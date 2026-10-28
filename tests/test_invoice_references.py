"""Referencing Lexware quotations and assigning time to invoices that were written in Lexware."""

import json
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import Invoice
from billing.services import assign_to_invoice, create_invoice
from billing.sync import sync_invoices
from customers.models import Customer
from lexware.client import LexwareError
from tests.lexware_fakes import fake_client
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db(transaction=True)

DIALOG = {"HX-Request": "true", "HX-Target": "dialog-body"}
PERIOD = {"start": "2026-10-01", "end": "2026-10-31"}


@pytest.fixture
def customer(task):
    customer = task.project.customer
    customer.default_hourly_rate = Decimal("100.00")
    customer.lexware_id = uuid.uuid4()
    customer.save()
    return customer


@pytest.fixture
def entry(user, task, customer):
    start = datetime(2026, 10, 5, 9, tzinfo=timezone.get_current_timezone())
    return TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(hours=2))


def written_in_lexware(customer, **extra) -> Invoice:
    values = {
        "customer": customer,
        "origin": Invoice.Origin.LEXWARE,
        "lexware_id": uuid.uuid4(),
        "period_start": date(2026, 10, 1),
        "period_end": date(2026, 10, 31),
        "total_net": Decimal("1500.00"),
        "status": Invoice.Status.DRAFT,
    }
    return Invoice.objects.create(**(values | extra))


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def quotation_fake(customer, *, quotation_id=None, number="AG-2026-10-0013", contact_id=None):
    """Lexware: the profile, a quotation, the invoice that gets created, and the voucher list of quotations."""
    quotation_id = quotation_id or uuid.uuid4()
    invoice_id = uuid.uuid4()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"companyName": "Maki IT", "taxType": "net", "smallBusiness": False})
        if path.endswith(f"/quotations/{quotation_id}"):
            contact = str(contact_id or customer.lexware_id)
            return httpx.Response(200, json={"voucherNumber": number, "address": {"contactId": contact}})
        if path.endswith("/voucherlist"):
            voucher = {
                "id": str(quotation_id),
                "voucherType": "quotation",
                "voucherStatus": "accepted",
                "voucherNumber": number,
                "voucherDate": "2026-10-12T00:00:00.000+02:00",
                "totalAmount": 1785.0,
            }
            return httpx.Response(200, json={"content": [voucher], "number": 0, "totalPages": 1, "last": True})
        if path.endswith("/invoices") and request.method == "POST":
            return httpx.Response(201, json={"id": str(invoice_id), "version": 1})
        return httpx.Response(404, json={"message": "not found"})

    handler.requests = requests
    handler.quotation_id = quotation_id
    handler.invoice_id = invoice_id
    return handler


# Quotation reference


async def test_invoice_is_created_as_follow_up_of_the_quotation(customer, entry):
    handler = quotation_fake(customer)

    async with fake_client(handler) as client:
        invoice = await create_invoice(client, customer, date(2026, 10, 1), date(2026, 10, 31), handler.quotation_id)

    post = next(r for r in handler.requests if r.method == "POST")
    assert post.url.params["precedingSalesVoucherId"] == str(handler.quotation_id)
    assert "finalize" not in post.url.params
    assert json.loads(post.content)["lineItems"][0]["name"] == "Entwicklung"
    assert invoice.quotation_number == "AG-2026-10-0013"
    await entry.arefresh_from_db()
    assert entry.invoice_id == invoice.pk


async def test_invoice_without_quotation_has_no_reference(customer, entry):
    handler = quotation_fake(customer)

    async with fake_client(handler) as client:
        invoice = await create_invoice(client, customer, date(2026, 10, 1), date(2026, 10, 31))

    post = next(r for r in handler.requests if r.method == "POST")
    assert "precedingSalesVoucherId" not in post.url.params
    assert invoice.quotation_number == ""
    assert not any(r.url.path.endswith("/voucherlist") or "/quotations/" in r.url.path for r in handler.requests)


async def test_quotation_of_another_contact_is_refused(customer, entry):
    handler = quotation_fake(customer, contact_id=uuid.uuid4())

    async with fake_client(handler) as client:
        with pytest.raises(LexwareError, match="nicht zu diesem Kunden"):
            await create_invoice(client, customer, date(2026, 10, 1), date(2026, 10, 31), handler.quotation_id)

    assert not any(r.method == "POST" for r in handler.requests)
    await entry.arefresh_from_db()
    assert entry.invoice_id is None


