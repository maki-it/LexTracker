"""Messages the scheduler creates for what is going on right now: a timer that runs for hours, an overdue invoice."""

import functools
from datetime import datetime, timedelta

from django.template.defaultfilters import floatformat
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from accounts.models import User
from billing.models import Invoice
from core.i18n import fmt, full_date
from core.models import AppSettings
from inbox.levels import Level
from inbox.models import Message
from inbox.service import anotify, aresolve
from tracking.models import TimeEntry

KIND = "timer.long"
OVERDUE_KIND = "invoice.overdue"
# Invoices that were overdue for longer than this are not announced, so a new installation or a first sync does not
# flood the bell with old invoices. The same limit as for the notices by e-mail (``mailer.jobs``).
OVERDUE_CATCH_UP = timedelta(days=7)
# The status of an invoice is only trusted for this long after the last time Lexware was asked.
OVERDUE_STATUS_MAX_AGE = timedelta(days=1)


def hours_text(running_for: timedelta):
    """ "3 Stunden", as a text that is translated for each reader."""
    hours = int(running_for.total_seconds() // 3600)
    return fmt(ngettext_lazy("%(count)d Stunde", "%(count)d Stunden", hours), count=hours)


async def notify_long_timers(now: datetime, hours: int) -> int:
    """Warn whoever has had a timer running for ``hours``, once per timer, and clear the warning once it stops.

    This does not depend on e-mail: the weekly mail reminder (``mailer.jobs``) is a separate thing.
    """
    running = (
        TimeEntry.objects.filter(ended_at__isnull=True, started_at__lte=now - timedelta(hours=hours))
        .exclude(user__role=User.Role.CUSTOMER)
        .select_related("user", "task", "task__project", "task__project__customer")
        .order_by("started_at")
    )
    told = 0
    keys = set()
    async for entry in running:
        key = f"timer:{entry.pk}"
        keys.add(key)
        # Only once, however long it keeps running (and even if the warning was read or deleted already).
        if await Message.objects.filter(dedupe_key=key).aexists():
            continue
        project = entry.task.project
        await anotify(
            Level.WARNING,
            KIND,
            fmt(_("Dein Timer läuft schon seit %(duration)s"), duration=hours_text(now - entry.started_at)),
            f"{project.customer.name} · {project.name} · {entry.task.name}",
            url=reverse("core:dashboard"),
            to=entry.user,
            dedupe_key=key,
        )
        told += 1
    # A timer that was stopped since needs no warning anymore.
    open_keys = {
        key
        async for key in Message.objects.filter(kind=KIND, read_at__isnull=True).values_list("dedupe_key", flat=True)
    }
    for key in open_keys - keys:
        await aresolve(key)
    return told


def _overdue_body(invoice: Invoice) -> str:
    """Due date and open amount, in the language and number format of whoever reads it."""
    text = fmt(_("Fällig am %(date)s"), date=full_date(invoice.due_date))
    if invoice.open_amount is None:
        return str(text)
    amount = floatformat(invoice.open_amount, "2g")
    return str(fmt(_("%(due)s, offen: %(amount)s €"), due=text, amount=amount))


async def notify_overdue_invoices(now: datetime) -> int:
    """Tell the administrators about each invoice that has become overdue, once per invoice and due date.

    The message clears itself when the invoice is not overdue anymore, e.g. because it was paid.
    """
    today = timezone.localdate(now)
    overdue = Invoice.objects.filter(status=Invoice.Status.OVERDUE, due_date__isnull=False)
    new = (
        overdue.filter(due_date__lt=today, due_date__gte=today - OVERDUE_CATCH_UP)
        .filter(status_synced_at__gte=now - OVERDUE_STATUS_MAX_AGE)
        .select_related("customer")
        .order_by("due_date", "pk")
    )
    told = 0
    async for invoice in new:
        key = f"invoice-overdue:{invoice.pk}:{invoice.due_date.isoformat()}"
        # Only once, even if the message was read or deleted already.
        if await Message.objects.filter(dedupe_key=key).aexists():
            continue
        number = invoice.voucher_number or _("ohne Nummer")
        await anotify(
            Level.WARNING,
            OVERDUE_KIND,
            fmt(
                _("Rechnung %(number)s von %(customer)s ist überfällig"), number=number, customer=invoice.customer.name
            ),
            functools.partial(_overdue_body, invoice),
            url=f"{reverse('billing:invoices')}?status=overdue",
            dedupe_key=key,
        )
        told += 1
    # An invoice that was paid since needs no message anymore.
    still = {f"invoice-overdue:{pk}:{due.isoformat()}" async for pk, due in overdue.values_list("pk", "due_date")}
    open_keys = {
        key
        async for key in Message.objects.filter(kind=OVERDUE_KIND, read_at__isnull=True).values_list(
            "dedupe_key", flat=True
        )
    }
    for key in open_keys - still:
        await aresolve(key)
    return told


async def run_due(now: datetime) -> dict[str, int]:
    app_settings = await AppSettings.aload()
    created = {"overdue invoice": await notify_overdue_invoices(now)}
    if app_settings.timer_reminder_hours:
        created["long timer"] = await notify_long_timers(now, app_settings.timer_reminder_hours)
    return created
