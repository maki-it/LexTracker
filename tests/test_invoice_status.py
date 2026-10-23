import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from billing.sync import sync_and_record, sync_invoices
from core.models import AppSettings
from customers.models import Customer
from projects.models import Project, Task
from tests.lexware_fakes import fake_client
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db(transaction=True)


def voucher(invoice: Invoice, status: str, **extra) -> dict:
    return {"id": str(invoice.lexware_id), "voucherType": "invoice", "voucherStatus": status, **extra}


def voucher_list(*vouchers: dict):
    """A Lexware fake: the voucher list, plus GET /invoices/{id} answering 404 for ids not in ``known``."""
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/voucherlist"):
            return httpx.Response(200, json={"content": list(vouchers), "number": 0, "totalPages": 1, "last": True})
        invoice_id = request.url.path.rsplit("/", 1)[1]
        if invoice_id in handler.known:
            return httpx.Response(200, json={"id": invoice_id, **handler.known[invoice_id]})
        return httpx.Response(404, json={"message": "not found"})

    handler.requests = requests
    handler.known = {}
    return handler


@pytest.fixture
def billed():
    """An invoice draft with one billed time entry."""
    from accounts.models import User

    user = User.objects.create_user(username="kim", password="geheim-123")
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.uuid4())
    task = Task.objects.create(project=Project.objects.create(customer=customer, name="Website"), name="Entwicklung")
    invoice = Invoice.objects.create(
        customer=customer,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        total_net=Decimal("200.00"),
        lexware_id=uuid.uuid4(),
    )
    start = timezone.now() - timedelta(days=3)
    entry = TimeEntry.objects.create(
        user=user, task=task, started_at=start, ended_at=start + timedelta(hours=2), invoice=invoice
    )
    return user, invoice, entry


async def test_status_and_number_come_from_lexware(billed):
    _, invoice, _ = billed
    handler = voucher_list(voucher(invoice, "open", voucherNumber="RE0042", dueDate="2099-11-15T00:00:00.000+01:00"))

    async with fake_client(handler) as client:
        result = await sync_invoices(client)

    await invoice.arefresh_from_db()
    assert invoice.status == Invoice.Status.OPEN
    assert invoice.voucher_number == "RE0042"
    assert invoice.due_date == date(2099, 11, 15)
    assert "/v1/invoices/" not in str(handler.requests[-1].url)
    assert handler.requests[0].url.params["voucherStatus"] == "any"
    assert result.changed == 1
    assert "draft" not in invoice.lexware_url and "/view/" in invoice.lexware_url


async def test_open_invoice_past_due_date_is_overdue(billed):
    _, invoice, _ = billed
    handler = voucher_list(voucher(invoice, "open", dueDate="2020-01-15T00:00:00.000+01:00", openAmount=238.1))

    async with fake_client(handler) as client:
        await sync_invoices(client)

    await invoice.arefresh_from_db()
    assert invoice.status == Invoice.Status.OVERDUE
    assert invoice.open_amount == Decimal("238.10")


async def test_deleted_draft_releases_its_time(billed):
    _, invoice, entry = billed
    handler = voucher_list()

    async with fake_client(handler) as client:
        result = await sync_invoices(client)

    await invoice.arefresh_from_db()
    await entry.arefresh_from_db()
    assert invoice.status == Invoice.Status.DELETED
    assert invoice.lexware_url == ""
    assert entry.invoice_id is None
    assert result.deleted == 1
    assert "wieder freigegeben" in result.summary

    # Deleted invoices are final and not asked about again: only the list is fetched.
    async with fake_client(handler) as client:
        await sync_invoices(client)
    assert len(handler.requests) == 3 and handler.requests[-1].url.path.endswith("/voucherlist")


async def test_invoice_missing_from_list_but_still_there_is_not_deleted(billed):
    # For example an archived invoice: the voucher list may leave it out.
    _, invoice, entry = billed
    handler = voucher_list()
    handler.known[str(invoice.lexware_id)] = {"voucherStatus": "paid", "voucherNumber": "RE0007"}

    async with fake_client(handler) as client:
        await sync_invoices(client)

    await invoice.arefresh_from_db()
    await entry.arefresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    assert invoice.voucher_number == "RE0007"
    assert entry.invoice_id == invoice.pk