async def test_quotations_are_asked_for_by_contact_and_status(customer):
    handler = quotation_fake(customer)

    async with fake_client(handler) as client:
        found = await client.list_quotations(customer.lexware_id)

    params = handler.requests[0].url.params
    assert params["voucherType"] == "quotation" and params["voucherStatus"] == "open,accepted"
    assert params["contactId"] == str(customer.lexware_id)
    assert [q.voucher_number for q in found] == ["AG-2026-10-0013"]


def test_quotation_field_lists_the_quotations(logged_in, customer, monkeypatch):
    handler = quotation_fake(customer)
    monkeypatch.setattr("billing.views.client_from_settings", lambda: fake_client(handler))

    html = logged_in.get(reverse("billing:quotation_options", args=[customer.pk])).text

    assert 'name="quotation"' in html and f'value="{handler.quotation_id}"' in html
    assert "AG-2026-10-0013 · 12.10.2026 · 1785,00 € brutto · Angenommen" in html


def test_quotation_field_is_empty_without_quotations(logged_in, customer, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"content": [], "number": 0, "totalPages": 1, "last": True})

    monkeypatch.setattr("billing.views.client_from_settings", lambda: fake_client(handler))

    assert 'name="quotation"' not in logged_in.get(reverse("billing:quotation_options", args=[customer.pk])).text


def test_quotation_field_says_when_lexware_cannot_be_reached(logged_in, customer, monkeypatch):
    def handler(request):
        return httpx.Response(500, json={"message": "kaputt"})

    monkeypatch.setattr("billing.views.client_from_settings", lambda: fake_client(handler))

    html = logged_in.get(reverse("billing:quotation_options", args=[customer.pk])).text

    assert "konnten nicht geladen werden" in html and 'name="quotation"' not in html


def test_create_view_passes_the_chosen_quotation(logged_in, customer, entry, monkeypatch):
    handler = quotation_fake(customer)
    monkeypatch.setattr("billing.views.client_from_settings", lambda: fake_client(handler))

    response = logged_in.post(
        reverse("billing:invoice_create", args=[customer.pk]), {**PERIOD, "quotation": str(handler.quotation_id)}
    )

    assert response.status_code == 302
    assert Invoice.objects.get(lexware_id=handler.invoice_id).quotation_number == "AG-2026-10-0013"


def test_preview_offers_quotation_and_assignment(logged_in, customer, entry):
    html = logged_in.get(reverse("billing:customer", args=[customer.pk]), PERIOD).text

    assert reverse("billing:quotation_options", args=[customer.pk]) in html
    assert "Bestehende Rechnung zuordnen" in html
    assert f"{reverse('billing:invoice_assign', args=[customer.pk])}?start=2026-10-01&amp;end=2026-10-31" in html


# Invoices written in Lexware


def test_open_time_is_assigned_to_an_invoice_written_in_lexware(customer, entry):
    invoice = written_in_lexware(customer)

    assert assign_to_invoice(customer, invoice, date(2026, 10, 1), date(2026, 10, 31)) == 1

    entry.refresh_from_db()
    assert entry.invoice_id == invoice.pk
    invoice.refresh_from_db()
    assert invoice.total_net == Decimal("1500.00")  # Lexware's amount stays.


def test_assigned_time_is_no_longer_open(customer, entry):
    assign_to_invoice(customer, written_in_lexware(customer), date(2026, 10, 1), date(2026, 10, 31))

    with pytest.raises(LexwareError, match="nichts abzurechnen"):
        assign_to_invoice(customer, written_in_lexware(customer), date(2026, 10, 1), date(2026, 10, 31))


@pytest.mark.parametrize("status", [Invoice.Status.DELETED, Invoice.Status.VOIDED])
def test_gone_invoices_take_no_time(customer, entry, status):
    invoice = written_in_lexware(customer, status=status)

    with pytest.raises(LexwareError):
        assign_to_invoice(customer, invoice, date(2026, 10, 1), date(2026, 10, 31))


