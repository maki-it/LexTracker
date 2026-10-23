from datetime import time

from django.core.validators import MinValueValidator
from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("erstellt", auto_now_add=True)
    updated_at = models.DateTimeField("geändert", auto_now=True)

    class Meta:
        abstract = True


class AppSettings(models.Model):
    """Settings for the whole app, edited on the settings page. There is only one row."""

    default_hourly_rate = models.DecimalField(
        "Standard-Stundensatz (netto)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Gilt, wenn weder Aufgabe, Projekt noch Kunde einen Stundensatz haben.",
    )

    class Rounding(models.IntegerChoices):
        EXACT = 0, "exakt (keine Rundung)"
        FIVE = 5, "jede angefangenen 5 Minuten"
        SIX = 6, "jede angefangenen 6 Minuten (Zehntelstunde)"
        TEN = 10, "jede angefangenen 10 Minuten"
        FIFTEEN = 15, "jede angefangene Viertelstunde"
        THIRTY = 30, "jede angefangene halbe Stunde"
        SIXTY = 60, "jede angefangene Stunde"

    time_rounding = models.PositiveSmallIntegerField(
        "Zeiten runden auf",
        choices=Rounding,
        default=Rounding.EXACT,
        help_text="Beim Stoppen des Timers und beim Speichern eines Eintrags wird das Ende aufgerundet. "
        "Bestehende Einträge bleiben, wie sie sind.",
    )

    login_max_attempts = models.PositiveSmallIntegerField(
        "Fehlversuche bis zur Sperre",
        default=5,
        help_text="Nach so vielen falschen Passwörtern oder Codes von einer IP-Adresse ist die Anmeldung von dort "
        "gesperrt. 0 schaltet die Sperre aus.",
    )
    login_lockout_minutes = models.PositiveSmallIntegerField(
        "Sperre in Minuten",
        default=15,
        validators=[MinValueValidator(1)],
        help_text="Zählt die Fehlversuche in diesem Zeitraum und sperrt so lange.",
    )

    login_link_enabled = models.BooleanField(
        "Anmeldung per E-Mail-Link erlauben",
        default=True,
        help_text="Bietet auf der Anmeldeseite einen Link per E-Mail statt des Passworts an. "
        "Die Zwei-Faktor-Anmeldung gilt auch dann. Nur wenn der E-Mail-Versand eingerichtet ist.",
    )

    class SyncInterval(models.IntegerChoices):
        # Minutes between two automatic runs.
        OFF = 0, "aus"
        QUARTER_HOUR = 15, "alle 15 Minuten"
        HALF_HOUR = 30, "alle 30 Minuten"
        HOUR = 60, "stündlich"
        TWO_HOURS = 120, "alle 2 Stunden"
        FOUR_HOURS = 240, "alle 4 Stunden"
        SIX_HOURS = 360, "alle 6 Stunden"
        TWELVE_HOURS = 720, "alle 12 Stunden"
        DAY = 1440, "täglich"
        WEEK = 10080, "wöchentlich"

    lexware_sync_interval = models.PositiveIntegerField(
        "Kunden importieren", choices=SyncInterval, default=SyncInterval.HOUR
    )
    lexware_sync_from = models.TimeField("ab", null=True, blank=True)
    lexware_sync_until = models.TimeField("bis", null=True, blank=True)
    invoice_sync_interval = models.PositiveIntegerField(
        "Rechnungsstatus abgleichen", choices=SyncInterval, default=SyncInterval.HOUR
    )
    invoice_sync_from = models.TimeField("ab", null=True, blank=True)
    invoice_sync_until = models.TimeField("bis", null=True, blank=True)
    # Written by the import, not on the settings page.
    lexware_synced_at = models.DateTimeField("letzter Kundenimport", null=True, blank=True, editable=False)
    lexware_sync_status = models.CharField("Ergebnis des letzten Imports", max_length=500, blank=True, editable=False)
    lexware_sync_failed = models.BooleanField("letzter Import fehlgeschlagen", default=False, editable=False)
    invoices_synced_at = models.DateTimeField("letzter Abgleich der Rechnungen", null=True, blank=True, editable=False)
    invoices_sync_status = models.CharField(
        "Ergebnis des letzten Rechnungsabgleichs", max_length=500, blank=True, editable=False
    )
    invoices_sync_failed = models.BooleanField(
        "letzter Rechnungsabgleich fehlgeschlagen", default=False, editable=False
    )

    backup_enabled = models.BooleanField("Datenbank täglich sichern", default=True)
    backup_time = models.TimeField(
        "Uhrzeit",
        default=time(3),
        help_text="Ist der Server zu der Zeit aus, holt er die Sicherung am selben Tag nach.",
    )
    backup_keep = models.PositiveSmallIntegerField(
        "Kopien aufbewahren",
        default=14,
        validators=[MinValueValidator(1)],
        help_text="Ältere Kopien werden nach jeder Sicherung gelöscht.",
    )
    # Written by the scheduler, not on the settings page.
    backup_at = models.DateTimeField("letzte Sicherung", null=True, blank=True, editable=False)
    backup_status = models.CharField("Ergebnis der letzten Sicherung", max_length=500, blank=True, editable=False)
    backup_failed = models.BooleanField("letzte Sicherung fehlgeschlagen", default=False, editable=False)

    class Weekday(models.IntegerChoices):
        MONDAY = 0, "montags"
        TUESDAY = 1, "dienstags"
        WEDNESDAY = 2, "mittwochs"
        THURSDAY = 3, "donnerstags"
        FRIDAY = 4, "freitags"
        SATURDAY = 5, "samstags"
        SUNDAY = 6, "sonntags"

    weekly_report_enabled = models.BooleanField("Wochenbericht per E-Mail", default=True)
    weekly_report_weekday = models.PositiveSmallIntegerField("Tag", choices=Weekday, default=Weekday.MONDAY)
    weekly_report_time = models.TimeField("Uhrzeit", default=time(7))
    timer_reminder_hours = models.PositiveSmallIntegerField(
        "Erinnern, wenn ein Timer länger läuft als (Stunden)",
        default=10,
        help_text="Eine E-Mail pro Timer an den, der ihn gestartet hat. 0 schaltet die Erinnerung aus.",
    )
    # Written by the scheduler, not on the settings page.
    weekly_report_at = models.DateTimeField("letzter Wochenbericht", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = "Einstellungen"

    def __str__(self) -> str:
        return "Einstellungen"

    @classmethod
    def load(cls) -> AppSettings:
        return cls.objects.get_or_create(pk=1)[0]

    @classmethod
    async def aload(cls) -> AppSettings:
        return (await cls.objects.aget_or_create(pk=1))[0]
