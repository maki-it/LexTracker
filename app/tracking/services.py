import math
from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from core.models import AppSettings
from projects.models import Task
from tracking.models import TimeEntry

# Timers shorter than this are discarded when stopped, e.g. after a misclick.
MIN_DURATION_SECONDS = 30


def rounded_end(started_at: datetime, ended_at: datetime, minutes: int) -> datetime:
    """Move ``ended_at`` so the duration is a whole number of ``minutes`` steps, rounding up."""
    if not minutes:
        return ended_at
    step = timedelta(minutes=minutes)
    return started_at + step * math.ceil((ended_at - started_at) / step)


@transaction.atomic
def start_timer(user, task: Task, description: str = "") -> TimeEntry:
    """Stop the user's running timer, if any, and start a new one on ``task``."""
    stop_timer(user)
    return TimeEntry.objects.create(user=user, task=task, description=description, is_billable=task.is_billable)


@transaction.atomic
def stop_timer(user) -> TimeEntry | None:
    entry = TimeEntry.objects.select_for_update().filter(user=user, ended_at__isnull=True).first()
    if entry is None:
        return None
    now = timezone.now()
    if (now - entry.started_at).total_seconds() < MIN_DURATION_SECONDS:
        entry.delete()
        return None
    entry.ended_at = rounded_end(entry.started_at, now, AppSettings.load().time_rounding)
    entry.save(update_fields=["ended_at", "updated_at"])
    return entry