async def test_final_invoices_are_not_synced(billed):
    _, invoice, _ = billed
    await Invoice.objects.filter(pk=invoice.pk).aupdate(status=Invoice.Status.PAID)
    handler = voucher_list(voucher(invoice, "voided"))

    async with fake_client(handler) as client:
        result = await sync_invoices(client)

    await invoice.arefresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    # Neither updated nor looked up, nor taken over a second time.
    assert len(handler.requests) == 1 and result.imported == 0


async def test_invoices_written_in_lexware_are_taken_over(billed):
    _, invoice, _ = billed
    customer = await Customer.objects.aget(pk=invoice.customer_id)
    lexware_id, stranger_id = str(uuid.uuid4()), str(uuid.uuid4())
    handler = voucher_list(
        voucher(invoice, "draft"),
        {
            "id": lexware_id,
            "voucherType": "invoice",
            "voucherStatus": "open",
            "voucherNumber": "RE0100",
            "voucherDate": "2026-09-30T00:00:00.000+02:00",
            "dueDate": "2099-10-14T00:00:00.000+02:00",
            "contactId": str(customer.lexware_id),
        },
        # A contact LexTracker does not know.
        {"id": stranger_id, "voucherType": "invoice", "voucherStatus": "open", "contactId": str(uuid.uuid4())},
    )
    handler.known[lexware_id] = {
        "voucherDate": "2026-09-30T00:00:00.000+02:00",
        "totalPrice": {"totalNetAmount": 450.5},
        "shippingConditions": {
            "shippingType": "serviceperiod",
            "shippingDate": "2026-09-01T00:00:00.000+02:00",
            "shippingEndDate": "2026-09-30T00:00:00.000+02:00",
        },
    }

    async with fake_client(handler) as client:
        result = await sync_invoices(client)

    taken = await Invoice.objects.aget(lexware_id=lexware_id)
    assert taken.origin == Invoice.Origin.LEXWARE and taken.customer_id == customer.pk
    assert taken.voucher_number == "RE0100" and taken.status == Invoice.Status.OPEN
    assert taken.total_net == Decimal("450.50")
    assert (taken.period_start, taken.period_end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert taken.voucher_date == date(2026, 9, 30) and taken.due_date == date(2099, 10, 14)
    assert result.imported == 1 and "1 aus Lexware übernommen" in result.summary
    assert not await Invoice.objects.filter(lexware_id=stranger_id).aexists()

    # Next time it is only updated. Once gone from Lexware it is removed, as it was never ours.
    async with fake_client(handler) as client:
        assert (await sync_invoices(client)).imported == 0
    del handler.known[lexware_id]
    async with fake_client(voucher_list(voucher(invoice, "draft"))) as client:
        await sync_invoices(client)
    assert not await Invoice.objects.filter(lexware_id=lexware_id).aexists()


async def test_sync_is_recorded(billed, monkeypatch):
    _, invoice, _ = billed
    handler = voucher_list(voucher(invoice, "draft"))
    monkeypatch.setattr("billing.sync.client_from_settings", lambda: fake_client(handler))

    await sync_and_record()

    app_settings = await AppSettings.aload()
    assert app_settings.invoices_synced_at
    assert app_settings.invoices_sync_status == "0 geändert, 1 unverändert."


# Views


@pytest.fixture
def logged_in(client, billed):
    client.force_login(billed[0])
    return client


def test_invoice_list_filters_by_status(logged_in, billed):
    _, invoice, _ = billed
    other = Invoice.objects.create(
        customer=invoice.customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        total_net=Decimal("80.00"),
        status=Invoice.Status.PAID,
        voucher_number="RE0001",
    )
    url = reverse("billing:invoices")

    response = logged_in.get(url)
    assert "RE0001" in response.text and "200,00 €" in response.text
    assert "Entwürfe" in response.text and "Bezahlt" in response.text

    response = logged_in.get(url, {"status": "bezahlt"})
    assert "RE0001" in response.text and "200,00 €" not in response.text

    response = logged_in.get(url, {"status": "entwurf"})
    assert "RE0001" not in response.text and "200,00 €" in response.text

    response = logged_in.get(url, {"q": "RE0001"})
    assert "RE0001" in response.text and "200,00 €" not in response.text
    assert other.lexware_url == ""


def test_invoice_number_links_to_lexware(logged_in, billed):
    _, draft, _ = billed
    sent = Invoice.objects.create(
        customer=draft.customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        total_net=Decimal("80.00"),
        status=Invoice.Status.PAID,
        voucher_number="RE0001",
        lexware_id=uuid.uuid4(),
    )

    text = logged_in.get(reverse("billing:invoices")).text
    # The number is the link; there is no separate "open" link next to it.
    assert f'href="{sent.lexware_url}" target="_blank" rel="noopener">RE0001</a>' in text
    assert "In Lexware öffnen" not in text
    # A draft has no number yet, so its link to the draft in Lexware carries a label instead.
    assert f'href="{draft.lexware_url}" target="_blank" rel="noopener">Entwurf öffnen</a>' in text


def test_invoice_with_a_single_service_date_shows_only_that_date(logged_in, billed):
    _, invoice, _ = billed
    # Lexware's "service" and "delivery" types have only a shippingDate; sync stores it as start and end.
    Invoice.objects.create(
        customer=invoice.customer,
        period_start=date(2026, 10, 19),
        period_end=date(2026, 10, 19),
        total_net=Decimal("80.00"),
        status=Invoice.Status.OPEN,
        voucher_number="RE0002",
    )

    text = logged_in.get(reverse("billing:invoices")).text
    assert "19.10.2026" in text and "19.10.2026 – 19.10.2026" not in text
    assert "01.10.2026 – 31.10.2026" in text


def test_invoice_list_shows_due_date_and_days_overdue_below_the_badge(logged_in, billed):
    _, invoice, _ = billed
    today = timezone.localdate()

    def make(number, status, due_date, origin=Invoice.Origin.APP):
        return Invoice.objects.create(
            customer=invoice.customer,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            total_net=Decimal("10.00"),
            status=status,
            voucher_number=number,
            due_date=due_date,
            origin=origin,
        )

    make("RE-OPEN", Invoice.Status.OPEN, date(2031, 3, 5))
    make("RE-LATE", Invoice.Status.OVERDUE, today - timedelta(days=3), origin=Invoice.Origin.LEXWARE)
    make("RE-PAID", Invoice.Status.PAID, date(2031, 4, 6))

    text = logged_in.get(reverse("billing:invoices")).text
    assert "Fällig 05.03.2031" in text and "seit" not in text.split("Fällig 05.03.2031")[1].split("</span>")[0]
    assert f"Fällig {(today - timedelta(days=3)):%d.%m.%Y} · seit 3 Tagen" in text
    # Paid invoices need no due date; the Lexware origin is a small label with a tooltip, not running text.
    assert "06.04.2031" not in text
    assert text.count("badge-outline") == 1 and text.count("In Lexware Office erstellt") == 1


def test_days_overdue_counts_only_for_overdue_invoices():
    today = timezone.localdate()
    overdue = Invoice(status=Invoice.Status.OVERDUE, due_date=today - timedelta(days=1))
    assert overdue.days_overdue == 1
    assert Invoice(status=Invoice.Status.OVERDUE, due_date=None).days_overdue == 0
    assert Invoice(status=Invoice.Status.OPEN, due_date=today - timedelta(days=5)).days_overdue == 0


def test_overview_lists_only_customers_with_open_time(logged_in, billed):
    entry = billed[2]
    Customer.objects.create(name="Ohne Zeiten AG")
    url = reverse("billing:overview")

    # The only entry is billed, so nothing is open.
    response = logged_in.get(url)
    assert "Kein Kunde hat offene Zeiten" in response.text
    assert "Ohne Zeiten AG" in logged_in.get(url, {"alle": "1"}).text

    TimeEntry.objects.filter(pk=entry.pk).update(invoice=None)
    response = logged_in.get(url)
    assert "ACME GmbH" in response.text and "Ohne Zeiten AG" not in response.text


def test_voided_invoice_time_can_be_released(logged_in, billed):
    _, invoice, entry = billed
    url = reverse("billing:invoice_release", args=[invoice.pk])

    # Only voided invoices.
    assert logged_in.post(url).status_code == 404

    Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.VOIDED)
    assert "Zeiten freigeben" in logged_in.get(reverse("billing:invoices")).text
    response = logged_in.post(url, {"return_query": "status=storniert"})
    assert response.url == reverse("billing:invoices") + "?status=storniert"
    entry.refresh_from_db()
    assert entry.invoice_id is None
    assert "Zeiten freigeben" not in logged_in.get(reverse("billing:invoices")).text


