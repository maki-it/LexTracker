from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django import template
from django.utils.formats import number_format

register = template.Library()


@register.filter
def hours(value: timedelta | None, style: str = "clock") -> str:
    """Format a duration as ``2:45`` (style ``clock``) or as decimal hours ``2,75`` (style ``decimal``).

    The decimal separator is the one of the active language (``2.75`` in English).

    Templates pass the user's choice: ``{{ entry.duration|hours:duration_format }}``.
    """
    seconds = value.total_seconds() if value else 0
    if style == "decimal":
        decimal_hours = (Decimal(seconds) / 3600).quantize(Decimal("0.01"), ROUND_HALF_UP)
        return number_format(decimal_hours, decimal_pos=2)
    minutes = int(seconds // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"
