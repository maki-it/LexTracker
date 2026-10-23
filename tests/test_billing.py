import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.calculation import build_draft
from billing.lexware import invoice_payload
from billing.models import BillingAgreement, Invoice
from billing.periods import Period, period_containing, periods_between, recent_periods
from billing.services import create_invoice
from core.models import AppSettings
from lexware.client import LexwareClient, LexwareError
from lexware.schemas import Profile
from projects.models import Project, Task
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def work(user, task, day: str, hours: float, start_hour: int = 9) -> TimeEntry:
    start = datetime.fromisoformat(f"{day}T{start_hour:02d}:00").replace(tzinfo=timezone.get_current_timezone())
    return TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(hours=hours))


@pytest.fixture
def customer(task):
    customer = task.project.customer
    customer.default_hourly_rate = Decimal("100.00")
    customer.lexware_id = uuid.uuid4()
    customer.save()
    return customer


def retainer(customer, **kwargs) -> BillingAgreement:
    values = {
        "kind": BillingAgreement.Kind.RETAINER,
        "period": Period.QUARTER,
        "included_hours": Decimal("20"),
        "fixed_price": Decimal("1800.00"),
        "valid_from": date(2026, 1, 1),
    }
    return BillingAgreement.objects.create(customer=customer, **(values | kwargs))


# Periods


def test_period_containing():
    assert period_containing(date(2026, 11, 5), Period.QUARTER).label == "Q4/2026"
    assert period_containing(date(2026, 11, 5), Period.QUARTER).end == date(2026, 12, 31)
    assert period_containing(date(2026, 2, 10), Period.MONTH).end == date(2026, 2, 28)
    assert period_containing(date(2026, 2, 10), Period.YEAR).label == "2026"


def test_periods_between_and_recent():
    assert [p.label for p in periods_between(date(2026, 2, 15), date(2026, 7, 1), Period.QUARTER)] == [
        "Q1/2026",
        "Q2/2026",
        "Q3/2026",
    ]
    assert [p.label for p in recent_periods(date(2026, 1, 10), Period.MONTH, 3)] == ["01/2026", "12/2025", "11/2025"]


# Calculation


def test_hourly_lines_grouped_by_task_with_rate_fallback(user, task, customer):
    design = Task.objects.create(project=task.project, name="Design", hourly_rate=Decimal("120.00"))
    work(user, task, "2026-10-05", 1.5)
    work(user, task, "2026-10-06", 2)
    work(user, design, "2026-10-07", 1)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    lines = {line.name: line for line in draft.lines}
    assert lines["Website · Entwicklung"].quantity == Decimal("3.50")
    assert lines["Website · Entwicklung"].unit_price == Decimal("100.00")
    assert lines["Website · Design"].total == Decimal("120.00")
    assert draft.total == Decimal("470.00")
    assert draft.can_be_invoiced


def test_excludes_billed_non_billable_and_out_of_range(user, task, customer):
    work(user, task, "2026-10-05", 1)
    TimeEntry.objects.filter(pk=work(user, task, "2026-10-06", 1).pk).update(is_billable=False)
    work(user, task, "2026-11-01", 1)
    invoice = Invoice.objects.create(
        customer=customer, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30), total_net=0
    )
    TimeEntry.objects.filter(pk=work(user, task, "2026-10-07", 1).pk).update(invoice=invoice)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    assert draft.duration == timedelta(hours=1)


def test_missing_rate_blocks_invoice(user, task, customer):
    customer.default_hourly_rate = None
    customer.save()
    work(user, task, "2026-10-05", 1)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    assert draft.problems
    assert not draft.can_be_invoiced


def test_retainer_within_contingent_bills_fixed_price_only(user, task, customer):
    retainer(customer)
    work(user, task, "2026-10-05", 8)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 12, 31))

    assert [(line.name, line.total) for line in draft.lines] == [("Retainer Q4/2026", Decimal("1800.00"))]


def test_retainer_overage_billed_at_overage_rate(user, task, customer):
    retainer(customer, overage_rate=Decimal("110.00"))
    work(user, task, "2026-10-05", 8)
    work(user, task, "2026-10-12", 8)
    work(user, task, "2026-11-02", 6.5)  # 2.5 h over the 20 h

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 12, 31))

    overage = draft.lines[1]
    assert overage.name == "Mehrstunden Q4/2026: Website · Entwicklung"
    assert overage.quantity == Decimal("2.50")
    assert overage.unit_price == Decimal("110.00")
    assert draft.total == Decimal("2075.00")

    # The preview lists the time behind each line; the split entry appears in both.
    included, extra = draft.lines[0].entries, overage.entries
    assert [e.duration for e in included] == [timedelta(hours=8), timedelta(hours=8), timedelta(hours=4)]
    assert [e.duration for e in extra] == [timedelta(hours=2.5)]


