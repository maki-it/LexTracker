"""What the scheduler remembers about its jobs, for the jobs page.

The scheduler is its own process, so the web app can only learn about it from the database: every run of a job
is noted in ``JobStatus`` and every check of the scheduler in ``AppSettings.scheduler_seen_at``.
Failures are not reported here; they reach the users as messages (``inbox.events``).
"""

import logging
import time as clock
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone

from core.models import AppSettings, JobStatus

logger = logging.getLogger(__name__)

# The scheduler checks once a minute (``scheduler.CHECK_INTERVAL``). Seen longer ago than this, it counts as stopped.
ALIVE_FOR = timedelta(minutes=5)


@dataclass
class Run:
    """What a job tells while it runs. ``idle`` marks a check that found nothing to do."""

    result: str = ""
    idle: bool = False


@asynccontextmanager
async def tracked(key: str):
    """Note how the job in the block went: when, for how long, the outcome and its error. Errors are raised again.

    A check that found nothing to do (``run.idle``) leaves no trace, unless the job failed before: then it
    is noted, so a job that works again does not keep showing its old error.
    """
    run = Run()
    started = timezone.now()
    began = clock.monotonic()
    try:
        yield run
    except Exception as exc:
        await _record(key, started, began, f"{type(exc).__name__}: {exc}", ok=False)
        raise
    if run.idle and not await JobStatus.objects.filter(key=key, last_ok=False).aexists():
        return
    await _record(key, started, began, run.result, ok=True)


async def _record(key: str, started: datetime, began: float, result: str, *, ok: bool) -> None:
    """Never raises: a status that cannot be stored must not stop the job it is about."""
    try:
        status, _ = await JobStatus.objects.aget_or_create(key=key)
        status.last_run_at = started
        status.duration_ms = round((clock.monotonic() - began) * 1000)
        status.last_ok = ok
        status.last_result = result[:500]
        if ok:
            status.last_success_at = started
            status.failures = 0
        else:
            status.failures += 1
            status.last_error = result[:500]
            status.last_error_at = started
        await status.asave()
    except Exception:
        logger.exception("Could not store the status of %s", key)


async def beat(now: datetime, *, started: bool = False) -> None:
    """Tell the web app that the scheduler is alive. Only these columns, so a settings change is not overwritten."""
    fields = {"scheduler_seen_at": now}
    if started:
        fields["scheduler_started_at"] = now
    try:
        await AppSettings.aload()
        await AppSettings.objects.filter(pk=1).aupdate(**fields)
    except Exception:
        logger.exception("Could not store the scheduler heartbeat")


def is_alive(app_settings: AppSettings, now: datetime) -> bool | None:
    """Whether the scheduler checked lately; None if it never has (not started yet, or not at all)."""
    if app_settings.scheduler_seen_at is None:
        return None
    return now - app_settings.scheduler_seen_at <= ALIVE_FOR
