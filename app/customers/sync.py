"""Import and update customers from Lexware Office."""

from dataclasses import dataclass

from django.utils import timezone

from core.models import AppSettings
from customers.models import Customer
from lexware.client import LexwareClient, LexwareError, client_from_settings

# Fields that Lexware owns. Everything else (rates, notes) is only edited here.
SYNCED_FIELDS = [
    "name",
    "customer_number",
    "email",
    "phone",
    "is_archived",
    "lexware_deleted",
    "lexware_version",
    "lexware_synced_at",
]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    removed: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged

    @property
    def has_changes(self) -> bool:
        return bool(self.created or self.updated or self.removed)

    @property
    def summary(self) -> str:
        summary = f"{self.created} neu, {self.updated} aktualisiert, {self.unchanged} unverändert"
        if self.removed:
            summary += f", {self.removed} in Lexware nicht mehr vorhanden (archiviert)"
        return summary + "."


async def sync_customers(client: LexwareClient) -> SyncResult:
    """Create customers that are new in Lexware and update those whose version changed."""
    existing = {c.lexware_id: c async for c in Customer.objects.filter(lexware_id__isnull=False)}
    now = timezone.now()
    to_create: list[Customer] = []
    to_update: list[Customer] = []
    result = SyncResult()

    seen = []
    async for contact in client.iter_customers():
        seen.append(contact.id)
        values = {
            "name": contact.name or "(ohne Namen)",
            "customer_number": contact.customer_number,
            "email": contact.email,
            "phone": contact.phone,
            "is_archived": contact.archived,
            "lexware_deleted": False,
            "lexware_version": contact.version,
            "lexware_synced_at": now,
        }
        customer = existing.get(contact.id)
        if customer is None:
            to_create.append(Customer(lexware_id=contact.id, **values))
        elif customer.lexware_version != contact.version or customer.lexware_deleted:
            for field, value in values.items():
                setattr(customer, field, value)
            customer.updated_at = now  # bulk_update skips auto_now
            to_update.append(customer)
        else:
            result.unchanged += 1

    if result.unchanged:
        await Customer.objects.filter(lexware_id__in=seen).aupdate(lexware_synced_at=now)
    if to_create:
        # Upsert, so two imports running at the same time cannot create duplicates.
        await Customer.objects.abulk_create(
            to_create, update_conflicts=True, unique_fields=["lexware_id"], update_fields=SYNCED_FIELDS
        )
    if to_update:
        await Customer.objects.abulk_update(to_update, [*SYNCED_FIELDS, "updated_at"])
    # The import has seen every customer contact, so the rest are gone from Lexware.
    result.removed = await (
        Customer.objects.filter(lexware_id__isnull=False, lexware_deleted=False)
        .exclude(lexware_id__in=seen)
        .aupdate(lexware_deleted=True, is_archived=True, updated_at=now)
    )
    result.created, result.updated = len(to_create), len(to_update)
    return result


async def _record(status: str, *, failed: bool) -> None:
    # Update only these columns, so a settings change saved at the same time is kept.
    await AppSettings.aload()
    await AppSettings.objects.filter(pk=1).aupdate(
        lexware_synced_at=timezone.now(), lexware_sync_status=status[:500], lexware_sync_failed=failed
    )


async def sync_and_record() -> SyncResult:
    """Run the import with the configured API key and remember its outcome."""
    try:
        async with client_from_settings() as client:
            result = await sync_customers(client)
    except LexwareError as exc:
        await _record(str(exc), failed=True)
        raise
    await _record(result.summary, failed=False)
    return result
