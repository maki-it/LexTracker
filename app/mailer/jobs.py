"""E-mails the scheduler sends on its own: the weekly report and the reminder about a timer left running.

When they go out is set on the settings page; each user can turn them off in their account.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode

from accounts.models import User
from core.models import AppSettings
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail
from reports.queries import build_report, entries_in
from reports.ranges import DateRange
from tracking.models import TimeEntry

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
# A weekly report missed by more than this (e.g. the server was down) waits for the next week.
CATCH_UP = timedelta(days=1)


def last_weekly_slot(now: datetime, weekday: int, at: time) -> datetime:
    """The most recent time the weekly report was planned for, at or before ``now``."""
    local = timezone.localtime(now)
    day = local.date() - timedelta(days=(local.weekday() - weekday) % 7)
    slot = datetime.combine(day, at, tzinfo=local.tzinfo)
    return slot if slot <= local else slot - timedelta(days=7)


def weekly_report_due(now: datetime, app_settings: AppSettings) -> datetime | None:
    """The slot to send the weekly report for, or None if it is not due."""
    if not app_settings.weekly_report_enabled:
        return None
    slot = last_weekly_slot(now, app_settings.weekly_report_weekday, app_settings.weekly_report_time)
    if now - slot > CATCH_UP:
        return None
    if app_settings.weekly_report_at is not None and app_settings.weekly_report_at >= slot:
        return None
    return slot


def report_range(sent_on: date) -> DateRange:
    """The seven days before the day the report is sent; on a Monday that is the week before."""
    end = sent_on - timedelta(days=1)
    start = end - timedelta(days=6)
    return DateRange("", f"{start:%d.%m.} – {end:%d.%m.%Y}", start, end)


@dataclass
class Line:
    label: str
    duration: timedelta
    share: int = 0


@dataclass
class WeeklyReport:
    range: DateRange
    total: timedelta = field(default_factory=timedelta)
    billable: timedelta = field(default_factory=timedelta)
    days: list[Line] = field(default_factory=list)
    projects: list[Line] = field(default_factory=list)
    # Administrators only: the whole business (see reports.queries.build_report).
    overview: object = None
    team_total: timedelta | None = None

    @property
    def is_empty(self) -> bool:
        return not self.total and (self.overview is None or not self.overview.totals.total)


def build_weekly_report(user: User, rng: DateRange) -> WeeklyReport:
    report = WeeklyReport(rng)
    per_day = {rng.start + timedelta(days=i): timedelta() for i in range(rng.days)}
    per_project: dict[int, Line] = {}
    for entry in entries_in(rng.start, rng.end).filter(user=user):
        report.total += entry.duration
        if entry.is_billable and entry.task.is_billable:
            report.billable += entry.duration
        day = timezone.localtime(entry.started_at).date()
        per_day[day] = per_day.get(day, timedelta()) + entry.duration
        project = entry.task.project
        line = per_project.setdefault(project.pk, Line(f"{project.customer.name} · {project.name}", timedelta()))
        line.duration += entry.duration
    longest = max(per_day.values(), default=timedelta()) or timedelta(hours=1)
    report.days = [
        Line(f"{WEEKDAYS[day.weekday()]} {day:%d.%m.}", total, round(total / longest * 100))
        for day, total in per_day.items()
    ]
    report.projects = sorted(per_project.values(), key=lambda line: line.duration, reverse=True)
    if user.is_admin:
        report.overview = build_report(rng)
        if report.overview.totals.total != report.total:
            report.team_total = report.overview.totals.total
    return report


def _recipients(**flags):
    return (
        User.objects.filter(is_active=True, **flags)
        .exclude(role=User.Role.CUSTOMER)
        .exclude(Q(email="") | Q(email__isnull=True))
    )


async def queue_weekly_reports(slot: datetime) -> int:
    rng = report_range(timezone.localtime(slot).date())
    base_url = (await MailSettings.aload()).base_url.rstrip("/")
    queued = 0
    async for user in _recipients(weekly_report=True):
        key = f"weekly-report:{user.pk}:{rng.start.isoformat()}"
        if await OutgoingMail.objects.filter(dedupe_key=key).aexists():
            continue
        report = await sync_to_async(build_weekly_report)(user, rng)
        if report.is_empty:
            continue
        if not base_url:
            url = ""
        elif user.is_admin:
            query = urlencode({"von": rng.start.isoformat(), "bis": rng.end.isoformat()})
            url = f"{base_url}{reverse('reports:overview')}?{query}"
        else:
            url = f"{base_url}{reverse('tracking:list')}"
        context = {"user": user, "report": report, "url": url, "duration_format": user.duration_format}
        await outbox.aqueue(
            OutgoingMail.Kind.WEEKLY_REPORT,
            user.email,
            f"Dein Wochenbericht {rng.label}",
            "weekly_report",
            context,
            user=user,
            dedupe_key=key,
        )
        queued += 1
    return queued


async def queue_timer_reminders(now: datetime, hours: int) -> int:
    base_url = (await MailSettings.aload()).base_url.rstrip("/")
    running = (
        TimeEntry.objects.filter(
            ended_at__isnull=True,
            started_at__lte=now - timedelta(hours=hours),
            user__in=_recipients(timer_reminder=True),
        )
        .select_related("user", "task", "task__project", "task__project__customer")
        .order_by("started_at")
    )
    queued = 0
    async for entry in running:
        key = f"timer-reminder:{entry.pk}"
        if await OutgoingMail.objects.filter(dedupe_key=key).aexists():
            continue
        context = {
            "user": entry.user,
            "entry": entry,
            "running_for": now - entry.started_at,
            "url": f"{base_url}{reverse('core:dashboard')}" if base_url else "",
            "duration_format": entry.user.duration_format,
            "datetime_format": f"{entry.user.date_format}, H:i",
        }
        await outbox.aqueue(
            OutgoingMail.Kind.TIMER_REMINDER,
            entry.user.email,
            "Dein Timer läuft noch",
            "timer_reminder",
            context,
            user=entry.user,
            dedupe_key=key,
        )
        queued += 1
    return queued


async def run_due(now: datetime) -> dict[str, int]:
    """Queue the reports and reminders that are due. Returns how many of each were queued."""
    if not await outbox.ais_configured():
        return {}
    app_settings = await AppSettings.aload()
    queued = {}
    if slot := weekly_report_due(now, app_settings):
        queued["weekly report"] = await queue_weekly_reports(slot)
        await AppSettings.objects.filter(pk=1).aupdate(weekly_report_at=now)
    if app_settings.timer_reminder_hours:
        queued["timer reminder"] = await queue_timer_reminders(now, app_settings.timer_reminder_hours)
    return queued
