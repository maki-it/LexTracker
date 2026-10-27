"""Send push notifications to the devices of a user.

``inbox.service.anotify`` calls ``apush_message`` for every message that is new, and ``push.jobs`` keeps the running
timer on the devices that asked for it. Neither may fail because a push service is down, so nothing here raises.
"""

import asyncio
import logging

import httpx
from cryptography.hazmat.primitives.asymmetric import ec
from django.templatetags.static import static
from django.utils import timezone

from accounts.models import User
from core import branding, crypto
from core.models import AppSettings
from push import webpush
from push.models import PushKeys, PushSubscription
from push.topics import Topic, topic_of

logger = logging.getLogger(__name__)

KEY_PURPOSE = "push-vapid"
# The push service wants a contact for the sender. Without a public https address there is none to give.
FALLBACK_SUBJECT = "mailto:push@lextracker.invalid"


async def aload_keys() -> tuple[ec.EllipticCurvePrivateKey, str]:
    """The private key and the public key (base64url). Made on first use."""
    keys = await PushKeys.objects.filter(pk=1).afirst()
    if keys is not None:
        if (pem := crypto.decrypt(keys.encrypted_private_key, KEY_PURPOSE)) is not None:
            return webpush.load_private(pem), keys.public_key
        # The secret key changed: the old pair is lost, and with it every subscription made for it.
        logger.warning("The push key cannot be decrypted anymore; making a new one. Devices have to subscribe again.")
        await PushSubscription.objects.all().adelete()
        await keys.adelete()
    private = webpush.new_private_key()
    public = webpush.b64encode(webpush.public_bytes(private))
    values = {"encrypted_private_key": crypto.encrypt(webpush.private_pem(private), KEY_PURPOSE), "public_key": public}
    # Two requests at once: the first one wins and both use its key.
    keys, created = await PushKeys.objects.aget_or_create(pk=1, defaults=values)
    if created:
        return private, public
    return await aload_keys()


async def asubject() -> str:
    url = await AppSettings.aurl()
    return url if url.startswith("https://") else FALLBACK_SUBJECT


async def aicon() -> str:
    """The picture on a notification: the uploaded logo if it is a raster image, else the built-in icon."""
    brand = await branding.aload()
    if brand.logo_url and brand.logo_type != "image/svg+xml":
        return brand.logo_url
    return static("img/icon-192.png")


async def apush(subscriptions: list[PushSubscription], message: dict, *, ttl: int = webpush.DEFAULT_TTL) -> int:
    """Send the message to these devices. Devices that are gone are deleted. Returns how many took it."""
    if not subscriptions:
        return 0
    private, _ = await aload_keys()
    subject = await asubject()
    message = {"icon": await aicon(), **message}
    async with httpx.AsyncClient(timeout=webpush.TIMEOUT) as client:
        results = await asyncio.gather(
            *(_send_one(client, sub, message, private, subject, ttl) for sub in subscriptions)
        )
    delivered = [sub.pk for sub, ok in zip(subscriptions, results, strict=True) if ok]
    if delivered:
        await PushSubscription.objects.filter(pk__in=delivered).aupdate(last_used_at=timezone.now())
    return len(delivered)


async def _send_one(client, sub: PushSubscription, message: dict, private, subject: str, ttl: int) -> bool:
    try:
        await webpush.send(
            client, sub.endpoint, sub.p256dh, sub.auth, message, private_key=private, subject=subject, ttl=ttl
        )
    except webpush.PushGone:
        await PushSubscription.objects.filter(pk=sub.pk).adelete()
    except webpush.PushError as error:
        logger.warning("Push to %r of %s failed: %s", sub.name, sub.user_id, error)
    else:
        return True
    return False


async def asubscriptions(user: User, topic: Topic) -> list[PushSubscription]:
    """The devices of the user that subscribed to the topic (the topics are a list in a JSON column)."""
    return [sub async for sub in user.push_subscriptions.all() if topic in sub.topics]


async def apush_message(user: User, message) -> None:
    """Push an inbox message to the devices that subscribed to its topic. Never raises."""
    try:
        if user.is_customer or (topic := topic_of(message.kind, message.level)) is None:
            return
        await apush(
            await asubscriptions(user, topic),
            {
                "kind": "message",
                "title": message.title,
                "body": message.body[:300],
                "url": message.url or "/",
                "tag": f"message:{message.pk}",
            },
        )
    except Exception:
        logger.exception("Could not push a message")
