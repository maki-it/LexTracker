"""Open pages in the dialog of base.html instead of navigating to them."""

from urllib.parse import urlencode

from django import template
from django.urls import reverse
from django.utils.html import format_html

register = template.Library()


@register.simple_tag
def dialog_link(viewname: str, *args, **params) -> str:
    """The attributes of a link that opens the page in the dialog.

    ``<a {% dialog_link "projects:edit" project.pk %}>`` keeps a normal ``href``, so the
    link still works as a page of its own (new tab, no JavaScript). Keyword arguments
    become the query string.
    """
    url = reverse(viewname, args=args)
    if params:
        url = f"{url}?{urlencode(params)}"
    return format_html(
        'href="{0}" hx-get="{0}" hx-target="#dialog-body" hx-swap="innerHTML" hx-select="unset" hx-push-url="false"',
        url,
    )
