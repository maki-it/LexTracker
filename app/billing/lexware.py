"""Build the Lexware Office invoice payload from a calculated draft."""

import re
from datetime import date, datetime, time

from django.utils import timezone

from billing.calculation import Draft, Line, _german_number, to_hours
from core.models import AppSettings
from lexware.schemas import Profile

# German standard VAT rate, used for the services LexTracker bills.
STANDARD_TAX_RATE = 19.0

# Lexware cuts or rejects longer texts on a line. Its documentation names no limits for invoices,
# so these are cautious values from the API's schema.
NAME_MAX = 255
DESCRIPTION_MAX = 2000

# Lexware formats **bold** and __italic__ in descriptions. Time entries are plain text.
_FORMATTING = re.compile(r"\*\*|__")


def _lexware_date(day: date) -> str:
    # Lexware expects full ISO timestamps with offset, e.g. 2026-10-31T00:00:00.000+01:00.
    return datetime.combine(day, time.min, tzinfo=timezone.get_current_timezone()).isoformat(timespec="milliseconds")


def tax_conditions(profile: Profile) -> tuple[str, float]:
    """Tax type and rate for the invoice, from the organization's settings in Lexware."""
    if profile.small_business or profile.tax_type == "vatfree":
        return "vatfree", 0.0
    return "net", STANDARD_TAX_RATE


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _activity(line: Line, entry) -> str:
    """One bullet of the activity list: the day, the time, and what was done."""
    parts = [f"{timezone.localtime(entry.started_at):%d.%m.%Y}", f"{_german_number(to_hours(entry.duration))} Std."]
    if line.fixed:  # A retainer line has time of several projects and tasks.
        parts.append(f"{entry.task.name} ({entry.task.project.name})")
    text = ", ".join(parts)
    note = _FORMATTING.sub("", " ".join(entry.description.split()))
    return f"- {text}: {note}" if note else f"- {text}"


def line_description(line: Line, detail: str) -> str:
    """The text below a line's name: its details, and for ``ENTRIES`` the activities behind it."""
    text = line.description
    if detail != AppSettings.InvoiceDetail.ENTRIES or not line.entries:
        return _clip(text, DESCRIPTION_MAX)
    rows = [_activity(line, entry) for entry in sorted(line.entries, key=lambda e: e.started_at)]
    shown = []
    # Leave room for the "and n more" row, so a long list is cut between two activities.
    budget = DESCRIPTION_MAX - len(text) - 2 - 60
    for row in rows:
        if len(row) + 1 > budget:
            break
        shown.append(row)
        budget -= len(row) + 1
    if len(shown) < len(rows):
        shown.append(f"- … und {len(rows) - len(shown)} weitere")
    return _clip("\n".join([text, "", *shown]), DESCRIPTION_MAX)


def invoice_payload(
    draft: Draft,
    voucher_date: date,
    profile: Profile,
    detail: str = AppSettings.InvoiceDetail.SUMMARY,
) -> dict:
    tax_type, tax_rate = tax_conditions(profile)
    return {
        "voucherDate": _lexware_date(voucher_date),
        "address": {"contactId": str(draft.customer.lexware_id)},
        "lineItems": [
            {
                "type": "custom",
                "name": _clip(line.name, NAME_MAX),
                **({"description": description} if (description := line_description(line, detail)) else {}),
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
