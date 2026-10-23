from datetime import datetime, timedelta

from django.db import transaction
from django.utils import timezone

from core.models import AppSettings
from projects.models import Task
from tracking.models import TimeEntry

# Timers shorter than this are discarded when stopped, e.g. after a misclick.
MIN_DURATION_SECONDS = 30


def round_to_step(moment: datetime, minutes: int) -> datetime:
    """Round ``moment`` to the nearest ``minutes`` step on the local clock, e.g. 9:07 → 9:00 and 9:08 → 9:15."""
    if not minutes:
        return moment
    local = timezone.localtime(moment).replace(tzinfo=None)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    step = timedelta(minutes=minutes)
    # Half a step rounds up, as people expect from rounding on paper.
    steps = int((local - midnight + step / 2) // step)
    return timezone.make_aware(midnight + step * steps)


def rounded_times(started_at: datetime, ended_at: datetime, minutes: int) -> tuple[datetime, datetime]:
    """Round start and end to the nearest ``minutes`` step; an entry keeps at least one step."""
    if not minutes:
        return started_at, ended_at
    start, end = round_to_step(started_at, minutes), round_to_step(ended_at, minutes)
    return start, max(end, start + timedelta(minutes=minutes))


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
    entry.started_at, entry.ended_at = rounded_times(entry.started_at, now, AppSettings.load().time_rounding)
    entry.save(update_fields=["started_at", "ended_at", "updated_at"])
    return entry
