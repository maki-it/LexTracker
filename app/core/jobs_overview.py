"""The jobs page: every job of the scheduler with its schedule, next run and how the last one went."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.utils import timezone
from django.utils.translation import gettext as _

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
        if minutes == 1440:
            return _("täglich")
        return _("alle %(count)d Tage") % {"count": minutes // 1440}
    if minutes % 60 == 0:
        if minutes == 60:
            return _("stündlich")
        return _("alle %(count)d Stunden") % {"count": minutes // 60}
    return _("alle %(count)d Minuten") % {"count": minutes}


def _window(start, end) -> str:
    if start is None and end is None:
        return ""
    if start and end:
        return _(", %(start)s – %(end)s Uhr") % {"start": f"{start:%H:%M}", "end": f"{end:%H:%M}"}
    if start:
        return _(", ab %(time)s Uhr") % {"time": f"{start:%H:%M}"}
    return _(", bis %(time)s Uhr") % {"time": f"{end:%H:%M}"}


async def overview(now: datetime, app_settings: AppSettings) -> list[JobRow]:
    """Every job the scheduler runs, with its schedule and how its last run went."""
    statuses = {status.key: status async for status in JobStatus.objects.all()}

    def row(key, label, schedule, next_run=None, scheduled=False):
        return JobRow(key, label, schedule, next_run, scheduled, statuses.get(key))

    s = app_settings
    weekly = (
        _("Wochenbericht %(weekday)s %(time)s Uhr")
        % {"weekday": s.get_weekly_report_weekday_display(), "time": f"{s.weekly_report_time:%H:%M}"}
        if s.weekly_report_enabled
        else _("Wochenbericht aus")
    )
    reminder = (
        _("Timer-Erinnerung nach %(hours)s Std.") % {"hours": s.timer_reminder_hours}
        if s.timer_reminder_hours
        else _("Timer-Erinnerung aus")
    )
    return [
        row(
            "customers",
            _("Kundenimport"),
            (_every(s.lexware_sync_interval) + _window(s.lexware_sync_from, s.lexware_sync_until))
            if s.lexware_sync_interval
            else _("aus"),
            next_sync(now, s.lexware_sync_interval, s.lexware_sync_from, s.lexware_sync_until, s.lexware_synced_at),
            True,
        ),
        row(
            "invoices",
            _("Rechnungsabgleich"),
            (_every(s.invoice_sync_interval) + _window(s.invoice_sync_from, s.invoice_sync_until))
            if s.invoice_sync_interval
            else _("aus"),
            next_sync(now, s.invoice_sync_interval, s.invoice_sync_from, s.invoice_sync_until, s.invoices_synced_at),
            True,
        ),
        row(
            "backup",
            _("Datensicherung"),
            _("täglich ab %(time)s Uhr") % {"time": f"{s.backup_time:%H:%M}"} if s.backup_enabled else _("aus"),
            await sync_to_async(next_backup)(now, s),
            True,
        ),
        row("webhooks", _("Abgleich auf Meldung von Lexware"), _("alle 5 Sekunden geprüft")),
        row("mail-queue", _("E-Mail-Versand"), _("alle 5 Sekunden")),
        row(
            "mail-reports",
            _("Berichte und Hinweise per E-Mail"),
            _("jede Minute geprüft: %(weekly)s, %(reminder)s, Hinweis zu überfälligen Rechnungen")
            % {"weekly": weekly, "reminder": reminder},
        ),
        row(
            "timer-messages",
            _("Nachrichten zu lange laufenden Timern und überfälligen Rechnungen"),
            _("jede Minute geprüft"),
        ),
        row("push-timer", _("Laufender Timer als Push-Benachrichtigung"), _("alle 5 Sekunden")),
        row("reminders", _("Erinnerungen"), _("jede Minute geprüft")),
        row("prune", _("Alte Nachrichten löschen"), _("stündlich")),
    ]
