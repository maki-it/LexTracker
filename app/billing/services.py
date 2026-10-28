from datetime import date
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext as _

from billing.calculation import Draft, build_draft
from billing.lexware import invoice_payload
from billing.models import Invoice
from billing.queries import newest_first
from core.ids import parse_uuid
from core.models import AppSettings
from customers.models import Customer
from lexware.client import LexwareClient, LexwareError, LexwareNotFound
from tracking.models import TimeEntry


@transaction.atomic
def _record_invoice(draft: Draft, lexware_id, quotation_number: str = "") -> Invoice:
    # update_or_create: the invoice sync may have taken the new draft over from Lexware in the meantime.
    invoice, _created = Invoice.objects.update_or_create(
        lexware_id=lexware_id,
        defaults={
            "customer": draft.customer,
            "origin": Invoice.Origin.APP,
            "period_start": draft.start,
            "period_end": draft.end,
            "total_net": draft.total,
            "quotation_number": quotation_number,
        },
    )
    TimeEntry.objects.filter(pk__in=[e.pk for e in draft.entries], invoice__isnull=True).update(invoice=invoice)
    return invoice


async def _quotation_number(client: LexwareClient, customer: Customer, quotation_id: UUID) -> str:
    """The number of the customer's quotation, so a quotation of someone else is never referenced."""
    try:
        data = await client.get_quotation(quotation_id)
    except LexwareNotFound as exc:
        raise LexwareError(_("Das Angebot gibt es in Lexware nicht (mehr).")) from exc
    if parse_uuid((data.get("address") or {}).get("contactId")) != customer.lexware_id:
        raise LexwareError(_("Das Angebot gehört in Lexware nicht zu diesem Kunden."))
    return data.get("voucherNumber") or ""


async def create_invoice(
    client: LexwareClient, customer: Customer, start: date, end: date, quotation_id: UUID | None = None
) -> Invoice:
    """Create an invoice draft in Lexware and mark the billed time entries.

    The draft is recalculated here, so entries added since the preview are included. With ``quotation_id``
    the draft refers to that quotation of the customer.
    """
    draft = await sync_to_async(build_draft)(customer, start, end)
    if not customer.lexware_id:
        raise LexwareError(_("Der Kunde ist nicht mit Lexware verknüpft. Importiere ihn zuerst aus Lexware."))
    if not draft.can_be_invoiced:
        raise LexwareError(" ".join(draft.problems) or _("Für diesen Zeitraum gibt es nichts abzurechnen."))
    quotation_number = await _quotation_number(client, customer, quotation_id) if quotation_id else ""
    profile = await client.get_profile()
    detail = (await AppSettings.aload()).invoice_detail
    payload = invoice_payload(draft, timezone.localdate(), profile, detail)
    lexware_id = await client.create_invoice(payload, quotation_id=quotation_id)
    return await sync_to_async(_record_invoice)(draft, lexware_id, quotation_number)


# Invoices of Lexware that open time can be assigned to: not gone or voided, written there and not by us.
ASSIGNABLE_EXCLUDED = [Invoice.Status.DELETED, Invoice.Status.VOIDED]


def assignable_invoices(customer: Customer):
    """The customer's invoices written in Lexware, newest first, that time can be assigned to."""
    invoices = customer.invoices.filter(origin=Invoice.Origin.LEXWARE).exclude(status__in=ASSIGNABLE_EXCLUDED)
    return newest_first(invoices.annotate(entry_count=Count("time_entries")))


@transaction.atomic
def assign_to_invoice(customer: Customer, invoice: Invoice, start: date, end: date) -> int:
    """Count the open time of the period as billed with an invoice that was written in Lexware.

    Nothing is changed in Lexware, and the invoice keeps its amount: the time only stops being open here.
    Returns how many time entries were assigned.
    """
    if invoice.customer_id != customer.pk or not assignable_invoices(customer).filter(pk=invoice.pk).exists():
        raise LexwareError(_("Dieser Rechnung können keine Zeiten zugeordnet werden."))
    draft = build_draft(customer, start, end)
    if not draft.entries:
        raise LexwareError(_("Für diesen Zeitraum gibt es nichts abzurechnen."))
    return TimeEntry.objects.filter(pk__in=[e.pk for e in draft.entries], invoice__isnull=True).update(invoice=invoice)
