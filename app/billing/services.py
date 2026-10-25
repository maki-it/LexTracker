from datetime import date

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from billing.calculation import Draft, build_draft
from billing.lexware import invoice_payload
from billing.models import Invoice
from core.models import AppSettings
from customers.models import Customer
from lexware.client import LexwareClient, LexwareError
from tracking.models import TimeEntry


@transaction.atomic
def _record_invoice(draft: Draft, lexware_id) -> Invoice:
    # update_or_create: the invoice sync may have taken the new draft over from Lexware in the meantime.
    invoice, _ = Invoice.objects.update_or_create(
        lexware_id=lexware_id,
        defaults={
            "customer": draft.customer,
            "origin": Invoice.Origin.APP,
            "period_start": draft.start,
            "period_end": draft.end,
            "total_net": draft.total,
        },
    )
    TimeEntry.objects.filter(pk__in=[e.pk for e in draft.entries], invoice__isnull=True).update(invoice=invoice)
    return invoice


async def create_invoice(client: LexwareClient, customer: Customer, start: date, end: date) -> Invoice:
    """Create an invoice draft in Lexware and mark the billed time entries.

    The draft is recalculated here, so entries added since the preview are included.
    """
    draft = await sync_to_async(build_draft)(customer, start, end)
    if not customer.lexware_id:
        raise LexwareError("Der Kunde ist nicht mit Lexware verknüpft. Importiere ihn zuerst aus Lexware.")
    if not draft.can_be_invoiced:
        raise LexwareError(" ".join(draft.problems) or "Für diesen Zeitraum gibt es nichts abzurechnen.")
    profile = await client.get_profile()
    detail = (await AppSettings.aload()).invoice_detail
    lexware_id = await client.create_invoice(invoice_payload(draft, timezone.localdate(), profile, detail))
    return await sync_to_async(_record_invoice)(draft, lexware_id)
