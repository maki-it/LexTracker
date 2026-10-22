"""Build the Lexware Office invoice payload from a calculated draft."""

from datetime import date, datetime, time

from django.utils import timezone

from billing.calculation import Draft


def _lexware_date(day: date) -> str:
    # Lexware expects full ISO timestamps with offset, e.g. 2026-10-31T00:00:00.000+01:00.
    return datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone()).isoformat(timespec="milliseconds")


def invoice_payload(draft: Draft, voucher_date: date) -> dict:
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
                    "taxRatePercentage": float(draft.tax_rate),
                },
            }
            for line in draft.lines
        ],
        "totalPrice": {"currency": "EUR"},
        "taxConditions": {"taxType": "net"},
        "shippingConditions": {
            "shippingType": "serviceperiod",
            "shippingDate": _lexware_date(draft.start),
            "shippingEndDate": _lexware_date(draft.end),
        },
        "title": "Rechnung",
        "introduction": f"Für den Leistungszeitraum {draft.start:%d.%m.%Y} bis {draft.end:%d.%m.%Y} "
        "stellen wir Ihnen folgende Leistungen in Rechnung.",
    }