def test_retainer_overage_falls_back_to_normal_rate(user, task, customer):
    retainer(customer, included_hours=Decimal("1"))
    work(user, task, "2026-10-05", 3)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 12, 31))

    assert draft.lines[1].quantity == Decimal("2.00")
    assert draft.lines[1].unit_price == Decimal("100.00")


def test_global_settings_give_fallback_rate(user, task, customer):
    customer.default_hourly_rate = None
    customer.save()
    AppSettings.objects.create(pk=1, default_hourly_rate=Decimal("80.00"))
    work(user, task, "2026-10-05", 1)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    assert draft.lines[0].unit_price == Decimal("80.00")


# Lexware


def test_invoice_payload(user, task, customer):
    work(user, task, "2026-10-05", 2)
    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    payload = invoice_payload(draft, date(2026, 11, 3), Profile())

    assert payload["address"] == {"contactId": str(customer.lexware_id)}
    assert payload["voucherDate"].startswith("2026-11-03T00:00:00.000+")
    assert payload["shippingConditions"]["shippingType"] == "serviceperiod"
    assert payload["lineItems"][0]["quantity"] == 2.0
    assert payload["lineItems"][0]["unitPrice"] == {"currency": "EUR", "netAmount": 100.0, "taxRatePercentage": 19.0}
    assert payload["taxConditions"] == {"taxType": "net"}


def test_invoice_payload_for_small_business(user, task, customer):
    work(user, task, "2026-10-05", 2)
    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    payload = invoice_payload(draft, date(2026, 11, 3), Profile(smallBusiness=True, taxType="vatfree"))

    assert payload["taxConditions"] == {"taxType": "vatfree"}
    assert payload["lineItems"][0]["unitPrice"]["taxRatePercentage"] == 0.0


def fake_lexware(requests: list):
    lexware_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/profile"):
            return httpx.Response(200, json={"companyName": "Maki IT", "taxType": "net", "smallBusiness": False})
        requests.append(request)
        return httpx.Response(201, json={"id": str(lexware_id), "version": 1})

    return LexwareClient("test-key", requests_per_second=0, transport=httpx.MockTransport(handler)), lexware_id


@pytest.mark.django_db(transaction=True)
async def test_create_invoice_marks_entries_as_billed(user, task, customer):
    entry = await TimeEntry.objects.acreate(
        user=user,
        task=task,
        started_at=datetime(2026, 10, 5, 9, tzinfo=timezone.get_current_timezone()),
        ended_at=datetime(2026, 10, 5, 11, tzinfo=timezone.get_current_timezone()),
    )
    requests = []
    client, lexware_id = fake_lexware(requests)

    async with client:
        invoice = await create_invoice(client, customer, date(2026, 10, 1), date(2026, 10, 31))

    await entry.arefresh_from_db()
    assert entry.invoice_id == invoice.pk
    assert invoice.lexware_id == lexware_id
    assert invoice.total_net == Decimal("200.00")
    assert requests[0].method == "POST"
    assert json.loads(requests[0].content)["lineItems"][0]["name"] == "Website · Entwicklung"

    # Nothing left to bill for the same period.
    async with fake_lexware([])[0] as client:
        with pytest.raises(LexwareError, match="nichts abzurechnen"):
            await create_invoice(client, customer, date(2026, 10, 1), date(2026, 10, 31))


# Views


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_billing_pages(logged_in, user, task, customer):
    work(user, task, "2026-10-05", 2)

    assert "2:00 h" in logged_in.get(reverse("billing:overview")).text
    response = logged_in.get(
        reverse("billing:customer", args=[customer.pk]), {"start": "2026-10-01", "end": "2026-10-31"}
    )
    assert "200,00 €" in response.text
    assert "Rechnungsentwurf in Lexware anlegen" in response.text