def test_manual_sync_button(logged_in, billed, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    _, invoice, _ = billed
    handler = voucher_list(voucher(invoice, "open", voucherNumber="RE0042"))
    monkeypatch.setattr("billing.sync.client_from_settings", lambda: fake_client(handler))

    response = logged_in.post(reverse("billing:invoice_sync"), follow=True)

    assert "Rechnungsstatus abgeglichen: 1 geändert" in response.text
    assert "RE0042" in response.text


def test_due_dates_without_time_zone_are_accepted(billed):
    from billing.sync import _due_date
    from lexware.schemas import Voucher

    v = Voucher.model_validate({"id": str(uuid.uuid4()), "voucherStatus": "open", "dueDate": "2026-11-01T00:00:00"})
    assert _due_date(v) == datetime(2026, 11, 1).date()


def test_deleted_draft_is_labelled_as_a_draft_with_its_time_hint_in_the_status_cell(logged_in, billed):
    _, invoice, _ = billed
    other = dict(customer=invoice.customer, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.DELETED)
    Invoice.objects.create(**other, total_net=Decimal("10.00"), status=Invoice.Status.VOIDED, voucher_number="RE-V")
    Invoice.objects.create(**other, total_net=Decimal("20.00"), status=Invoice.Status.DELETED, voucher_number="RE-SENT")

    text = logged_in.get(reverse("billing:invoices")).text
    rows = {row.split("</tr>")[0] for row in text.split("<tr>")[2:]}
    deleted_draft = next(r for r in rows if "Entwurf gelöscht" in r)
    voided = next(r for r in rows if "RE-V" in r)
    deleted_sent = next(r for r in rows if "RE-SENT" in r)

    # The draft says so in its badge, and the hint sits in the status cell, not in an extra column.
    assert "Entwurf gelöscht" in deleted_draft and "In Lexware gelöscht" not in deleted_draft.replace(
        'title="In Lexware gelöscht"', ""
    )
    assert deleted_draft.count("Zeiten wieder offen") == 1
    assert deleted_draft.index("Zeiten wieder offen") < deleted_draft.index("line-through")
    # A voided invoice stays apart: its own label and color, no "time open" hint.
    assert "Storniert" in voided and "badge-warning" in voided and "Zeiten wieder offen" not in voided
    # Deleted after it got a number: no draft label, but time is open again too.
    assert "Entwurf gelöscht" not in deleted_sent and ">In Lexware gelöscht<" in deleted_sent
    assert "Zeiten wieder offen" in deleted_sent
    assert "badge-warning" not in deleted_draft and "badge-warning" not in deleted_sent


def test_deleted_draft_is_listed_under_drafts_and_deleted(logged_in, billed):
    _, invoice, _ = billed
    other = dict(customer=invoice.customer, period_start=date(2026, 9, 1), period_end=date(2026, 9, 30))
    Invoice.objects.filter(pk=invoice.pk).update(status=Invoice.Status.DELETED)  # 200,00 €, never had a number
    Invoice.objects.create(**other, total_net=Decimal("70.00"), status=Invoice.Status.DRAFT)
    Invoice.objects.create(**other, total_net=Decimal("20.00"), status=Invoice.Status.DELETED, voucher_number="RE-SENT")
    url = reverse("billing:invoices")

    def shown(*statuses):
        response = logged_in.get(url, {"status": list(statuses)})
        text = response.text
        return {amount for amount in ("200,00", "70,00", "20,00") if f"{amount} €" in text}, response

    # A deleted draft is still a draft, a deleted invoice that had a number is not.
    assert shown("entwurf")[0] == {"200,00", "70,00"}
    assert shown("geloescht")[0] == {"200,00", "20,00"}
    both, response = shown("entwurf", "geloescht")
    assert both == {"200,00", "70,00", "20,00"} and response.text.count("200,00 €") == 1
    counts = {pill.key: pill.count for pill in response.context["filters"]}
    assert counts["entwurf"] == 2 and counts["geloescht"] == 2
