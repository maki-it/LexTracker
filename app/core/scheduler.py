"""Recurring jobs, run by ``manage.py run_scheduler`` in its own process (its own container in Docker)."""

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone

from billing import sync as invoice_sync
from core import backup
from core.models import AppSettings
from customers import sync as customer_sync
from lexware import credentials
from lexware.client import LexwareError

logger = logging.getLogger(__name__)

# How often the scheduler looks for due jobs. Settings changes apply within this time.
CHECK_INTERVAL = 60

# Touched on every check. The container's health check looks at its age.
HEARTBEAT = Path(tempfile.gettempdir()) / "lextracker-scheduler.heartbeat"


@dataclass(frozen=True)
class Job:
    name: str
    run: Callable[[], Awaitable]
    # The AppSettings fields that configure the job and record its last run.
    interval_field: str
    from_field: str
    until_field: str
    last_run_field: str


JOBS = [
    Job(
        "customer import",
        customer_sync.sync_and_record,
        "lexware_sync_interval",
        "lexware_sync_from",
        "lexware_sync_until",
        "lexware_synced_at",
    ),
    Job(
        "invoice sync",
        invoice_sync.sync_and_record,
        "invoice_sync_interval",
        "invoice_sync_from",
        "invoice_sync_until",
        "invoices_synced_at",
    ),
]


def in_window(now: time, start: time | None, end: time | None) -> bool:
    """Whether ``now`` lies in [start, end). Open ends mean midnight; start after end wraps past midnight."""
    start = start or time.min
    if end is None or end == time.min:
        return now >= start
    if start <= end:
        return start <= now < end
    return now >= start or now < end


def is_due(now: datetime, interval: int, start: time | None, end: time | None, last: datetime | None) -> bool:
    if not interval or not in_window(timezone.localtime(now).time(), start, end):
        return False
    # Allow one check of slack, so a daily job does not slowly drift later than its start time.
    return last is None or now - last >= timedelta(minutes=interval) - timedelta(seconds=CHECK_INTERVAL)


async def run_due_jobs(now: datetime) -> list[str]:
    """Run every job whose interval has passed and whose time window is open. Returns the names that ran."""
    if not await credentials.ais_configured():
        return []
    app_settings = await AppSettings.aload()
    ran = []
    for job in JOBS:
        due = is_due(
            now,
            getattr(app_settings, job.interval_field),
            getattr(app_settings, job.from_field),
            getattr(app_settings, job.until_field),
            getattr(app_settings, job.last_run_field),
        )
        if not due:
            continue
        ran.append(job.name)
        # One job failing must not stop the others.
        try:
            result = await job.run()
        except LexwareError as exc:
            logger.warning("Automatic %s failed: %s", job.name, exc)
        else:
            logger.info("Automatic %s: %s", job.name, result.summary)
    return ran


async def run(stop: asyncio.Event) -> None:
    logger.info("Scheduler started")
    while not stop.is_set():
        HEARTBEAT.touch()
        now = timezone.now()
        try:
            await run_due_jobs(now)
        except Exception:
            # Keep running: a broken job must not stop the others or the next attempt.
            logger.exception("Scheduled job failed")
        try:
            if backup.is_due(now):
                path = await sync_to_async(backup.create_backup)(now)
                logger.info("Database backup written to %s", path)
        except Exception:
            logger.exception("Database backup failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CHECK_INTERVAL)
    logger.info("Scheduler stopped")
