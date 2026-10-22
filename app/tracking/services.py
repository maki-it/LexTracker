from django.db import transaction
from django.utils import timezone

from projects.models import Task
from tracking.models import TimeEntry

# Timers shorter than this are discarded when stopped, e.g. after a misclick.
MIN_DURATION_SECONDS = 30


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
    entry.ended_at = now
    entry.save(update_fields=["ended_at", "updated_at"])
    return entry
