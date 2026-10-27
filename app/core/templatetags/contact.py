"""Links for contacting a customer."""

import re
from urllib.parse import quote, urlencode

from django import template

register = template.Library()


@register.filter
def tel(number: str) -> str:
    """A phone number for a ``tel:`` link: digits and a leading plus, without spaces, slashes or brackets."""
    return re.sub(r"(?!^\+)\D", "", number.replace("(0)", "").strip())


@register.filter
def route_url(query: str) -> str:
    """A link that opens the route to the address in the maps app of the phone, or in the browser."""
    return "https://www.google.com/maps/dir/?" + urlencode({"api": 1, "destination": query}, quote_via=quote)
