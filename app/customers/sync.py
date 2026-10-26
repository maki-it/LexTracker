"""Import and update customers from Lexware Office."""

from dataclasses import dataclass
from uuid import UUID

from django.utils import timezone
from django.utils.translation import gettext as _

from core.models import AppSettings
from customers.lexware import merged_note
from customers.models import Customer
from lexware.client import LexwareClient, LexwareError, LexwareNotFound, client_from_settings
from lexware.schemas import Contact

# Fields that Lexware owns. Everything else (rates, categories) is only edited here. The notes are kept in both
# places (see ``customers.lexware.merged_note``).
SYNCED_FIELDS = [
    "name",
    "customer_number",
    "email",
    "phone",
    "is_archived",
    "lexware_deleted",
    "lexware_version",
    "lexware_note",
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
        parts = [
            _("%(count)d neu") % {"count": self.created},
            _("%(count)d aktualisiert") % {"count": self.updated},
            _("%(count)d unverändert") % {"count": self.unchanged},
        ]
        if self.removed:
            parts.append(_("%(count)d in Lexware nicht mehr vorhanden (archiviert)") % {"count": self.removed})
        return ", ".join(parts) + "."


def _values(contact: Contact, now) -> dict:
    return {
        "name": contact.name or "(ohne Namen)",
        "customer_number": contact.customer_number,
        "email": contact.email,
        "phone": contact.phone,
        "is_archived": contact.archived,
        "lexware_deleted": False,
        "lexware_version": contact.version,
        "lexware_note": contact.note,
        "lexware_synced_at": now,
    }


async def _apply(contacts: list[Contact], existing: dict[UUID, Customer], now) -> SyncResult:
    """Create the customers that are new and update those whose version changed. ``existing``: by Lexware ID."""
    to_create: list[Customer] = []
    to_update: list[Customer] = []
    to_backfill: list[Customer] = []
    result = SyncResult()

    for contact in contacts:
        values = _values(contact, now)
        customer = existing.get(contact.id)
        if customer is None:
            to_create.append(Customer(lexware_id=contact.id, notes=contact.note, **values))
        elif customer.lexware_version != contact.version or customer.lexware_deleted:
            customer.notes = merged_note(customer, contact.note)
            for field, value in values.items():
                setattr(customer, field, value)
            customer.updated_at = now  # bulk_update skips auto_now
            to_update.append(customer)
        else:
            result.unchanged += 1
            if customer.lexware_note is None:
                # From before notes were synced: the contact is the same, but its note is not known here yet.
                customer.notes = merged_note(customer, contact.note)
                customer.lexware_note = contact.note
                to_backfill.append(customer)

    if result.unchanged:
        await Customer.objects.filter(lexware_id__in=[c.id for c in contacts]).aupdate(lexware_synced_at=now)
    if to_create:
        # Upsert, so two imports running at the same time cannot create duplicates.
        await Customer.objects.abulk_create(
            to_create, update_conflicts=True, unique_fields=["lexware_id"], update_fields=SYNCED_FIELDS
        )
    if to_update:
        await Customer.objects.abulk_update(to_update, [*SYNCED_FIELDS, "notes", "updated_at"])
    if to_backfill:
        await Customer.objects.abulk_update(to_backfill, ["notes", "lexware_note"])
    result.created, result.updated = len(to_create), len(to_update)
    return result


async def sync_customers(client: LexwareClient) -> SyncResult:
    """Create customers that are new in Lexware and update those whose version changed."""
    existing = {c.lexware_id: c async for c in Customer.objects.filter(lexware_id__isnull=False)}
    now = timezone.now()
    contacts = [contact async for contact in client.iter_customers()]
    result = await _apply(contacts, existing, now)
    # The import has seen every customer contact, so the rest are gone from Lexware.
    result.removed = await (
        Customer.objects.filter(lexware_id__isnull=False, lexware_deleted=False)
        .exclude(lexware_id__in=[c.id for c in contacts])
        .aupdate(lexware_deleted=True, is_archived=True, updated_at=now)
    )
    return result


async def sync_contact(client: LexwareClient, contact_id: UUID) -> SyncResult:
    """Bring the one customer with this Lexware ID up to date, as the import would.

    A contact that is gone from Lexware or has no customer role any more archives its customer, like the import.
    Contacts that are not customers and unknown here are ignored.
    """
    now = timezone.now()
    try:
        contact = Contact.model_validate(await client.get_contact(contact_id))
    except LexwareNotFound:
        contact = None
    if contact is None or not contact.customer_number:
        removed = await Customer.objects.filter(lexware_id=contact_id, lexware_deleted=False).aupdate(
            lexware_deleted=True, is_archived=True, updated_at=now
        )
        return SyncResult(removed=removed)
    existing = {c.lexware_id: c async for c in Customer.objects.filter(lexware_id=contact_id)}
    return await _apply([contact], existing, now)


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
