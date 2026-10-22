from datetime import timedelta

from django import template

register = template.Library()


@register.filter
def hours(value: timedelta | None) -> str:
    """Format a duration as hours and minutes, e.g. ``1:05``."""
    if not value:
        return "0:00"
    minutes = int(value.total_seconds() // 60)
    return f"{minutes // 60}:{minutes % 60:02d}"
