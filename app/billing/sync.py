"""Keep the status of invoices in line with Lexware Office."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.utils.translation import gettext as _

from billing.models import Invoice
from core.ids import parse_uuid
from core.models import AppSettings
from customers.models import Customer
from lexware.client import LexwareClient, LexwareError, LexwareNotFound, client_from_settings
from lexware.schemas import Voucher
from tracking.models import TimeEntry

# Statuses that can still change in Lexware. Paid, voided and deleted invoices are final.
OPEN_STATUSES = [
    Invoice.Status.DRAFT,
    Invoice.Status.OPEN,
    Invoice.Status.OVERDUE,
    Invoice.Status.TRANSFERRED,
    Invoice.Status.SEPADEBIT,
]
# Statuses of invoices that have payments to ask for.
PAYABLE_STATUSES = [
    Invoice.Status.OPEN,
    Invoice.Status.TRANSFERRED,
    Invoice.Status.SEPADEBIT,
    Invoice.Status.PAID,
    "paidoff",
]
SYNCED_FIELDS = [
    "status",
    "voucher_number",
    "voucher_date",
    "due_date",
    "open_amount",
    "status_synced_at",
    "updated_at",
]


@dataclass
class InvoiceSyncResult:
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0
    imported: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.changed or self.imported or self.deleted)

    @property
    def summary(self) -> str:
        parts = [
            _("%(count)d geändert") % {"count": self.changed},
            _("%(count)d unverändert") % {"count": self.unchanged},
        ]
        if self.imported:
            parts.append(_("%(count)d aus Lexware übernommen") % {"count": self.imported})
        if self.deleted:
            parts.append(_("%(count)d in Lexware gelöscht (Zeiten wieder freigegeben)") % {"count": self.deleted})
        return ", ".join(parts) + "."


def _status(lexware_status: str, due_date, today) -> str:
    if lexware_status == "paidoff":
        return Invoice.Status.PAID
    if lexware_status == Invoice.Status.OPEN and due_date and due_date < today:
        return Invoice.Status.OVERDUE
    return lexware_status


def _apply(invoice: Invoice, status: str, voucher_number: str | None, voucher_date, due_date, open_amount, now) -> bool:
    """Set the values from Lexware and tell whether anything changed."""
    values = {
        "status": status,
        "voucher_number": voucher_number or "",
        "voucher_date": voucher_date or invoice.voucher_date,
        "due_date": due_date,
        "open_amount": open_amount,
    }
    changed = any(getattr(invoice, field) != value for field, value in values.items())
    for field, value in values.items():
        setattr(invoice, field, value)
    invoice.status_synced_at = now
    if changed:
        invoice.updated_at = now  # bulk_update skips auto_now
    return changed


@transaction.atomic
def mark_deleted(invoice: Invoice, now) -> None:
    """The draft is gone from Lexware: keep it for the record and let its time be billed again."""
    TimeEntry.objects.filter(invoice=invoice).update(invoice=None)
    invoice.status = Invoice.Status.DELETED
    invoice.status_synced_at = invoice.updated_at = now
    invoice.save(update_fields=["status", "status_synced_at", "updated_at"])


async def sync_invoices(client: LexwareClient) -> InvoiceSyncResult:
    """Update every invoice whose status can still change, detect drafts deleted in Lexware, and take over
    invoices written directly in Lexware for imported customers."""
    known = {i.lexware_id: i async for i in Invoice.objects.filter(lexware_id__isnull=False)}
    pending = {lexware_id: i for lexware_id, i in known.items() if i.status in OPEN_STATUSES}
    customers = {c.lexware_id: c.pk async for c in Customer.objects.filter(lexware_id__isnull=False)}
    result = InvoiceSyncResult()
    now = timezone.now()
    today = timezone.localdate()

    to_update: list[Invoice] = []
    new: list[Voucher] = []

    def record(
        invoice: Invoice, lexware_status: str, voucher_number: str | None, voucher_date, due_date, open_amount
    ) -> None:
        status = _status(lexware_status, due_date, today)
        if _apply(invoice, status, voucher_number, voucher_date, due_date, open_amount, now):
            result.changed += 1
        else:
            result.unchanged += 1
        to_update.append(invoice)

    # The whole list every time, so invoices written in Lexware show up whenever they were created.
    async for voucher in client.iter_invoices():
        if invoice := pending.pop(voucher.id, None):
            record(
                invoice,
                voucher.voucher_status,
                voucher.voucher_number,
                _day(voucher.voucher_date),
                _due_date(voucher),
                _amount(voucher.open_amount),
            )
        elif voucher.id not in known and voucher.contact_id in customers:
            new.append(voucher)

    # Not in the list: look each one up, so an archived invoice is not mistaken for a deleted one.
    for invoice in pending.values():
        try:
            data = await client.get_invoice(invoice.lexware_id)
        except LexwareNotFound:
            await _forget(invoice, now)
            result.deleted += 1
            continue
        status, number = data.get("voucherStatus", invoice.status), data.get("voucherNumber")
        record(invoice, status, number, _local_date(data.get("voucherDate")), invoice.due_date, invoice.open_amount)

    if to_update:
        await Invoice.objects.abulk_update(to_update, SYNCED_FIELDS)

    for voucher in new:
        # The list has no net amount and no service period, so these come from the invoice itself.
        try:
            data = await client.get_invoice(voucher.id)
        except LexwareNotFound:
            continue
        await _create_from_lexware(
            voucher.id,
            data,
            customer_id=customers[voucher.contact_id],
            voucher_date=_local_date(data.get("voucherDate")) or _day(voucher.voucher_date),
            status=_status(voucher.voucher_status, _due_date(voucher), today),
            voucher_number=voucher.voucher_number,
            due_date=_due_date(voucher),
            open_amount=_amount(voucher.open_amount),
            now=now,
        )
        result.imported += 1
    return result


async def _forget(invoice: Invoice, now) -> None:
    """The invoice is gone from Lexware."""
    if invoice.origin == Invoice.Origin.LEXWARE and not await invoice.time_entries.aexists():
        await invoice.adelete()  # Never ours, no time assigned to it and gone: nothing to keep.
    else:
        await sync_to_async(mark_deleted)(invoice, now)


async def sync_invoice(client: LexwareClient, invoice_id: UUID) -> InvoiceSyncResult:
    """Look at just this invoice in Lexware, as the sync of everything would do.

    For a call from Lexware that names the invoice. Ids that are no invoice of ours (Lexware also reports payments
    of credit notes and other vouchers) are ignored. It reads the invoice and its payments instead of the whole
    voucher list, so the sync of everything stays the safety net.
    """
    result = InvoiceSyncResult()
    now = timezone.now()
    invoice = await Invoice.objects.filter(lexware_id=invoice_id).afirst()
    if invoice and invoice.status not in OPEN_STATUSES:
        return result
    try:
        data = await client.get_invoice(invoice_id)
    except LexwareNotFound:
        if invoice:
            await _forget(invoice, now)
            result.deleted += 1
        return result

    contact_id = parse_uuid((data.get("address") or {}).get("contactId"))
    customer_id = None
    if invoice is None:
        if contact_id:
            customer_id = await Customer.objects.filter(lexware_id=contact_id).values_list("pk", flat=True).afirst()
        if customer_id is None:
            return result  # Not for a customer we know.

    today = timezone.localdate()
    due_date = _local_date(data.get("dueDate"))
    lexware_status = data.get("voucherStatus", invoice.status if invoice else Invoice.Status.DRAFT)
    status = _status(lexware_status, due_date, today)
    open_amount = await _open_amount(client, invoice_id, lexware_status, invoice.open_amount if invoice else None)
    voucher_date = _local_date(data.get("voucherDate"))
    if invoice:
        if _apply(invoice, status, data.get("voucherNumber"), voucher_date, due_date, open_amount, now):
            result.changed += 1
        else:
            result.unchanged += 1
        await Invoice.objects.abulk_update([invoice], SYNCED_FIELDS)
    else:
        await _create_from_lexware(
            invoice_id,
            data,
            customer_id=customer_id,
            voucher_date=voucher_date,
            status=status,
            voucher_number=data.get("voucherNumber"),
            due_date=due_date,
            open_amount=open_amount,
            now=now,
        )
        result.imported += 1
    return result


async def _open_amount(client: LexwareClient, invoice_id: UUID, lexware_status: str, current: Decimal | None):
    """What is still to be paid, from the payments of the invoice. The invoice itself does not say."""
    if lexware_status not in PAYABLE_STATUSES:
        return current  # Drafts and voided invoices have no payments.
    try:
        payment = await client.get_payment(invoice_id)
    except LexwareNotFound:
        return current
    return _amount(payment.get("openAmount"))


async def _create_from_lexware(
    lexware_id: UUID,
    data: dict,
    *,
    customer_id: UUID,
    voucher_date: date | None,
    status: str,
    voucher_number: str | None,
    due_date: date | None,
    open_amount: Decimal | None,
    now,
) -> Invoice:
    shipping = data.get("shippingConditions") or {}
    start = _local_date(shipping.get("shippingDate")) or voucher_date or timezone.localdate()
    end = _local_date(shipping.get("shippingEndDate")) or start
    return await Invoice.objects.acreate(
        customer_id=customer_id,
        origin=Invoice.Origin.LEXWARE,
        quotation_number=_quotation_number(data),
        lexware_id=lexware_id,
        voucher_date=voucher_date,
        period_start=start,
        period_end=end,
        total_net=Decimal(str((data.get("totalPrice") or {}).get("totalNetAmount") or 0)),
        status=status,
        voucher_number=voucher_number or "",
        due_date=due_date,
        open_amount=open_amount,
        status_synced_at=now,
    )


def _quotation_number(data: dict) -> str:
    """The number of the quotation the invoice follows up on, from its related vouchers."""
    related = data.get("relatedVouchers") or []
    return next((v.get("voucherNumber") or "" for v in related if v.get("voucherType") == "quotation"), "")


def _amount(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal("0.01"))


def _local_date(value: str | None) -> date | None:
    return _day(parse_datetime(value)) if value else None


def _due_date(voucher: Voucher):
    return _day(voucher.due_date)


def _day(value: datetime | None) -> date | None:
    """The local calendar day of a Lexware timestamp; those without a time zone are taken as they are."""
    if value is None:
        return None
    return timezone.localdate(value) if timezone.is_aware(value) else value.date()


async def _record(status: str, *, failed: bool) -> None:
    # Update only these columns, so a settings change saved at the same time is kept.
    await AppSettings.aload()
    await AppSettings.objects.filter(pk=1).aupdate(
        invoices_synced_at=timezone.now(), invoices_sync_status=status[:500], invoices_sync_failed=failed
    )


async def sync_and_record() -> InvoiceSyncResult:
    """Run the status sync with the configured API key and remember its outcome."""
    try:
        async with client_from_settings() as client:
            result = await sync_invoices(client)
    except LexwareError as exc:
        await _record(str(exc), failed=True)
        raise
    await _record(result.summary, failed=False)
    return result
