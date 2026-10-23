"""Messages the scheduler creates for what is going on right now: a timer that runs for hours."""

from datetime import datetime, timedelta

from django.urls import reverse

from accounts.models import User
from core.models import AppSettings
from inbox.levels import Level
from inbox.models import Message
from inbox.service import anotify, aresolve
from tracking.models import TimeEntry

KIND = "timer.long"


def hours_text(running_for: timedelta) -> str:
    return f"{int(running_for.total_seconds() // 3600)} Stunden"


async def notify_long_timers(now: datetime, hours: int) -> int:
    """Warn whoever has had a timer running for ``hours``, once per timer, and clear the warning once it stops.

    This does not depend on e-mail: the weekly mail reminder (``mailer.jobs``) is a separate thing.
    """
    running = (
        TimeEntry.objects.filter(ended_at__isnull=True, started_at__lte=now - timedelta(hours=hours))
        .exclude(user__role=User.Role.CUSTOMER)
        .select_related("user", "task", "task__project", "task__project__customer")
        .order_by("started_at")
    )
    told = 0
    keys = set()
    async for entry in running:
        key = f"timer:{entry.pk}"
        keys.add(key)
        # Only once, however long it keeps running (and even if the warning was read or deleted already).
        if await Message.objects.filter(dedupe_key=key).aexists():
            continue
        project = entry.task.project
        await anotify(
            Level.WARNING,
            KIND,
            f"Dein Timer läuft schon seit {hours_text(now - entry.started_at)}",
            f"{project.customer.name} · {project.name} · {entry.task.name}",
            url=reverse("core:dashboard"),
            to=entry.user,
            dedupe_key=key,
        )
        told += 1
    # A timer that was stopped since needs no warning anymore.
    open_keys = {
        key
        async for key in Message.objects.filter(kind=KIND, read_at__isnull=True).values_list("dedupe_key", flat=True)
    }
    for key in open_keys - keys:
        await aresolve(key)
    return told


async def run_due(now: datetime) -> dict[str, int]:
    app_settings = await AppSettings.aload()
    if not app_settings.timer_reminder_hours:
        return {}
    return {"long timer": await notify_long_timers(now, app_settings.timer_reminder_hours)}