def test_create_retainer_agreement(logged_in, customer):
    response = logged_in.post(
        reverse("billing:agreement_create", args=[customer.pk]),
        {"kind": "retainer", "period": "quarter", "valid_from": "2026-01-01"},
    )
    assert "Für einen Retainer erforderlich." in response.text

    logged_in.post(
        reverse("billing:agreement_create", args=[customer.pk]),
        {
            "kind": "retainer",
            "period": "quarter",
            "valid_from": "2026-01-01",
            "included_hours": "20",
            "fixed_price": "1800",
        },
    )
    assert customer.billing_agreements.get().included_hours == Decimal("20")


def test_agreements_must_not_overlap(logged_in, customer):
    retainer(customer, valid_until=date(2026, 6, 30))
    url = reverse("billing:agreement_create", args=[customer.pk])

    response = logged_in.post(url, {"kind": "hourly", "period": "month", "valid_from": "2026-06-01"})
    assert "Für diesen Zeitraum gilt schon eine andere Vereinbarung." in response.text

    logged_in.post(url, {"kind": "hourly", "period": "month", "valid_from": "2026-07-01"})
    assert customer.billing_agreements.count() == 2


def test_preview_lists_the_entries_of_a_line(logged_in, user, task, customer):
    entry = work(user, task, "2026-10-05", 1.5)
    entry.description = "Startseite gestaltet"
    entry.save()

    response = logged_in.get(
        reverse("billing:customer", args=[customer.pk]), {"start": "2026-10-01", "end": "2026-10-31"}
    )
    assert "Startseite gestaltet" in response.text and "09:00–10:30" in response.text


def test_period_options_mark_open_time_and_span_months(logged_in, user, task, customer, monkeypatch):
    monkeypatch.setattr("billing.views.timezone.localdate", lambda *a: date(2026, 10, 22))
    work(user, task, "2026-01-30", 2)
    work(user, task, "2026-02-01", 1)
    url = reverse("billing:customer", args=[customer.pk])

    response = logged_in.get(url)
    options = {o.label: o for o in response.context["period_options"]}
    # Recent months without time are shown but have no open time; old months with time are added.
    assert options["09/2026"].open_time == timedelta(0)
    assert options["01/2026"].open_time == timedelta(hours=2)
    everything = options["Alle offenen"]
    assert (everything.start, everything.end, everything.open_time) == (
        date(2026, 1, 30),
        date(2026, 2, 1),
        timedelta(hours=3),
    )
    # September has no open time, so all open time is preselected.
    assert response.context["draft"].total == Decimal("300.00")
    assert "pill-muted" in response.text

    # Changing the dates also swaps the pills, so the matching one is marked.
    response = logged_in.get(
        url, {"start": "2026-01-30", "end": "2026-02-01"}, headers={"HX-Request": "true", "HX-Target": "preview"}
    )
    assert 'id="period-pills"' in response.text and 'hx-swap-oob="true"' in response.text
    assert "300,00 €" in response.text


def test_sidebar_counts(logged_in, user, task, customer):
    response = logged_in.get(reverse("core:dashboard"))
    assert response.wsgi_request.nav_counts == {"projects": 1, "billable_customers": 0}

    work(user, task, "2026-10-05", 2)
    response = logged_in.get(reverse("core:dashboard"))
    assert response.wsgi_request.nav_counts["billable_customers"] == 1
    assert 'title="Kunden mit offenen, abrechenbaren Zeiten">1<' in response.text


# Open entries of a customer


def entries_url(customer) -> str:
    return reverse("billing:customer_entries", args=[customer.pk])


def test_overview_links_the_customer_to_its_open_entries(logged_in, user, task, customer):
    assert entries_url(customer) not in logged_in.get(reverse("billing:overview"), {"alle": "1"}).text
    work(user, task, "2026-10-05", 2)

    page = logged_in.get(reverse("billing:overview")).text
    assert f'hx-get="{entries_url(customer)}" hx-target="#dialog-body"' in page


def test_open_entries_by_project_with_sums(logged_in, user, task, customer):
    app = Project.objects.create(customer=customer, name="App", hourly_rate=Decimal("80.00"))
    concept = Task.objects.create(project=app, name="Konzept")
    entry = work(user, task, "2026-10-05", 1.5)
    entry.description = "Startseite gestaltet"
    entry.save()
    work(user, concept, "2026-10-06", 2)
    # A running timer is not billable yet.
    TimeEntry.objects.create(user=user, task=task, started_at=timezone.now())

    response = logged_in.get(entries_url(customer))

    groups = {s["group"].project.name: s["group"] for s in response.context["sections"]}
    assert set(groups) == {"App", "Website"}
    assert (groups["Website"].duration, groups["Website"].amount) == (timedelta(hours=1.5), Decimal("150.00"))
    assert (groups["App"].duration, groups["App"].amount) == (timedelta(hours=2), Decimal("160.00"))
    row = groups["Website"].rows[0]
    assert (row.rate, row.amount, row.entry.user) == (Decimal("100.00"), Decimal("150.00"), user)
    assert "Startseite gestaltet" in response.text and "Konzept" in response.text
    assert response.context["draft"].total == Decimal("310.00")
    assert "Hauptnavigation" in response.text


