"""Recurring jobs, run by ``manage.py run_scheduler`` in its own process (its own container in Docker)."""

import asyncio
import functools
import logging
import tempfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.utils.functional import Promise
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy

from billing import sync as invoice_sync
from core import backup, jobs
from core.models import AppSettings
from customers import sync as customer_sync
from inbox import events as inbox_events
from inbox import jobs as inbox_jobs
from inbox import service as inbox
from lexware import credentials
from lexware.client import LexwareError
from mailer import jobs as mail_jobs
from mailer import outbox

logger = logging.getLogger(__name__)

# How often the scheduler looks for due jobs. Settings changes apply within this time.
CHECK_INTERVAL = 60

# How often the outgoing mail queue is looked at, so a login link arrives within seconds.
MAIL_INTERVAL = 5

# How often old messages are deleted.
PRUNE_INTERVAL = timedelta(hours=1)

# Touched on every check. The container's health check looks at its age.
HEARTBEAT = Path(tempfile.gettempdir()) / "lextracker-scheduler.heartbeat"


@dataclass(frozen=True)
class Job:
    name: str
    run: Callable[[], Awaitable]
    # How messages about it refer to it: the name in the key and the name in the title.
    key: str
    label: str | Promise
    # The AppSettings fields that configure the job and record its last run.
    interval_field: str
    from_field: str
    until_field: str
    last_run_field: str


JOBS = [
    Job(
        "customer import",
        customer_sync.sync_and_record,
        "customers",
        gettext_lazy("Kundenimport"),
        "lexware_sync_interval",
        "lexware_sync_from",
        "lexware_sync_until",
        "lexware_synced_at",
    ),
    Job(
        "invoice sync",
        invoice_sync.sync_and_record,
        "invoices",
        gettext_lazy("Rechnungsabgleich"),
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
            async with jobs.tracked(job.key) as tracking:
                result = await job.run()
                tracking.result = result.summary
        except LexwareError as exc:
            logger.warning("Automatic %s failed: %s", job.name, exc)
            await inbox_events.job_failed(job.key, job.label, exc)
        else:
            logger.info("Automatic %s: %s", job.name, result.summary)
            # The summary is worded for each reader in their language, so it is passed as a function.
            await inbox_events.job_done(
                job.key,
                job.label,
                functools.partial(getattr, result, "summary"),
                changed=getattr(result, "has_changes", False),
            )
    return ran


async def send_mail(stop: asyncio.Event) -> None:
    """Send the queued e-mails, every few seconds."""
    while not stop.is_set():
        try:
            async with jobs.tracked("mail-queue") as tracking:
                sent = await outbox.send_due(on_failed=inbox_events.mail_failed)
                tracking.result = f"{sent} gesendet"
                tracking.idle = not sent
            if sent:
                logger.info("Sent %s e-mail%s", sent, "s" if sent > 1 else "")
        except Exception:
            logger.exception("Sending e-mails failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), MAIL_INTERVAL)


async def run(stop: asyncio.Event) -> None:
    logger.info("Scheduler started")
    mailer = asyncio.create_task(send_mail(stop))
    last_prune = None
    first = True
    while not stop.is_set():
        HEARTBEAT.touch()
        now = timezone.now()
        await jobs.beat(now, started=first)
        first = False
        try:
            await run_due_jobs(now)
        except Exception:
            # Keep running: a broken job must not stop the others or the next attempt.
            logger.exception("Scheduled job failed")
        try:
            if backup.is_due(now, await AppSettings.aload()):
                async with jobs.tracked("backup") as tracking:
                    path = await sync_to_async(backup.backup_and_record)(now)
                    tracking.result = path.name
                logger.info("Database backup written to %s", path)
                await inbox_events.backup_done(path.name)
        except Exception as exc:
            logger.exception("Database backup failed")
            await inbox_events.backup_failed(exc)
        try:
            async with jobs.tracked("mail-reports") as tracking:
                queued = {name: count for name, count in (await mail_jobs.run_due(now)).items() if count}
                tracking.result = ", ".join(f"{count} {name}" for name, count in queued.items())
                tracking.idle = not queued
            for name, count in queued.items():
                logger.info("Queued %s %s e-mail%s", count, name, "s" if count > 1 else "")
        except Exception:
            logger.exception("Queueing reports and reminders failed")
        try:
            async with jobs.tracked("timer-messages") as tracking:
                created = {name: count for name, count in (await inbox_jobs.run_due(now)).items() if count}
                tracking.result = ", ".join(f"{count} {name}" for name, count in created.items())
                tracking.idle = not created
            for name, count in created.items():
                logger.info("Created %s %s message%s", count, name, "s" if count > 1 else "")
        except Exception:
            logger.exception("Creating messages failed")
        try:
            if last_prune is None or now - last_prune >= PRUNE_INTERVAL:
                async with jobs.tracked("prune") as tracking:
                    tracking.result = _("%(count)d gelöscht") % {"count": await inbox.prune(now)}
                last_prune = now
        except Exception:
            logger.exception("Deleting messages failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CHECK_INTERVAL)
    await mailer
    logger.info("Scheduler stopped")