def test_invoices_made_here_and_of_other_customers_take_no_time(customer, entry):
    made_here = written_in_lexware(customer, origin=Invoice.Origin.APP)
    other = written_in_lexware(Customer.objects.create(name="Andere GmbH", lexware_id=uuid.uuid4()))

    for invoice in (made_here, other):
        with pytest.raises(LexwareError):
            assign_to_invoice(customer, invoice, date(2026, 10, 1), date(2026, 10, 31))
    entry.refresh_from_db()
    assert entry.invoice_id is None


def test_assign_dialog_lists_only_assignable_invoices(logged_in, customer, entry):
    written_in_lexware(customer, voucher_number="RE-1", status=Invoice.Status.OPEN, quotation_number="AG-7")
    written_in_lexware(customer, voucher_number="RE-2", status=Invoice.Status.VOIDED)
    written_in_lexware(customer, voucher_number="RE-3", status=Invoice.Status.DELETED)
    written_in_lexware(customer, origin=Invoice.Origin.APP, voucher_number="RE-4")

    html = logged_in.get(reverse("billing:invoice_assign", args=[customer.pk]), PERIOD, headers=DIALOG).text

    assert "RE-1" in html and "Angebot AG-7" in html
    assert "RE-2" not in html and "RE-3" not in html and "RE-4" not in html
    assert "Hauptnavigation" not in html
    assert "In Lexware wird nichts geändert" in html


def test_assign_view_assigns_and_goes_back_to_the_period(logged_in, customer, entry):
    invoice = written_in_lexware(customer, voucher_number="RE-1")

    response = logged_in.post(
        reverse("billing:invoice_assign", args=[customer.pk]), {**PERIOD, "invoice": str(invoice.pk)}, headers=DIALOG
    )

    assert response.status_code == 200 and response["HX-Refresh"] == "true"
    entry.refresh_from_db()
    assert entry.invoice_id == invoice.pk


def test_assign_view_refuses_an_unknown_invoice(logged_in, customer, entry):
    response = logged_in.post(
        reverse("billing:invoice_assign", args=[customer.pk]), {**PERIOD, "invoice": str(uuid.uuid4())}
    )

    assert response.status_code == 302
    entry.refresh_from_db()
    assert entry.invoice_id is None


def test_invoice_list_shows_quotation_and_assigned_time(logged_in, customer, entry):
    invoice = written_in_lexware(customer, voucher_number="RE-1", quotation_number="AG-2026-10-0013")
    assign_to_invoice(customer, invoice, date(2026, 10, 1), date(2026, 10, 31))

    html = logged_in.get(reverse("billing:invoices")).text

    assert "Angebot AG-2026-10-0013" in html
    assert "1 Zeiteintrag zugeordnet" in html


# Sync


