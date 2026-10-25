"""Create, resolve and clean up messages.

Anything that wants to tell users something calls ``anotify``. The scheduler runs in its own process, so
the database is the only way a message reaches the web app; the bell and the messages page read it from there.
"""

import enum
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from django.db import IntegrityError
from django.db.models import Count, F, Max, Q, QuerySet
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.functional import Promise

from accounts.models import User
from inbox.levels import Level
from inbox.models import Message
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail

logger = logging.getLogger(__name__)

# How long read messages are kept, by level. Unread debug and info messages go after twice as long;
# unread warnings and critical messages stay until they are read.
KEEP_READ = {
    Level.DEBUG: timedelta(days=3),
    Level.INFO: timedelta(days=30),
    Level.WARNING: timedelta(days=90),
    Level.CRITICAL: timedelta(days=365),
}
# No user keeps more than this; the oldest debug and info messages go first.
KEEP_MAX = 1000


# What a message says: a plain string, a lazy translation, or a function that builds the text. The last two are
# turned into text once per recipient, in their language (see ``User.language``).
Text = str | Promise | Callable[[], str]


def _text(text: Text) -> str:
    return text() if callable(text) and not isinstance(text, Promise) else str(text)


class Audience(enum.Enum):
    ADMINS = "admins"
    # Administrators and employees, not customers.
    STAFF = "staff"


def recipients(to: User | Audience) -> QuerySet[User]:
    users = User.objects.filter(is_active=True)
    if isinstance(to, User):
        return users.filter(pk=to.pk)
    if to is Audience.ADMINS:
        return users.filter(role=User.Role.ADMIN)
    return users.exclude(role=User.Role.CUSTOMER)


def visible_to(user: User) -> QuerySet[Message]:
    """The messages the user's settings let them see. Critical ones always pass: nothing ranks above them."""
    return Message.objects.filter(user=user, level__gte=user.message_level)


async def anotify(
    level: int,
    kind: str,
    title: Text,
    body: Text = "",
    *,
    url: str = "",
    to: User | Audience = Audience.ADMINS,
    dedupe_key: str = "",
    escalate_after: int = 0,
) -> list[Message]:
    """Tell the users. Returns the message each of them got.

    ``title`` and ``body`` can be lazy translations or functions, so every recipient gets them in their language.
    ``url`` is a path in the app. Whoever has an unread message with the same ``dedupe_key`` gets it updated
    (counted up) instead of another one. With ``escalate_after`` the message becomes critical once it has repeated that
    often. A message that is new, or has become more important, is also e-mailed to those who asked for that.
    """
    if url and not (url.startswith("/") and not url.startswith("//")):
        raise ValueError(f"A message links to a path in the app, not to {url!r}")
    result = []
    async for user in recipients(to):
        message, notable = await _deliver(user, level, kind, title, body, url, dedupe_key, escalate_after)
        result.append(message)
        if notable:
            await _mail(user, message)
    return result


async def _deliver(
    user: User, level: int, kind: str, title: Text, body: Text, url: str, dedupe_key: str, escalate_after: int
) -> tuple[Message, bool]:
    """Store the message for the user. The second value tells whether it is new or has become more important."""
    with translation.override(user.language):
        fields = {"title": _text(title)[:200], "body": _text(body), "url": url}
    for _ in range(2):
        if dedupe_key:
            unread = Message.objects.filter(user=user, dedupe_key=dedupe_key, read_at__isnull=True)
            if existing := await unread.afirst():
                return await _repeat(existing, level, fields, escalate_after)
        try:
            message = await Message.objects.acreate(
                user=user, level=level, kind=kind, dedupe_key=dedupe_key, last_at=timezone.now(), **fields
            )
        except IntegrityError:
            # The web app or the scheduler stored the same message a moment ago: update that one.
            continue
        return message, True
    raise RuntimeError("Could not store the message")  # pragma: no cover


async def _repeat(message: Message, level: int, fields: dict, escalate_after: int) -> tuple[Message, bool]:
    previous = message.level
    await Message.objects.filter(pk=message.pk).aupdate(
        count=F("count") + 1, last_at=timezone.now(), level=max(previous, level), **fields
    )
    await message.arefresh_from_db()
    if escalate_after and message.count >= escalate_after and message.level < Level.CRITICAL:
        message.level = Level.CRITICAL
        await message.asave(update_fields=["level"])
    return message, message.level > previous


async def aresolve(dedupe_key: str, *, user: User | None = None) -> int:
    """Mark the unread messages with this key as read, e.g. once the backup works again. Returns how many."""
    unread = Message.objects.filter(dedupe_key=dedupe_key, read_at__isnull=True)
    if user is not None:
        unread = unread.filter(user=user)
    return await unread.aupdate(read_at=timezone.now())


async def _mail(user: User, message: Message) -> None:
    if not user.email or user.message_email_level == 0 or message.level < user.message_email_level:
        return
    config = await MailSettings.aload()
    if not config.is_configured:
        return
    base_url = config.base_url.rstrip("/")
    with translation.override(user.language):
        subject = f"{message.get_level_display()}: {message.title}"
    await outbox.aqueue(
        OutgoingMail.Kind.NOTIFICATION,
        user.email,
        subject,
        "notification",
        {"user": user, "message": message, "url": f"{base_url}{reverse('inbox:panel')}" if base_url else ""},
        user=user,
        # A message that becomes critical later is mailed again, one that merely repeats is not.
        dedupe_key=f"message:{message.pk}:{message.level}",
    )


async def summary(user: User) -> dict:
    """What the bell and the banner show: how many messages are unread, the highest level and the critical ones."""
    unread = visible_to(user).filter(read_at__isnull=True)
    result = await unread.aaggregate(count=Count("pk"), top=Max("level"))
    # The banner on every page: the newest critical message that is still unread.
    critical = unread.filter(level=Level.CRITICAL)
    result["critical"] = await critical.afirst() if result["top"] == Level.CRITICAL else None
    result["critical_count"] = await critical.acount() if result["critical"] else 0
    return result


async def prune(now: datetime | None = None) -> int:
    """Delete old messages by the rules above. Returns how many."""
    now = now or timezone.now()
    deleted = 0
    for level, keep in KEEP_READ.items():
        old = Q(read_at__lt=now - keep)
        if level <= Level.INFO:
            old |= Q(read_at__isnull=True, last_at__lt=now - 2 * keep)
        deleted += (await Message.objects.filter(old, level=level).adelete())[0]
    # The cap: of the users above it, the oldest messages of the lowest levels go.
    crowded = Message.objects.order_by().values("user").annotate(n=Count("pk")).filter(n__gt=KEEP_MAX)
    async for row in crowded:
        oldest = Message.objects.filter(user_id=row["user"]).order_by("level", "last_at", "id")
        surplus = [pk async for pk in oldest.values_list("pk", flat=True)[: row["n"] - KEEP_MAX]]
        deleted += (await Message.objects.filter(pk__in=surplus).adelete())[0]
    if deleted:
        logger.info("Deleted %s old message%s", deleted, "" if deleted == 1 else "s")
    return deleted
