"""The jobs page: every job of the scheduler with its schedule, next run and how the last one went."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone

from core import backup
from core.models import AppSettings, JobStatus
from core.scheduler import CHECK_INTERVAL, in_window


def next_sync(now: datetime, interval: int, start, end, last: datetime | None) -> datetime | None:
    """When a job with an interval and a time window runs next (``scheduler.is_due``); None if it is off.

    Not before ``now``: a job that is due runs at the next check. The first time it runs is the start of the window.
    """
    if not interval:
        return None
    candidate = (
        now if last is None else max(now, last + timedelta(minutes=interval) - timedelta(seconds=CHECK_INTERVAL))
    )
    local = timezone.localtime(candidate)
    if in_window(local.time(), start, end):
        return candidate
    # Outside the window: when it opens, today or tomorrow.
    opens = datetime.combine(local.date(), start or time.min, tzinfo=local.tzinfo)
    return opens if opens > local else opens + timedelta(days=1)


def next_backup(now: datetime, app_settings: AppSettings) -> datetime | None:
    if not app_settings.backup_enabled:
        return None
    local = timezone.localtime(now)
    if backup.is_due(now, app_settings):
        return now
    for day in (local.date(), local.date() + timedelta(days=1)):
        at = datetime.combine(day, app_settings.backup_time, tzinfo=local.tzinfo)
        if at > local and backup.is_due(at, app_settings):
            return at
    return None


@dataclass
class JobRow:
    key: str
    label: str
    schedule: str
    next_run: datetime | None
    # Whether ``next_run`` is meaningful for this job: those that only look for work every minute have none.
    scheduled: bool
    status: JobStatus | None


def _every(minutes: int) -> str:
    if minutes % 1440 == 0:
        return "täglich" if minutes == 1440 else f"alle {minutes // 1440} Tage"
    if minutes % 60 == 0:
        return "stündlich" if minutes == 60 else f"alle {minutes // 60} Stunden"
    return f"alle {minutes} Minuten"


def _window(start, end) -> str:
    if start is None and end is None:
        return ""
    return (
        f", {start:%H:%M} – {end:%H:%M} Uhr"
        if start and end
        else f", ab {start:%H:%M} Uhr"
        if start
        else f", bis {end:%H:%M} Uhr"
    )


async def overview(now: datetime, app_settings: AppSettings) -> list[JobRow]:
    """Every job the scheduler runs, with its schedule and how its last run went."""
    statuses = {status.key: status async for status in JobStatus.objects.all()}

    def row(key, label, schedule, next_run=None, scheduled=False):
        return JobRow(key, label, schedule, next_run, scheduled, statuses.get(key))

    s = app_settings
    weekly = (
        f"Wochenbericht {s.get_weekly_report_weekday_display()} {s.weekly_report_time:%H:%M} Uhr"
        if s.weekly_report_enabled
        else "Wochenbericht aus"
    )
    reminder = (
        f"Timer-Erinnerung nach {s.timer_reminder_hours} Std." if s.timer_reminder_hours else "Timer-Erinnerung aus"
    )
    return [
        row(
            "customers",
            "Kundenimport",
            (_every(s.lexware_sync_interval) + _window(s.lexware_sync_from, s.lexware_sync_until))
            if s.lexware_sync_interval
            else "aus",
            next_sync(now, s.lexware_sync_interval, s.lexware_sync_from, s.lexware_sync_until, s.lexware_synced_at),
            True,
        ),
        row(
            "invoices",
            "Rechnungsabgleich",
            (_every(s.invoice_sync_interval) + _window(s.invoice_sync_from, s.invoice_sync_until))
            if s.invoice_sync_interval
            else "aus",
            next_sync(now, s.invoice_sync_interval, s.invoice_sync_from, s.invoice_sync_until, s.invoices_synced_at),
            True,
        ),
        row(
            "backup",
            "Datensicherung",
            f"täglich ab {s.backup_time:%H:%M} Uhr" if s.backup_enabled else "aus",
            await sync_to_async(next_backup)(now, s),
            True,
        ),
        row("mail-queue", "E-Mail-Versand", "alle 5 Sekunden"),
        row(
            "mail-reports",
            "Berichte und Hinweise per E-Mail",
            f"jede Minute geprüft: {weekly}, {reminder}, Hinweis zu überfälligen Rechnungen",
        ),
        row("timer-messages", "Nachricht zu lange laufender Timer", "jede Minute geprüft"),
        row("prune", "Alte Nachrichten löschen", "stündlich"),
    ]
