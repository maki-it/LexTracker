"""Let Lexware Office tell us about changes (webhooks) instead of asking again and again.

Lexware calls an address of this app whenever a contact or an invoice changes. The call is only a hint: it
says which kind of thing changed, and the scheduler then runs the usual import or status sync for it
(``core.scheduler.process_webhooks``). Nothing in the call is stored as data, so a forged call can at worst
make the scheduler look at Lexware a little early. The address also contains a secret, so only Lexware, which
was given it when the subscription was created, can reach the endpoint at all.

The regular sync interval stays as a safety net for calls that never arrive.
"""

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _

from core.ids import parse_uuid
from lexware.client import LexwareClient, LexwareError
from lexware.models import LexwareConnection, WebhookEvent, WebhookSubscription
from mailer.models import MailSettings

logger = logging.getLogger(__name__)

# Which sync (``core.scheduler.JOBS`` key) each event is a reason for.
EVENT_AREAS = {
    "contact.created": "customers",
    "contact.changed": "customers",
    "contact.deleted": "customers",
    "invoice.created": "invoices",
    "invoice.changed": "invoices",
    "invoice.status.changed": "invoices",
    "invoice.deleted": "invoices",
    "payment.changed": "invoices",
}
EVENT_TYPE_MAX_LENGTH = 60
# Processed events are kept this long, so the settings page can show when Lexware last called.
KEEP_PROCESSED = timedelta(days=7)
# A call that no sync has taken up by then is dropped (the sync interval catches up).
KEEP_PENDING = timedelta(days=2)


def callback_path(token: str) -> str:
    return reverse("webhooks:lexware", args=[token])


async def aensure_token() -> str:
    connection = await LexwareConnection.aload()
    if not connection.webhook_token:
        connection.webhook_token = secrets.token_urlsafe(32)
        await LexwareConnection.objects.filter(pk=1).aupdate(webhook_token=connection.webhook_token)
    return connection.webhook_token


async def avalid_token(token: str) -> bool:
    stored = (await LexwareConnection.aload()).webhook_token
    return bool(stored) and secrets.compare_digest(stored.encode(), token.encode())


async def arecord(event_type: str, resource_id: UUID | None) -> bool:
    """Note a call from Lexware for the scheduler. False if it asks for nothing or the same thing is already waiting."""
    event_type = event_type[:EVENT_TYPE_MAX_LENGTH]
    waiting = WebhookEvent.objects.filter(event_type=event_type, resource_id=resource_id, processed_at__isnull=True)
    if await waiting.aexists():
        return False
    # Events that no sync is interested in are kept as done, so the settings page can still show the call.
    done = None if event_type in EVENT_AREAS else timezone.now()
    await WebhookEvent.objects.acreate(event_type=event_type, resource_id=resource_id, processed_at=done)
    return done is None


async def aclaim(area: str) -> list[UUID]:
    """Take up the waiting calls that ask for this sync (a ``core.scheduler.JOBS`` key) and return their IDs.

    Calls that arrive from now on stay waiting, so a change during a sync is not lost.
    """
    types = [event_type for event_type, wanted in EVENT_AREAS.items() if wanted == area]
    waiting = [
        pk
        async for pk in WebhookEvent.objects.filter(event_type__in=types, processed_at__isnull=True).values_list(
            "pk", flat=True
        )
    ]
    if waiting:
        await WebhookEvent.objects.filter(pk__in=waiting).aupdate(processed_at=timezone.now())
    return waiting


async def arelease(claimed: list[UUID]) -> None:
    """Put claimed calls back, because the sync failed and has to be tried again."""
    await WebhookEvent.objects.filter(pk__in=claimed).aupdate(processed_at=None)


async def aprune(now: datetime | None = None) -> int:
    now = now or timezone.now()
    done = WebhookEvent.objects.filter(processed_at__lt=now - KEEP_PROCESSED)
    old = WebhookEvent.objects.filter(processed_at__isnull=True, received_at__lt=now - KEEP_PENDING)
    return (await done.adelete())[0] + (await old.adelete())[0]


@dataclass
class WebhookStatus:
    # Where Lexware is to call, and why we cannot ask it to yet.
    callback_url: str = ""
    problem: str = ""
    subscriptions: list[WebhookSubscription] = field(default_factory=list)
    last_event_at: datetime | None = None

    @property
    def active(self) -> bool:
        return bool(self.subscriptions)


async def abase_url(request_origin: str = "") -> str:
    """The address the app is reachable at from outside: the one set for e-mails, else the one of this request."""
    return ((await MailSettings.aload()).base_url or request_origin).rstrip("/")


async def astatus(request_origin: str = "") -> WebhookStatus:
    status = WebhookStatus(subscriptions=[s async for s in WebhookSubscription.objects.all()])
    base_url = await abase_url(request_origin)
    if not base_url.startswith("https://"):
        status.problem = _(
            "Lexware ruft nur Adressen mit HTTPS auf. Trage unter „E-Mail“ die öffentliche Adresse der App "
            "ein, zum Beispiel https://zeit.example.de."
        )
    elif token := (await LexwareConnection.aload()).webhook_token:
        status.callback_url = base_url + callback_path(token)
    last = await WebhookEvent.objects.order_by("-received_at").values_list("received_at", flat=True).afirst()
    status.last_event_at = last
    return status


@dataclass
class EnableResult:
    subscribed: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)


async def aenable(client: LexwareClient, base_url: str) -> EnableResult:
    """Subscribe to every event of ``EVENT_AREAS``. Events that Lexware refuses are reported, not fatal."""
    await adisable(client)
    callback_url = base_url.rstrip("/") + callback_path(await aensure_token())
    result = EnableResult()
    for event_type in EVENT_AREAS:
        try:
            subscription_id = await client.create_event_subscription(event_type, callback_url)
        except LexwareError as exc:
            result.failed[event_type] = str(exc)
            continue
        await WebhookSubscription.objects.aupdate_or_create(
            event_type=event_type, defaults={"subscription_id": subscription_id}
        )
        result.subscribed.append(event_type)
    if not result.subscribed:
        # Nothing worked, so do not leave a secret address behind.
        await LexwareConnection.objects.filter(pk=1).aupdate(webhook_token="")
    return result


async def adisable(client: LexwareClient) -> None:
    """Cancel the subscriptions at Lexware and make the address useless.

    Besides the ones we know, those that call our address are removed, in case a record got lost.
    """
    token = (await LexwareConnection.aload()).webhook_token
    known = {s.subscription_id async for s in WebhookSubscription.objects.exclude(subscription_id=None)}
    if token:
        for subscription in await client.list_event_subscriptions():
            found = parse_uuid(subscription.get("subscriptionId") or subscription.get("id"))
            if found and token in str(subscription.get("callbackUrl", "")):
                known.add(found)
    for subscription_id in known:
        await client.delete_event_subscription(subscription_id)
    await WebhookSubscription.objects.all().adelete()
    await LexwareConnection.objects.filter(pk=1).aupdate(webhook_token="")
