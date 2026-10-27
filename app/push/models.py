import hashlib

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel
from push.topics import default_topics


class PushKeys(models.Model):
    """The key pair that identifies this app to the push services of the browsers (VAPID). There is only one row.

    It is made on first use. The private key is stored encrypted (see ``core.crypto``). A new pair, e.g. after the
    secret key was changed, makes every subscription useless, so those are deleted and the devices subscribe again.
    """

    encrypted_private_key = models.TextField(editable=False)
    # The public key as the browser wants it: the uncompressed point, base64url.
    public_key = models.CharField(max_length=100, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = _("Push-Schlüssel")

    def __str__(self) -> str:
        return "Push-Schlüssel"


class PushSubscription(UUIDModel):
    """A browser on one device that wants push notifications for a user (the ``PushSubscription`` of the browser)."""

    user = models.ForeignKey(
        "accounts.User", verbose_name=_("Benutzer"), on_delete=models.CASCADE, related_name="push_subscriptions"
    )
    # Where the push service takes the notification, and the keys that only this browser can read it with.
    endpoint = models.CharField(max_length=2000, unique=True, editable=False)
    p256dh = models.CharField(max_length=200, editable=False)
    auth = models.CharField(max_length=100, editable=False)
    name = models.CharField(_("Name"), max_length=100)
    # What this device wants to be told about, values of ``push.topics.Topic``.
    topics = models.JSONField(_("Themen"), default=default_topics)
    created_at = models.DateTimeField(_("hinzugefügt"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("zuletzt zugestellt"), null=True, blank=True, editable=False)
    # The time entry whose running timer this device shows right now (see ``push.jobs``). No foreign key: the entry
    # is deleted when it ran for a few seconds only, and the device still has to be told to drop the notification.
    timer_shown = models.UUIDField(null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("Push-Gerät")
        verbose_name_plural = _("Push-Geräte")
        ordering = ["created_at"]

    def __str__(self) -> str:
        return self.name

    @property
    def endpoint_hash(self) -> str:
        """Lets the page recognise this browser's subscription without putting the address into the page."""
        return hashlib.sha256(self.endpoint.encode()).hexdigest()
