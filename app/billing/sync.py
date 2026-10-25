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
            if invoice.origin == Invoice.Origin.LEXWARE:
                await invoice.adelete()  # Never ours and gone: nothing to keep.
            else:
                await sync_to_async(mark_deleted)(invoice, now)
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
        await _create_from_lexware(voucher, data, customers[voucher.contact_id], now, today)
        result.imported += 1
    return result


async def _create_from_lexware(voucher: Voucher, data: dict, customer_id: UUID, now, today) -> Invoice:
    voucher_date = _local_date(data.get("voucherDate")) or _day(voucher.voucher_date)
    shipping = data.get("shippingConditions") or {}
    start = _local_date(shipping.get("shippingDate")) or voucher_date or today
    end = _local_date(shipping.get("shippingEndDate")) or start
    due_date = _due_date(voucher)
    return await Invoice.objects.acreate(
        customer_id=customer_id,
        origin=Invoice.Origin.LEXWARE,
        lexware_id=voucher.id,
        voucher_date=voucher_date,
        period_start=start,
        period_end=end,
        total_net=Decimal(str((data.get("totalPrice") or {}).get("totalNetAmount") or 0)),
        status=_status(voucher.voucher_status, due_date, today),
        voucher_number=voucher.voucher_number or "",
        due_date=due_date,
        open_amount=_amount(voucher.open_amount),
        status_synced_at=now,
    )


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
