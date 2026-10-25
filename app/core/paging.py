"""Lists that load the next rows while scrolling.

The view loads one page; the last row of the table (``core/_more_rows.html``) asks for the next one as
soon as it scrolls into view and is replaced by it. Such a request (htmx, ``?page=2`` …) gets only the
rows, rendered by the list's rows template.
"""

from dataclasses import dataclass

from django.db.models import QuerySet
from django.http import HttpRequest

from accounts.models import User


@dataclass
class Page:
    items: list
    number: int
    # Query string of the next page, empty on the last one.
    next_query: str

    @property
    def is_first(self) -> bool:
        return self.number == 1


def page_number(request: HttpRequest) -> int:
    try:
        return max(1, int(request.GET.get("page", 1)))
    except ValueError:
        return 1


def wants_rows(request: HttpRequest) -> bool:
    """A request for the next rows, not for the whole page."""
    return bool(request.htmx) and page_number(request) > 1


async def apage(request: HttpRequest, queryset: QuerySet) -> Page:
    size = getattr(request.user, "list_page_size", User.PageSize.MEDIUM)
    number = page_number(request)
    offset = (number - 1) * size
    # One more than fits on the page tells whether there is a next page.
    items = [item async for item in queryset[offset : offset + size + 1]]
    next_query = ""
    if len(items) > size:
        params = request.GET.copy()
        params["page"] = number + 1
        next_query = params.urlencode()
    return Page(items[:size], number, next_query)
