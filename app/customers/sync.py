"""Import and update customers from Lexware Office."""

from dataclasses import dataclass

from django.utils import timezone

from customers.models import Customer
from lexware.client import LexwareClient

# Fields that Lexware owns. Everything else (rates, notes) is only edited here.
SYNCED_FIELDS = ["name", "customer_number", "email", "phone", "is_archived", "lexware_version", "lexware_synced_at"]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    unchanged: int = 0

    @property
    def total(self) -> int:
        return self.created + self.updated + self.unchanged


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
            "lexware_version": contact.version,
            "lexware_synced_at": now,
        }
        customer = existing.get(contact.id)
        if customer is None:
            to_create.append(Customer(lexware_id=contact.id, **values))
        elif customer.lexware_version != contact.version:
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
    result.created, result.updated = len(to_create), len(to_update)
    return result
