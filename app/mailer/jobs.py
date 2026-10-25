"""E-mails the scheduler sends on its own: the weekly report, the reminder about a timer left running and the
notice about an overdue invoice.

When they go out is set on the settings page; each user can turn the first two off in their account.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy
from django.utils.translation import gettext_lazy as _

from accounts.models import User
from billing.models import Invoice
from core.i18n import date_format, datetime_format, fmt, full_date, short_date
from core.models import AppSettings
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail
from reports.queries import build_report, entries_in
from reports.ranges import DateRange
from tracking.models import TimeEntry

WEEKDAYS = [
    gettext_lazy("Mo"),
    gettext_lazy("Di"),
    gettext_lazy("Mi"),
    gettext_lazy("Do"),
    gettext_lazy("Fr"),
    gettext_lazy("Sa"),
    gettext_lazy("So"),
]
# A weekly report missed by more than this (e.g. the server was down) waits for the next week.
CATCH_UP = timedelta(days=1)
# Invoices overdue for longer than this get no notice, so turning the notice on does not remind customers
# of every old invoice at once.
OVERDUE_CATCH_UP = timedelta(days=7)
# The status must have been checked with Lexware this recently, so a paid invoice is not mistaken for an open one.
OVERDUE_STATUS_MAX_AGE = timedelta(days=1)


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
    return DateRange("", f"{short_date(start)} – {full_date(end)}", start, end)


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
        Line(f"{WEEKDAYS[day.weekday()]} {short_date(day)}", total, round(total / longest * 100))
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
    sent_on = timezone.localtime(slot).date()
    rng = report_range(sent_on)
    base_url = (await MailSettings.aload()).base_url.rstrip("/")
    queued = 0
    async for user in _recipients(weekly_report=True):
        key = f"weekly-report:{user.pk}:{rng.start.isoformat()}"
        if await OutgoingMail.objects.filter(dedupe_key=key).aexists():
            continue
        # Day names and dates are written in the language of whoever gets the report.
        with translation.override(user.language):
            user_range = report_range(sent_on)
            report = await sync_to_async(build_weekly_report)(user, user_range)
        if report.is_empty:
            continue
        if not base_url:
            url = ""
        elif user.is_admin:
            query = urlencode({"from": rng.start.isoformat(), "to": rng.end.isoformat()})
            url = f"{base_url}{reverse('reports:overview')}?{query}"
        else:
            url = f"{base_url}{reverse('tracking:list')}"
        context = {"user": user, "report": report, "url": url, "duration_format": user.duration_format}
        await outbox.aqueue(
            OutgoingMail.Kind.WEEKLY_REPORT,
            user.email,
            fmt(_("Dein Wochenbericht %(range)s"), range=user_range.label),
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
            "datetime_format": datetime_format(entry.user.date_format),
        }
        await outbox.aqueue(
            OutgoingMail.Kind.TIMER_REMINDER,
            entry.user.email,
            _("Dein Timer läuft noch"),
            "timer_reminder",
            context,
            user=entry.user,
            dedupe_key=key,
        )
        queued += 1
    return queued


def overdue_invoices(now: datetime, days: int):
    """Invoices overdue for ``days`` days, but not much longer, whose status was checked with Lexware lately."""
    today = timezone.localdate(now)
    latest = today - timedelta(days=days)
    return (
        Invoice.objects.filter(
            status=Invoice.Status.OVERDUE,
            due_date__lte=latest,
            due_date__gte=latest - OVERDUE_CATCH_UP,
            status_synced_at__gte=now - OVERDUE_STATUS_MAX_AGE,
        )
        .select_related("customer")
        .order_by("due_date", "pk")
    )


async def queue_overdue_notices(now: datetime, app_settings: AppSettings) -> int:
    """One notice per invoice and due date: to the customer if wanted, and to every administrator."""
    config = await MailSettings.aload()
    to_customer = app_settings.overdue_notice == AppSettings.OverdueNotice.CUSTOMER
    admins = [user async for user in _recipients(role=User.Role.ADMIN)]
    queued = 0
    async for invoice in overdue_invoices(now, app_settings.overdue_notice_days):
        key = f"invoice-overdue:{invoice.pk}:{invoice.due_date.isoformat()}"
        context = {"invoice": invoice, "days_overdue": (timezone.localdate(now) - invoice.due_date).days}
        customer_email = invoice.customer.email if to_customer else ""
        number = invoice.voucher_number or _("ohne Nummer")
        if customer_email and not await OutgoingMail.objects.filter(dedupe_key=f"{key}:customer").aexists():
            await outbox.aqueue(
                OutgoingMail.Kind.INVOICE_OVERDUE,
                customer_email,
                fmt(_("Zahlungserinnerung zur Rechnung %(number)s"), number=number),
                "invoice_overdue_customer",
                context | {"sender_name": config.from_name},
                dedupe_key=f"{key}:customer",
            )
            queued += 1
        for admin in admins:
            admin_key = f"{key}:user:{admin.pk}"
            if await OutgoingMail.objects.filter(dedupe_key=admin_key).aexists():
                continue
            await outbox.aqueue(
                OutgoingMail.Kind.INVOICE_OVERDUE,
                admin.email,
                fmt(
                    _("Rechnung %(number)s von %(customer)s ist überfällig"),
                    number=number,
                    customer=invoice.customer.name,
                ),
                "invoice_overdue",
                context
                | {
                    "user": admin,
                    "customer_notified": bool(customer_email),
                    "customer_without_email": to_customer and not invoice.customer.email,
                    "date_format": date_format(admin.date_format),
                },
                user=admin,
                dedupe_key=admin_key,
            )
            queued += 1
    return queued


async def run_due(now: datetime) -> dict[str, int]:
    """Queue the reports, reminders and notices that are due. Returns how many of each were queued."""
    if not await outbox.ais_configured():
        return {}
    app_settings = await AppSettings.aload()
    queued = {}
    if slot := weekly_report_due(now, app_settings):
        queued["weekly report"] = await queue_weekly_reports(slot)
        await AppSettings.objects.filter(pk=1).aupdate(weekly_report_at=now)
    if app_settings.timer_reminder_hours:
        queued["timer reminder"] = await queue_timer_reminders(now, app_settings.timer_reminder_hours)
    if app_settings.overdue_notice != AppSettings.OverdueNotice.OFF:
        queued["overdue invoice"] = await queue_overdue_notices(now, app_settings)
    return queued
