"""Write changes to a customer back to its contact in Lexware Office."""

from django.utils import timezone

from customers.models import Customer
from lexware.client import LexwareClient
from lexware.schemas import Contact

# Fields that live in Lexware. Changing one of them here changes the Lexware contact.
LEXWARE_FIELDS = ("name", "email", "phone")

# Same order in which the import picks the address or number to show.
EMAIL_GROUPS = ("business", "office", "other", "private")
PHONE_GROUPS = ("business", "office", "mobile", "other", "private")


def _replace(groups: dict, groups_order: tuple[str, ...], old: str, new: str) -> None:
    """Swap ``old`` for ``new`` in Lexware's grouped lists, or add ``new`` as the business entry."""
    for key in groups_order:
        items = groups.get(key) or []
        if old and old in items:
            index = items.index(old)
            if new:
                items[index] = new
            else:
                items.pop(index)
            return
    if new:
        groups.setdefault("business", []).insert(0, new)


def apply_to_contact(contact: dict, customer: Customer) -> dict:
    """Change the raw Lexware ``contact`` so it shows the customer's name, e-mail and phone."""
    current = Contact.model_validate(contact)
    if customer.name != current.name:
        if contact.get("company"):
            contact["company"]["name"] = customer.name
        else:
            first, _, last = customer.name.rpartition(" ")
            contact.setdefault("person", {}).update(firstName=first, lastName=last)
    if customer.email != current.email:
        _replace(contact.setdefault("emailAddresses", {}), EMAIL_GROUPS, current.email, customer.email)
    if customer.phone != current.phone:
        _replace(contact.setdefault("phoneNumbers", {}), PHONE_GROUPS, current.phone, customer.phone)
    return contact


# The parts of a Lexware address the customer portal shows and changes.
ADDRESS_FIELDS = ("supplement", "street", "zip", "city", "countryCode")


def billing_address(contact: dict) -> dict:
    """The contact's first billing address with every field of ``ADDRESS_FIELDS``, empty if it has none."""
    addresses = (contact.get("addresses") or {}).get("billing") or [{}]
    return {key: addresses[0].get(key) or "" for key in ADDRESS_FIELDS}


def apply_billing_address(contact: dict, address: dict) -> dict:
    """Write ``address`` into the contact's first billing address, keeping fields LexTracker does not know.

    A contact without a billing address gets one. Empty values are left out, as Lexware does.
    """
    billing = contact.setdefault("addresses", {}).setdefault("billing", [])
    if not billing:
        billing.append({})
    entry = billing[0]
    for key in ADDRESS_FIELDS:
        if address.get(key):
            entry[key] = address[key]
        else:
            entry.pop(key, None)
    return contact


async def push_to_lexware(client: LexwareClient, customer: Customer) -> None:
    """Send the customer's Lexware fields to Lexware and remember the contact's new version.

    The contact is read fresh first, so changes made in Lexware to other fields are kept.
    """
    contact = await client.get_contact(customer.lexware_id)
    customer.lexware_version = await client.update_contact(customer.lexware_id, apply_to_contact(contact, customer))
    customer.lexware_synced_at = timezone.now()
