from django.db import models

from core.models import TimeStampedModel


class Category(models.Model):
    """A label for grouping customers, maintained in LexTracker (Lexware contacts have none)."""

    name = models.CharField("Name", max_length=100, unique=True)

    class Meta:
        verbose_name = "Kategorie"
        verbose_name_plural = "Kategorien"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


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
    categories = models.ManyToManyField(Category, verbose_name="Kategorien", blank=True, related_name="customers")

    # Link to the contact in Lexware Office. Empty for customers created only here.
    lexware_id = models.UUIDField("Lexware-ID", unique=True, null=True, blank=True, editable=False)
    lexware_version = models.PositiveIntegerField("Lexware-Version", null=True, blank=True, editable=False)
    lexware_synced_at = models.DateTimeField("zuletzt synchronisiert", null=True, blank=True, editable=False)
    # The contact no longer comes back from the import (deleted in Lexware or no longer a customer).
    # The customer is kept, because time and invoices refer to it, and archived.
    lexware_deleted = models.BooleanField("in Lexware gelöscht", default=False, editable=False)

    class Meta:
        verbose_name = "Kunde"
        verbose_name_plural = "Kunden"
        ordering = ["name"]
        indexes = [models.Index(fields=["is_archived", "name"])]

    def __str__(self) -> str:
        return self.name
