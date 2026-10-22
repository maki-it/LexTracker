from django.db import models

from core.models import TimeStampedModel


class Customer(TimeStampedModel):
    name = models.CharField("Name", max_length=255)
    customer_number = models.CharField("Kundennummer", max_length=50, blank=True)
    email = models.EmailField("E-Mail", blank=True)
    phone = models.CharField("Telefon", max_length=50, blank=True)
    default_hourly_rate = models.DecimalField(
        "Standard-Stundensatz (netto)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    notes = models.TextField("Notizen", blank=True)
    is_archived = models.BooleanField("archiviert", default=False)

    # Link to the contact in Lexware Office. Empty for customers created only here.
    lexware_id = models.UUIDField("Lexware-ID", unique=True, null=True, blank=True, editable=False)
    lexware_version = models.PositiveIntegerField("Lexware-Version", null=True, blank=True, editable=False)
    lexware_synced_at = models.DateTimeField("zuletzt synchronisiert", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Kunde"
        verbose_name_plural = "Kunden"
        ordering = ["name"]
        indexes = [models.Index(fields=["is_archived", "name"])]

    def __str__(self) -> str:
        return self.name