async def test_sync_takes_the_quotation_reference_over_from_lexware(customer):
    lexware_id = str(uuid.uuid4())
    voucher = {
        "id": lexware_id,
        "voucherType": "invoice",
        "voucherStatus": "draft",
        "contactId": str(customer.lexware_id),
    }
    related = [
        {"id": str(uuid.uuid4()), "voucherNumber": "LS-1", "voucherType": "deliverynote"},
        {"id": str(uuid.uuid4()), "voucherNumber": "AG-2026-10-0013", "voucherType": "quotation"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/voucherlist"):
            return httpx.Response(200, json={"content": [voucher], "number": 0, "totalPages": 1, "last": True})
        return httpx.Response(200, json={"id": lexware_id, "relatedVouchers": related})

    async with fake_client(handler) as client:
        await sync_invoices(client)

    assert (await Invoice.objects.aget(lexware_id=lexware_id)).quotation_number == "AG-2026-10-0013"


async def test_assigned_invoice_deleted_in_lexware_releases_its_time(user, task, customer):
    invoice = await Invoice.objects.acreate(
        customer=customer,
        origin=Invoice.Origin.LEXWARE,
        lexware_id=uuid.uuid4(),
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        total_net=Decimal("100.00"),
    )
    start = datetime(2026, 10, 5, 9, tzinfo=timezone.get_current_timezone())
    entry = await TimeEntry.objects.acreate(
        user=user, task=task, started_at=start, ended_at=start + timedelta(hours=1), invoice=invoice
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/voucherlist"):
            return httpx.Response(200, json={"content": [], "number": 0, "totalPages": 1, "last": True})
        return httpx.Response(404, json={"message": "not found"})

    async with fake_client(handler) as client:
        result = await sync_invoices(client)

    assert result.deleted == 1
    await entry.arefresh_from_db()
    assert entry.invoice_id is None
    assert (await Invoice.objects.aget(pk=invoice.pk)).status == Invoice.Status.DELETED


# The time behind an invoice


def test_invoice_entries_dialog_lists_the_assigned_time(logged_in, user, task, customer, entry):
    entry.description = "Startseite gestaltet"
    entry.save()
    other = TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=datetime(2026, 11, 2, 9, tzinfo=timezone.get_current_timezone()),
        ended_at=datetime(2026, 11, 2, 10, tzinfo=timezone.get_current_timezone()),
    )
    invoice = written_in_lexware(customer, voucher_number="RE-1", quotation_number="AG-7")
    assign_to_invoice(customer, invoice, date(2026, 10, 1), date(2026, 10, 31))

    html = logged_in.get(reverse("billing:invoice_entries", args=[invoice.pk]), headers=DIALOG).text

    assert "Zeiten der Rechnung RE-1" in html and "Angebot AG-7" in html
    assert "Startseite gestaltet" in html and f"{task.project.name} · {task.name}" in html
    assert "1 Zeiteintrag, Summe" in html and "2:00 h" in html
    assert "aus Lexware zugeordnet" in html
    assert "Hauptnavigation" not in html
    # Time of another period stays out.
    assert other.description == "" and "02.11.2026" not in html


def test_invoice_entries_dialog_says_when_nothing_is_assigned(logged_in, customer):
    invoice = written_in_lexware(customer)

    html = logged_in.get(reverse("billing:invoice_entries", args=[invoice.pk])).text

    assert "keine Zeiteinträge zugeordnet" in html


def test_invoice_entries_of_an_unknown_invoice_are_404(logged_in):
    assert logged_in.get(reverse("billing:invoice_entries", args=[uuid.uuid4()])).status_code == 404


def test_invoice_list_links_the_time_of_every_invoice(logged_in, customer, entry):
    written_here = written_in_lexware(customer, origin=Invoice.Origin.APP, voucher_number="RE-9")
    entry.invoice = written_here
    entry.save()
    url = reverse("billing:invoice_entries", args=[written_here.pk])

    html = logged_in.get(reverse("billing:invoices")).text

    assert f'href="{url}"' in html and "1 Zeiteintrag<" in html and "zugeordnet" not in html


# Order of the invoices


def test_customer_page_sorts_invoices_by_date_then_number(logged_in, customer):
    # An old number with a late service period must not come first, and a draft counts with its creation date.
    written_in_lexware(customer, voucher_number="RE-1", voucher_date=date(2026, 10, 20), period_end=date(2027, 4, 19))
    written_in_lexware(customer, voucher_number="RE-2", voucher_date=date(2026, 4, 20), period_end=date(2026, 10, 19))
    written_in_lexware(customer, voucher_number="RE-3", voucher_date=date(2026, 10, 20), period_end=date(2026, 10, 20))
    draft = written_in_lexware(customer, voucher_date=timezone.localdate() + timedelta(days=1))

    page = logged_in.get(reverse("billing:customer", args=[customer.pk])).text

    assert draft.status == Invoice.Status.DRAFT
    positions = [page.index(number) for number in ("RE-3", "RE-1", "RE-2")]
    assert positions == sorted(positions)
    assert page.index("Entwurf öffnen") < page.index("RE-3")


def test_assign_dialog_sorts_invoices_by_date_then_number(logged_in, customer, entry):
    written_in_lexware(customer, voucher_number="RE-1", voucher_date=date(2026, 9, 1))
    written_in_lexware(customer, voucher_number="RE-2", voucher_date=date(2026, 10, 1))
    written_in_lexware(customer, voucher_number="RE-3", voucher_date=date(2026, 10, 1))

    html = logged_in.get(reverse("billing:invoice_assign", args=[customer.pk]), PERIOD).text

    assert html.index("RE-3") < html.index("RE-2") < html.index("RE-1")
