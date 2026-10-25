from django.db import models
from django.utils.translation import gettext_lazy as _


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

    class Meta:
        verbose_name = verbose_name_plural = _("Lexware-Verbindung")

    def __str__(self) -> str:
        return "Lexware-Verbindung"

    @classmethod
    async def aload(cls) -> LexwareConnection:
        return (await cls.objects.aget_or_create(pk=1))[0]
