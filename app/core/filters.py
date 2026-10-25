"""Status filters of a list that can be combined.

The selection lives in the URL as a repeated parameter (``?status=open&status=overdue``) and every filter
pill is a plain link that adds or removes its own key, so it works without JavaScript. The selected filters are
combined with OR.
"""

from dataclasses import dataclass

from django.http import HttpRequest


@dataclass
class FilterPill:
    key: str
    label: str
    count: int
    active: bool
    # Query string of the list with this filter toggled.
    query: str


def selected_filters(request: HttpRequest, keys, param: str = "status") -> list[str]:
    """The known keys from the URL, in the order of the filter definition."""
    wanted = set(request.GET.getlist(param))
    return [key for key in keys if key in wanted]


def query_with(request: HttpRequest, values: list[str], param: str = "status") -> str:
    """The current query string with the filter set to ``values``, from the first page."""
    params = request.GET.copy()
    params.pop("page", None)
    params.setlist(param, values)
    return params.urlencode()


def filter_pills(
    request: HttpRequest,
    filters: dict,
    counts: dict[str, int],
    selected: list[str],
    *,
    param: str = "status",
    exclusive: str | None = None,
    when_empty: list[str] | None = None,
    visible=lambda key: True,
) -> list[FilterPill]:
    """One pill per filter that toggles it in the selection.

    ``exclusive`` is a filter that cannot be combined (like "Alle"): choosing it replaces the selection, and
    choosing another one replaces it. ``when_empty`` is the selection that stands in for none at all, for lists
    whose default is not unfiltered. ``visible`` hides filters that would show nothing; selected ones stay.
    """
    pills = []
    for key, (label, _) in filters.items():
        active = key in selected
        if not (active or visible(key)):
            continue
        if key == exclusive or (exclusive in selected):
            values = [key]
        else:
            values = [k for k in filters if (k in selected) != (k == key)] or (when_empty or [])
        pills.append(FilterPill(key, label, counts[key], active, query_with(request, values, param)))
    return pills