def test_open_entries_in_dialog(logged_in, user, task, customer):
    work(user, task, "2026-10-05", 1)
    response = logged_in.get(entries_url(customer), headers={"HX-Request": "true", "HX-Target": "dialog-body"})
    assert "Hauptnavigation" not in response.text and "dialog-wide" in response.text


def test_open_entries_leave_out_billed_and_not_billable_time(logged_in, user, task, customer):
    billed = work(user, task, "2026-10-05", 1)
    invoice = Invoice.objects.create(
        customer=customer, period_start=date(2026, 10, 1), period_end=date(2026, 10, 31), total_net=Decimal("100")
    )
    TimeEntry.objects.filter(pk=billed.pk).update(invoice=invoice)
    free = work(user, task, "2026-10-06", 1)
    TimeEntry.objects.filter(pk=free.pk).update(is_billable=False)

    response = logged_in.get(entries_url(customer))
    assert response.context["draft"] is None
    assert "Alles ist abgerechnet" in response.text


def test_open_entries_without_a_rate_are_marked(logged_in, user, task, customer):
    customer.default_hourly_rate = None
    customer.save()
    work(user, task, "2026-10-05", 1)

    response = logged_in.get(entries_url(customer))
    row = response.context["sections"][0]["rows"][0]
    assert not row.has_rate and row.amount is None
    assert "kein Satz" in response.text and "kein Stundensatz hinterlegt" in response.text


def test_open_entries_in_a_retainer(logged_in, user, task, customer):
    retainer(customer, period=Period.MONTH, included_hours=Decimal("3"), fixed_price=Decimal("300.00"))
    work(user, task, "2026-10-05", 2)
    work(user, task, "2026-10-06", 2)

    response = logged_in.get(entries_url(customer))

    first, second = response.context["sections"][0]["rows"]
    assert (first.included, first.billed, first.amount) == (timedelta(hours=2), timedelta(0), None)
    # The second entry is split: one hour still fits, the other one is billed extra.
    assert (second.included, second.billed, second.amount) == (
        timedelta(hours=1),
        timedelta(hours=1),
        Decimal("100.00"),
    )
    assert response.context["retainer_total"] == Decimal("300.00")
    assert response.context["draft"].total == Decimal("400.00")
    assert "im Retainer" in response.text and "1:00 h im Retainer" in response.text


def test_open_entries_are_paged_per_project(logged_in, user, task, customer, monkeypatch):
    monkeypatch.setattr("billing.views.ENTRIES_PER_PAGE", 2)
    for day in range(1, 6):
        work(user, task, f"2026-10-{day:02d}", 1)
    htmx = {"HX-Request": "true", "HX-Target": "more"}

    first = logged_in.get(entries_url(customer))
    assert first.text.count("<tr") == 1 + 2 + 1  # head, two rows, "more"
    assert "Weitere 3 Zeiteinträge anzeigen" in first.text

    url = f"{entries_url(customer)}?projekt={task.project_id}"
    second = logged_in.get(f"{url}&seite=2", headers=htmx)
    assert second.text.count("<tr") == 3 and "Weitere 1 Zeiteintrag anzeigen" in second.text
    last = logged_in.get(f"{url}&seite=3", headers=htmx)
    assert last.text.count("<tr") == 1 and "Weitere" not in last.text


def test_open_entries_query_count_does_not_grow_with_entries(
    logged_in, user, task, customer, django_assert_max_num_queries
):
    work(user, task, "2026-10-01", 1)
    with CaptureQueriesContext(connection) as few:
        logged_in.get(entries_url(customer))
    for day in range(2, 29):
        work(user, task, f"2026-10-{day:02d}", 1)
    with django_assert_max_num_queries(len(few)):
        logged_in.get(entries_url(customer))


def test_open_entries_are_for_administrators_only(client, task, customer):
    employee = User.objects.create_user(username="ma", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)
    assert client.get(entries_url(customer)).status_code == 403
