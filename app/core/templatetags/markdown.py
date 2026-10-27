"""Render the Markdown that users write in descriptions and notes."""

from django import template
from django.urls import reverse

from core import markdown as md
from core.markdown_targets import TARGETS

register = template.Library()


@register.filter
def markdown(value: str | None) -> str:
    """``{{ text|markdown }}``: the text as HTML, wrapped in ``<div class="markdown">``. Checklists are read-only."""
    return md.render(value)


@register.simple_tag
def markdown_field(obj, field: str) -> str:
    """``{% markdown_field project "description" %}``: like the filter, but its checklists can be ticked on the page.

    Ticking saves the text of ``field``, see ``core.views.markdown_toggle``.
    """
    target = next(name for name, t in TARGETS.items() if isinstance(obj, t.model) and t.field == field)
    return md.render(getattr(obj, field), reverse("core:markdown_toggle", args=[target, obj.pk]))
