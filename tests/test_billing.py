import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from billing.calculation import build_draft
from billing.lexware import invoice_payload
from billing.models import BillingAgreement, Invoice
from billing.periods import Period, period_containing, periods_between, recent_periods
from billing.services import create_invoice
from lexware.client import LexwareClient, LexwareError
from projects.models import Task
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


def test_retainer_overage_falls_back_to_normal_rate(user, task, customer):
    retainer(customer, included_hours=Decimal("1"))
    work(user, task, "2026-10-05", 3)

    draft = build_draft(customer, date(2026, 10, 1), date(2026, 12, 31))

    assert draft.lines[1].quantity == Decimal("2.00")
    assert draft.lines[1].unit_price == Decimal("100.00")


# Lexware


def test_invoice_payload(user, task, customer, settings):
    settings.INVOICE_TAX_RATE = Decimal("19")
    work(user, task, "2026-10-05", 2)
    draft = build_draft(customer, date(2026, 10, 1), date(2026, 10, 31))

    payload = invoice_payload(draft, date(2026, 11, 3))

    assert payload["address"] == {"contactId": str(customer.lexware_id)}
    assert payload["voucherDate"].startswith("2026-11-03T00:00:00.000+")
    assert payload["shippingConditions"]["shippingType"] == "serviceperiod"
    assert payload["lineItems"][0]["quantity"] == 2.0
    assert payload["lineItems"][0]["unitPrice"] == {"currency": "EUR", "netAmount": 100.0, "taxRatePercentage": 19.0}


def fake_lexware(requests: list):
    lexware_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
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
