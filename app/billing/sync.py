"""Keep the status of invoices in line with Lexware Office."""

from dataclasses import dataclass
from datetime import timedelta

from asgiref.sync import sync_to_async
from django.db import transaction
from django.utils import timezone

from billing.models import Invoice
from core.models import AppSettings
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
SYNCED_FIELDS = ["status", "voucher_number", "due_date", "status_synced_at", "updated_at"]


@dataclass
class InvoiceSyncResult:
    changed: int = 0
    unchanged: int = 0
    deleted: int = 0

    @property
    def summary(self) -> str:
        summary = f"{self.changed} geändert, {self.unchanged} unverändert"
        if self.deleted:
            summary += f", {self.deleted} in Lexware gelöscht (Zeiten wieder freigegeben)"
        return summary + "."


def _status(lexware_status: str, due_date, today) -> str:
    if lexware_status == "paidoff":
        return Invoice.Status.PAID
    if lexware_status == Invoice.Status.OPEN and due_date and due_date < today:
        return Invoice.Status.OVERDUE
    return lexware_status


def _apply(invoice: Invoice, status: str, voucher_number: str | None, due_date, now) -> bool:
    """Set the values from Lexware and tell whether anything changed."""
    values = {"status": status, "voucher_number": voucher_number or "", "due_date": due_date}
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
    """Update every invoice whose status can still change, and detect drafts deleted in Lexware."""
    pending = {
        i.lexware_id: i async for i in Invoice.objects.filter(lexware_id__isnull=False, status__in=OPEN_STATUSES)
    }
    result = InvoiceSyncResult()
    if not pending:
        return result
    now = timezone.now()
    today = timezone.localdate()
    # Only list invoices created since the oldest one we follow (a day earlier, for time zones).
    created_from = min(timezone.localdate(i.created_at) for i in pending.values()) - timedelta(days=1)

    to_update: list[Invoice] = []

    def record(invoice: Invoice, lexware_status: str, voucher_number: str | None, due_date) -> None:
        if _apply(invoice, _status(lexware_status, due_date, today), voucher_number, due_date, now):
            result.changed += 1
        else:
            result.unchanged += 1
        to_update.append(invoice)

    async for voucher in client.iter_invoices(created_from=created_from):
        invoice = pending.pop(voucher.id, None)
        if invoice:
            record(invoice, voucher.voucher_status, voucher.voucher_number, _due_date(voucher))

    # Not in the list: look each one up, so an archived invoice is not mistaken for a deleted one.
    for invoice in pending.values():
        try:
            data = await client.get_invoice(invoice.lexware_id)
        except LexwareNotFound:
            await sync_to_async(mark_deleted)(invoice, now)
            result.deleted += 1
            continue
        record(invoice, data.get("voucherStatus", invoice.status), data.get("voucherNumber"), invoice.due_date)

    if to_update:
        await Invoice.objects.abulk_update(to_update, SYNCED_FIELDS)
    return result


def _due_date(voucher: Voucher):
    due = voucher.due_date
    if due is None:
        return None
    return timezone.localdate(due) if timezone.is_aware(due) else due.date()


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
