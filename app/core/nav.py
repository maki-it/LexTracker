"""Numbers shown next to the links in the sidebar."""

from collections.abc import Awaitable, Callable

from django.http import HttpRequest, HttpResponse
from django.utils.decorators import async_only_middleware

from projects.models import Project
from tracking.models import TimeEntry


async def nav_counts() -> dict[str, int]:
    open_time = TimeEntry.objects.filter(
        ended_at__isnull=False,
        invoice__isnull=True,
        is_billable=True,
        task__is_billable=True,
        task__project__customer__is_archived=False,
    )
    return {
        "projects": await Project.objects.filter(status=Project.Status.ACTIVE).acount(),
        "billable_customers": await open_time.values("task__project__customer").distinct().acount(),
    }


@async_only_middleware
def NavCountsMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Count for full pages only. htmx requests swap parts of a page and never render the sidebar."""

    async def middleware(request: HttpRequest) -> HttpResponse:
        if request.user.is_authenticated and not request.htmx and not request.path.startswith(("/static/", "/mcp/")):
            request.nav_counts = await nav_counts()
        return await get_response(request)

    return middleware
