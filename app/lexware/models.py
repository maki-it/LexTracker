from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel, UUIDModel


class LexwareConnection(models.Model):
    """The Lexware Office API key, entered on the settings page or during setup. There is only one row.

    The key is stored encrypted (see ``lexware.credentials``) and never shown again; the page shows
    only its last characters.
    """

    encrypted_api_key = models.TextField(blank=True, editable=False)
    key_suffix = models.CharField(_("Ende des Schlüssels"), max_length=4, blank=True, editable=False)
    company_name = models.CharField(_("Lexware-Konto"), max_length=200, blank=True, editable=False)
    verified_at = models.DateTimeField(_("zuletzt geprüft"), null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(_("geändert"), null=True, blank=True, editable=False)
    # The secret part of the webhook address (see ``lexware.webhooks``). Empty while webhooks are off.
    webhook_token = models.CharField(max_length=64, blank=True, editable=False)
    # Lexware's public key (PEM) for the signature of its calls. Empty: calls are not checked for a signature.
    webhook_public_key = models.TextField(blank=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = _("Lexware-Verbindung")

    def __str__(self) -> str:
        return "Lexware-Verbindung"

    @classmethod
    async def aload(cls) -> LexwareConnection:
        return (await cls.objects.aget_or_create(pk=1))[0]


class WebhookSubscription(TimeStampedModel):
    """An event subscription that this app created at Lexware: Lexware calls our webhook address for this event."""

    event_type = models.CharField(_("Ereignis"), max_length=60, unique=True)
    subscription_id = models.UUIDField(_("Abo-ID bei Lexware"), null=True, blank=True)

    class Meta:
        verbose_name = _("Webhook-Abo")
        verbose_name_plural = _("Webhook-Abos")
        ordering = ["event_type"]

    def __str__(self) -> str:
        return self.event_type


class WebhookEvent(UUIDModel):
    """A call from Lexware that says something changed. Only the type and the resource are kept.

    The call itself is never trusted for its content: it only makes the scheduler look at Lexware sooner
    (see ``lexware.webhooks``), so a forged call cannot change any data.
    """

    event_type = models.CharField(max_length=60)
    resource_id = models.UUIDField(null=True, blank=True)
    received_at = models.DateTimeField(auto_now_add=True)
    # Set when the scheduler has taken it up.
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["processed_at", "received_at"])]
