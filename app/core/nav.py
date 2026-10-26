"""What the sidebar shows besides its links: the running timer, the bell and the numbers next to the links."""

from collections.abc import Awaitable, Callable

from django.http import HttpRequest, HttpResponse
from django.utils.decorators import async_only_middleware

from inbox import service as inbox
from projects.models import Project
from reminders import queries as reminder_queries
from tracking.models import TimeEntry


async def nav_counts(user) -> dict[str, int]:
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
        "reminders": await reminder_queries.due_count(user),
    }


async def running_entry(user) -> TimeEntry | None:
    entries = TimeEntry.objects.filter(user=user, ended_at__isnull=True)
    return await entries.select_related("task__project__customer").afirst()


SKIPPED = ("/static/", "/mcp/")


@async_only_middleware
def NavCountsMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Full pages only, since htmx requests never render the sidebar.

    The timer is rendered with the page instead of being loaded after it, so the sidebar does not jump.
    """

    async def middleware(request: HttpRequest) -> HttpResponse:
        user = request.user
        if user.is_authenticated and not request.htmx and not request.path.startswith(SKIPPED):
            if not user.is_customer:
                request.nav_timer = {"running_entry": await running_entry(user)}
                request.nav_inbox = await inbox.summary(user)
            if user.is_admin:
                request.nav_counts = await nav_counts(user)
        return await get_response(request)

    return middleware
