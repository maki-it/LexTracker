"""Build the Lexware Office invoice payload from a calculated draft."""

from datetime import date, datetime, time

from django.utils import timezone

from billing.calculation import Draft
from lexware.schemas import Profile

# German standard VAT rate, used for the services LexTracker bills.
STANDARD_TAX_RATE = 19.0


def _lexware_date(day: date) -> str:
    # Lexware expects full ISO timestamps with offset, e.g. 2026-10-31T00:00:00.000+01:00.
    return datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone()).isoformat(timespec="milliseconds")


def tax_conditions(profile: Profile) -> tuple[str, float]:
    """Tax type and rate for the invoice, from the organization's settings in Lexware."""
    if profile.small_business or profile.tax_type == "vatfree":
        return "vatfree", 0.0
    return "net", STANDARD_TAX_RATE


def invoice_payload(draft: Draft, voucher_date: date, profile: Profile) -> dict:
    tax_type, tax_rate = tax_conditions(profile)
    return {
        "voucherDate": _lexware_date(voucher_date),
        "address": {"contactId": str(draft.customer.lexware_id)},
        "lineItems": [
            {
                "type": "custom",
                "name": line.name,
                **({"description": line.description} if line.description else {}),
                "quantity": float(line.quantity),
                "unitName": line.unit,
                "unitPrice": {
                    "currency": "EUR",
                    "netAmount": float(line.unit_price),
                    "taxRatePercentage": tax_rate,
                },
            }
            for line in draft.lines
        ],
        "totalPrice": {"currency": "EUR"},
        "taxConditions": {"taxType": tax_type},
        "shippingConditions": {
            "shippingType": "serviceperiod",
            "shippingDate": _lexware_date(draft.start),
            "shippingEndDate": _lexware_date(draft.end),
        },
        "title": "Rechnung",
        "introduction": f"Für den Leistungszeitraum {draft.start:%d.%m.%Y} bis {draft.end:%d.%m.%Y} "
        "stellen wir Ihnen folgende Leistungen in Rechnung.",
    }
