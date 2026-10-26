"""Tell users about reminders that have become due: in the bell and by e-mail, as set on each reminder."""

import logging
from datetime import datetime

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.i18n import datetime_format, fmt
from inbox.levels import Level
from inbox.service import anotify
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail
from reminders.models import Reminder

logger = logging.getLogger(__name__)

KIND = "reminder.due"
# How much of the notes the message in the bell shows.
NOTES_PREVIEW = 300


def _body(reminder: Reminder) -> str:
    return "\n".join(part for part in (reminder.subject, reminder.notes[:NOTES_PREVIEW].strip()) if part)


async def _queue_mail(reminder: Reminder, base_url: str) -> None:
    user = reminder.user
    await outbox.aqueue(
        OutgoingMail.Kind.REMINDER,
        user.email,
        fmt(_("Erinnerung: %(title)s"), title=reminder.title),
        "reminder",
        {
            "user": user,
            "reminder": reminder,
            "url": f"{base_url}{reverse('reminders:list')}" if base_url else "",
            "datetime_format": datetime_format(user.date_format),
        },
        user=user,
        dedupe_key=f"reminder:{reminder.pk}:{reminder.due_at.isoformat()}",
    )


async def notify_due(now: datetime) -> int:
    """Announce the reminders that are due and not done, once each. Returns how many were announced.

    A reminder that fell due while the scheduler was not running is announced with the next run.
    """
    config = await MailSettings.aload()
    base_url = config.base_url.rstrip("/")
    due = (
        Reminder.objects.filter(due_at__lte=now, notified_at__isnull=True, done_at__isnull=True, user__is_active=True)
        .select_related("user", "customer", "project__customer")
        .order_by("due_at")
    )
    told = 0
    async for reminder in due:
        # Claim it first, so that two runs at once do not both announce it.
        if not await Reminder.objects.filter(pk=reminder.pk, notified_at__isnull=True).aupdate(notified_at=now):
            continue
        try:
            if reminder.notify_bell:
                await anotify(
                    Level.INFO,
                    KIND,
                    reminder.title,
                    _body(reminder),
                    url=reverse("reminders:list"),
                    to=reminder.user,
                    dedupe_key=f"reminder:{reminder.pk}",
                    # The e-mail below is the reminder's own, not the one for messages.
                    mail=False,
                )
            if reminder.notify_email and config.is_configured and reminder.user.email:
                await _queue_mail(reminder, base_url)
        except Exception:
            # Try again with the next run instead of losing the reminder.
            logger.exception("Could not announce reminder %s", reminder.pk)
            await Reminder.objects.filter(pk=reminder.pk).aupdate(notified_at=None)
            continue
        told += 1
    return told


async def run_due(now: datetime) -> dict[str, int]:
    return {"reminder": await notify_due(now)}
