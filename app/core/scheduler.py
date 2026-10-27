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
from uuid import UUID

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
from lexware import credentials, webhooks
from lexware.client import LexwareError, client_from_settings
from mailer import jobs as mail_jobs
from mailer import outbox
from push import jobs as push_jobs
from reminders import jobs as reminder_jobs

logger = logging.getLogger(__name__)

# How often the scheduler looks for due jobs. Settings changes apply within this time.
CHECK_INTERVAL = 60

# How often the outgoing mail queue is looked at, so a login link arrives within seconds.
MAIL_INTERVAL = 5

# How often the calls from Lexware (webhooks) are looked at, so a change shows up within seconds.
WEBHOOK_INTERVAL = 5

# Up to this many changed contacts or invoices are loaded one by one; more than that are cheaper as a full sync.
WEBHOOK_MAX_SINGLE = 10

# After a failed sync that a webhook asked for, wait this long before trying again.
WEBHOOK_RETRY_AFTER = 60

# How often the running timer on the devices that show it is compared with the real one.
PUSH_TIMER_INTERVAL = 5

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


job_locks = {job.key: asyncio.Lock() for job in JOBS}


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


async def run_job(job: Job) -> bool:
    """Run one sync and tell the users how it went. False if it failed (the failure is reported as a message)."""
    # Only one at a time per sync, so a run on a webhook and a run on the interval never overlap.
    async with job_locks[job.key]:
        try:
            async with jobs.tracked(job.key) as tracking:
                result = await job.run()
                tracking.result = result.summary
        except LexwareError as exc:
            logger.warning("Automatic %s failed: %s", job.name, exc)
            await inbox_events.job_failed(job.key, job.label, exc)
            return False
        logger.info("Automatic %s: %s", job.name, result.summary)
        # The summary is worded for each reader in their language, so it is passed as a function.
        await inbox_events.job_done(
            job.key,
            job.label,
            functools.partial(getattr, result, "summary"),
            changed=getattr(result, "has_changes", False),
        )
        return True


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
        await run_job(job)
    return ran


async def _run_single_syncs(key: str, what: str, resource_ids: list[UUID], sync_one) -> bool:
    """Run ``sync_one(client, resource_id)`` for each id. False if that failed (reported as a message).

    Unlike the full sync this leaves the time of the last full run alone, so the sync on schedule still runs.
    """
    job = next(job for job in JOBS if job.key == key)
    async with job_locks[key]:
        try:
            async with client_from_settings() as client:
                for resource_id in resource_ids:
                    await sync_one(client, resource_id)
        except LexwareError as exc:
            logger.warning("Updating %s %s on a call from Lexware failed: %s", len(resource_ids), what, exc)
            await inbox_events.job_failed(job.key, job.label, exc)
            return False
    logger.info("Updated %s %s on a call from Lexware", len(resource_ids), what)
    return True


async def run_contact_syncs(contact_ids: list[UUID]) -> bool:
    """Update just these customers from Lexware."""
    return await _run_single_syncs("customers", "customer(s)", contact_ids, customer_sync.sync_contact)


async def run_invoice_syncs(invoice_ids: list[UUID]) -> bool:
    """Update just these invoices from Lexware."""
    return await _run_single_syncs("invoices", "invoice(s)", invoice_ids, invoice_sync.sync_invoice)


async def run_webhook_syncs(retry_at: dict[str, datetime], now: datetime) -> list[str]:
    """Run the syncs that Lexware has called for. ``retry_at`` holds when a failed one may be tried again."""
    if not await credentials.ais_configured():
        return []
    waiting = {key for key, at in retry_at.items() if at > now}
    ran = []
    for job in JOBS:
        if job.key in waiting:
            continue
        # Claim per sync, so a sync that has to wait does not hold back the calls for the others.
        if not (claimed := await webhooks.aclaim(job.key)):
            continue
        resource_ids = {e.resource_id for e in claimed}
        # A few changed contacts or invoices: load only those.
        few = None not in resource_ids and len(resource_ids) <= WEBHOOK_MAX_SINGLE
        try:
            if job.key == "customers" and few:
                ran.append(_("%(count)d Kunden") % {"count": len(resource_ids)})
                done = await run_contact_syncs(sorted(resource_ids))
            elif job.key == "invoices" and few:
                ran.append(_("%(count)d Rechnungen") % {"count": len(resource_ids)})
                done = await run_invoice_syncs(sorted(resource_ids))
            else:
                ran.append(job.name)
                done = await run_job(job)
        except Exception:
            # Not a Lexware error (those are reported and give ``done = False``): the calls must not get lost.
            await webhooks.arelease(claimed)
            retry_at[job.key] = now + timedelta(seconds=WEBHOOK_RETRY_AFTER)
            raise
        if done:
            retry_at.pop(job.key, None)
        else:
            await webhooks.arelease(claimed)
            retry_at[job.key] = now + timedelta(seconds=WEBHOOK_RETRY_AFTER)
    return ran


async def process_webhooks(stop: asyncio.Event) -> None:
    """Look every few seconds for calls from Lexware and run the syncs they ask for."""
    retry_at: dict[str, datetime] = {}
    while not stop.is_set():
        try:
            async with jobs.tracked("webhooks") as tracking:
                ran = await run_webhook_syncs(retry_at, timezone.now())
                tracking.result = ", ".join(ran)
                tracking.idle = not ran
        except Exception:
            logger.exception("Syncing on a call from Lexware failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), WEBHOOK_INTERVAL)


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


async def show_timers(stop: asyncio.Event) -> None:
    """Keep the running timer on the devices that show it as a notification, every few seconds."""
    while not stop.is_set():
        try:
            async with jobs.tracked("push-timer") as tracking:
                told = await push_jobs.sync_timers(timezone.now())
                tracking.result = f"{told} benachrichtigt"
                tracking.idle = not told
        except Exception:
            logger.exception("Updating the timer notifications failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), PUSH_TIMER_INTERVAL)


async def run(stop: asyncio.Event) -> None:
    logger.info("Scheduler started")
    mailer = asyncio.create_task(send_mail(stop))
    hooks = asyncio.create_task(process_webhooks(stop))
    timers = asyncio.create_task(show_timers(stop))
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
            async with jobs.tracked("reminders") as tracking:
                announced = {name: count for name, count in (await reminder_jobs.run_due(now)).items() if count}
                tracking.result = ", ".join(f"{count} {name}" for name, count in announced.items())
                tracking.idle = not announced
            for name, count in announced.items():
                logger.info("Announced %s %s%s", count, name, "s" if count > 1 else "")
        except Exception:
            logger.exception("Announcing reminders failed")
        try:
            if last_prune is None or now - last_prune >= PRUNE_INTERVAL:
                async with jobs.tracked("prune") as tracking:
                    deleted = await inbox.prune(now) + await webhooks.aprune(now)
                    tracking.result = _("%(count)d gelöscht") % {"count": deleted}
                last_prune = now
        except Exception:
            logger.exception("Deleting messages failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CHECK_INTERVAL)
    await mailer
    await hooks
    await timers
    logger.info("Scheduler stopped")
