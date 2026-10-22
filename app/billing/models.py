from django.db import models

from core.models import TimeStampedModel


class BillingAgreement(TimeStampedModel):
    """How a customer pays for time. Without an agreement, time is billed by the hour."""

    class Kind(models.TextChoices):
        HOURLY = "hourly", "nach Aufwand (Stundensatz)"
        RETAINER = "retainer", "Retainer (Stundenkontingent zum Festpreis)"

    class Period(models.TextChoices):
        MONTH = "month", "monatlich"
        QUARTER = "quarter", "quartalsweise"
        YEAR = "year", "jährlich"

    customer = models.ForeignKey(
        "customers.Customer", verbose_name="Kunde", on_delete=models.CASCADE, related_name="billing_agreements"
    )
    kind = models.CharField("Modell", max_length=20, choices=Kind, default=Kind.HOURLY)
    period = models.CharField("Abrechnungszeitraum", max_length=20, choices=Period, default=Period.MONTH)
    included_hours = models.DecimalField(
        "Enthaltene Stunden pro Zeitraum", max_digits=8, decimal_places=2, null=True, blank=True
    )
    fixed_price = models.DecimalField(
        "Festpreis pro Zeitraum (netto)", max_digits=10, decimal_places=2, null=True, blank=True
    )
    overage_rate = models.DecimalField(
        "Stundensatz für Mehrstunden (netto)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leer lassen, um den normalen Stundensatz der Aufgabe, des Projekts oder Kunden zu verwenden.",
    )
    valid_from = models.DateField("gültig ab")
    valid_until = models.DateField("gültig bis", null=True, blank=True)

    class Meta:
        verbose_name = "Abrechnungsvereinbarung"
        verbose_name_plural = "Abrechnungsvereinbarungen"
        ordering = ["customer", "-valid_from"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(kind="retainer")
                | models.Q(included_hours__isnull=False, fixed_price__isnull=False),
                name="retainer_has_hours_and_price",
            ),
        ]

    def __str__(self) -> str:
        if self.kind == self.Kind.RETAINER:
            return f"{self.included_hours} h {self.get_period_display()} für {self.fixed_price} €"
        return self.get_kind_display()


class Invoice(TimeStampedModel):
    """An invoice created in Lexware Office for a customer and period."""

    customer = models.ForeignKey(
        "customers.Customer", verbose_name="Kunde", on_delete=models.PROTECT, related_name="invoices"
    )
    period_start = models.DateField("Leistungszeitraum von")
    period_end = models.DateField("Leistungszeitraum bis")
    total_net = models.DecimalField("Summe netto", max_digits=12, decimal_places=2)
    lexware_id = models.UUIDField("Lexware-ID", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "Rechnung"
        verbose_name_plural = "Rechnungen"
        ordering = ["-period_end", "-created_at"]

    def __str__(self) -> str:
        return f"{self.customer} {self.period_start:%d.%m.%Y}–{self.period_end:%d.%m.%Y}"

    @property
    def lexware_url(self) -> str:
        return f"https://app.lexware.de/permalink/invoices/edit/{self.lexware_id}" if self.lexware_id else ""
