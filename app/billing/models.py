from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class BillingAgreement(TimeStampedModel):
    """How a customer pays for time. Without an agreement, time is billed by the hour."""

    class Kind(models.TextChoices):
        HOURLY = "hourly", _("nach Aufwand (Stundensatz)")
        RETAINER = "retainer", _("Retainer (Stundenkontingent zum Festpreis)")

    class Period(models.TextChoices):
        MONTH = "month", _("monatlich")
        QUARTER = "quarter", _("quartalsweise")
        YEAR = "year", _("jährlich")

    customer = models.ForeignKey(
        "customers.Customer", verbose_name=_("Kunde"), on_delete=models.CASCADE, related_name="billing_agreements"
    )
    kind = models.CharField(_("Modell"), max_length=20, choices=Kind, default=Kind.HOURLY)
    period = models.CharField(_("Abrechnungszeitraum"), max_length=20, choices=Period, default=Period.MONTH)
    included_hours = models.DecimalField(
        _("Enthaltene Stunden pro Zeitraum"), max_digits=8, decimal_places=2, null=True, blank=True
    )
    fixed_price = models.DecimalField(
        _("Festpreis pro Zeitraum (netto)"), max_digits=10, decimal_places=2, null=True, blank=True
    )
    overage_rate = models.DecimalField(
        _("Stundensatz für Mehrstunden (netto)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer lassen, um den normalen Stundensatz der Aufgabe, des Projekts oder Kunden zu verwenden."),
    )
    valid_from = models.DateField(_("gültig ab"))
    valid_until = models.DateField(_("gültig bis"), null=True, blank=True)

    class Meta:
        verbose_name = _("Abrechnungsvereinbarung")
        verbose_name_plural = _("Abrechnungsvereinbarungen")
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
            return _("%(hours)s h %(period)s für %(price)s €") % {
                "hours": self.included_hours,
                "period": self.get_period_display(),
                "price": self.fixed_price,
            }
        return self.get_kind_display()


class Invoice(TimeStampedModel):
    """An invoice in Lexware Office for a customer and period, created here or taken over from Lexware."""

    class Origin(models.TextChoices):
        APP = "app", _("LexTracker")
        LEXWARE = "lexware", _("Lexware Office")

    class Status(models.TextChoices):
        # The voucher statuses Lexware uses for invoices, plus "deleted" for drafts deleted there.
        DRAFT = "draft", _("Entwurf")
        OPEN = "open", _("Offen")
        OVERDUE = "overdue", _("Überfällig")
        TRANSFERRED = "transferred", _("Überweisung läuft")
        SEPADEBIT = "sepadebit", _("Lastschrift")
        PAID = "paid", _("Bezahlt")
        VOIDED = "voided", _("Storniert")
        DELETED = "deleted", _("In Lexware gelöscht")

    customer = models.ForeignKey(
        "customers.Customer", verbose_name=_("Kunde"), on_delete=models.PROTECT, related_name="invoices"
    )
    period_start = models.DateField(_("Leistungszeitraum von"))
    period_end = models.DateField(_("Leistungszeitraum bis"))
    total_net = models.DecimalField(_("Summe netto"), max_digits=12, decimal_places=2)
    lexware_id = models.UUIDField(_("Lexware-ID"), unique=True, null=True, blank=True, editable=False)
    # Invoices written directly in Lexware are taken over by billing.sync. They have no time entries.
    origin = models.CharField(_("erstellt in"), max_length=20, choices=Origin, default=Origin.APP)
    voucher_date = models.DateField(_("Rechnungsdatum"), null=True, blank=True)
    # Kept up to date from Lexware by billing.sync.
    status = models.CharField(_("Status"), max_length=20, choices=Status, default=Status.DRAFT)
    voucher_number = models.CharField(_("Rechnungsnummer"), max_length=50, blank=True)
    due_date = models.DateField(_("fällig am"), null=True, blank=True)
    # Gross, as Lexware's voucher list reports it; None until the first sync.
    open_amount = models.DecimalField(_("offener Betrag"), max_digits=12, decimal_places=2, null=True, blank=True)
    status_synced_at = models.DateTimeField(_("Status abgeglichen"), null=True, blank=True, editable=False)
    # The quotation (Angebot) the invoice follows up on, as Lexware shows it under "Referenz".
    quotation_number = models.CharField(_("Angebot"), max_length=50, blank=True)

    class Meta:
        verbose_name = _("Rechnung")
        verbose_name_plural = _("Rechnungen")
        ordering = ["-period_end", "-created_at"]
        indexes = [models.Index(fields=["status"])]

    def __str__(self) -> str:
        if self.period_start == self.period_end:  # Lexware's single service or delivery date.
            return f"{self.customer} {self.period_start:%d.%m.%Y}"
        return f"{self.customer} {self.period_start:%d.%m.%Y}–{self.period_end:%d.%m.%Y}"

    @property
    def lexware_url(self) -> str:
        if not self.lexware_id or self.status == self.Status.DELETED:
            return ""
        action = "edit" if self.status == self.Status.DRAFT else "view"
        return f"https://app.lexware.de/permalink/invoices/{action}/{self.lexware_id}"

    @property
    def shows_due_date(self) -> bool:
        """Whether the due date is worth showing: only while the invoice still waits for its payment."""
        return bool(self.due_date) and self.status in (self.Status.OPEN, self.Status.OVERDUE)

    @property
    def days_overdue(self) -> int:
        """Days since the due date, 0 if the invoice is not overdue."""
        if self.status != self.Status.OVERDUE or not self.due_date:
            return 0
        return max((timezone.localdate() - self.due_date).days, 0)

    @property
    def was_draft_when_deleted(self) -> bool:
        """Whether the invoice was deleted in Lexware as a draft: a draft has no voucher number yet."""
        return self.status == self.Status.DELETED and not self.voucher_number

    @property
    def status_label(self) -> str:
        """The status as shown in the list; a deleted draft says it was a draft."""
        if self.was_draft_when_deleted:
            return _("Entwurf gelöscht")
        return self.get_status_display()

    @property
    def status_badge(self) -> str:
        """The badge class that goes with the status."""
        return {
            self.Status.DRAFT: "",
            self.Status.OPEN: "badge-primary",
            self.Status.TRANSFERRED: "badge-primary",
            self.Status.SEPADEBIT: "badge-primary",
            self.Status.OVERDUE: "badge-danger",
            self.Status.PAID: "badge-success",
            self.Status.VOIDED: "badge-warning",
            self.Status.DELETED: "",  # Not the warning color of a voided invoice.
        }.get(self.status, "")
