"""The running timer as a notification on the devices that asked for it.

Not a push per timer start or stop in the code that does it: the timer is started and stopped from the web, the
MCP server and the entry form. Instead the scheduler compares every few seconds what each device shows with what
runs, and tells the devices that differ.
"""

import logging
from datetime import datetime

from django.urls import reverse
from django.utils import translation
from django.utils.translation import gettext as _

from core.templatetags.timefmt import hours
from push import service
from push.models import PushSubscription
from push.topics import Topic
from tracking.models import TimeEntry

logger = logging.getLogger(__name__)

# How long a push service keeps a timer notification for a device that is offline. A day old news about a timer is
# worse than none.
TTL = 120


def _label(entry: TimeEntry) -> str:
    task = entry.task
    return f"{task.project.customer.name} · {task.project.name} · {task.name}"


async def sync_timers(now: datetime) -> int:
    """Show the running timer on the devices that want it and take it off the others. Returns how many were told."""
    devices = [sub async for sub in PushSubscription.objects.select_related("user").filter(user__is_active=True)]
    # Only those that want to see the timer, or still show one.
    devices = [d for d in devices if Topic.TIMER_LIVE in d.topics or d.timer_shown]
    if not devices:
        return 0
    users = {d.user_id for d in devices}
    entries = TimeEntry.objects.select_related("task__project__customer")
    running = {e.user_id: e async for e in entries.filter(user_id__in=users, ended_at__isnull=True)}
    shown = {d.timer_shown for d in devices if d.timer_shown}
    finished = {e.pk: e async for e in entries.filter(pk__in=shown)}
    told = 0
    for device in devices:
        entry = running.get(device.user_id) if Topic.TIMER_LIVE in device.topics else None
        if (entry.pk if entry else None) == device.timer_shown:
            continue
        with translation.override(device.user.ui_language):
            if entry:
                message = {
                    "kind": "timer",
                    "title": _("Timer läuft"),
                    "body": _label(entry),
                    "since": int(entry.started_at.timestamp() * 1000),
                    "url": reverse("core:dashboard"),
                }
            else:
                done = finished.get(device.timer_shown)
                message = {
                    "kind": "timer-end",
                    "title": _("Timer gestoppt"),
                    "body": f"{_label(done)} · {hours(done.duration, device.user.duration_format)}"
                    if done and done.ended_at
                    else "",
                    "url": reverse("core:dashboard"),
                }
        # Noted whether or not the push service took it, so a device that is unreachable is not tried every few seconds.
        await PushSubscription.objects.filter(pk=device.pk).aupdate(timer_shown=entry.pk if entry else None)
        if await service.apush([device], message, ttl=TTL):
            told += 1
    return told
