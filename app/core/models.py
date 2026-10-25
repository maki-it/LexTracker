import uuid
from datetime import time

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class UUIDModel(models.Model):
    """A model identified by a UUID instead of a counter.

    Version 7 puts the creation time first, so new rows land at the end of the primary key index like
    counters do. That keeps SQLite's B-tree compact, which random UUIDs (version 4) would not.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid7, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(UUIDModel):
    created_at = models.DateTimeField(_("erstellt"), auto_now_add=True)
    updated_at = models.DateTimeField(_("geändert"), auto_now=True)

    class Meta:
        abstract = True


class AppSettings(models.Model):
    """Settings for the whole app, edited on the settings page. There is only one row."""

    default_hourly_rate = models.DecimalField(
        _("Standard-Stundensatz (netto)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Gilt, wenn weder Aufgabe, Projekt noch Kunde einen Stundensatz haben."),
    )

    class Rounding(models.IntegerChoices):
        EXACT = 0, _("exakt (keine Rundung)")
        FIVE = 5, _("5 Minuten")
        SIX = 6, _("6 Minuten (Zehntelstunde)")
        TEN = 10, _("10 Minuten")
        FIFTEEN = 15, _("Viertelstunde")
        THIRTY = 30, _("halbe Stunde")
        SIXTY = 60, _("volle Stunde")

    time_rounding = models.PositiveSmallIntegerField(
        _("Zeiten runden auf"),
        choices=Rounding,
        default=Rounding.EXACT,
        help_text=_(
            "Beim Stoppen des Timers und beim Speichern eines Eintrags werden Beginn und Ende auf den "
            "nächsten Schritt gerundet (z. B. 9:07 auf 9:00, 9:08 auf 9:15). Ein Eintrag dauert mindestens einen "
            "Schritt. Bestehende Einträge bleiben, wie sie sind."
        ),
    )

    class InvoiceDetail(models.TextChoices):
        SUMMARY = "summary", _("Projekt und Zeitraum")
        ENTRIES = "entries", _("zusätzlich die Tätigkeiten mit Datum und Dauer")

    invoice_detail = models.CharField(
        _("Detailtiefe der Rechnungspositionen"),
        max_length=10,
        choices=InvoiceDetail,
        default=InvoiceDetail.SUMMARY,
        help_text=_(
            "Jede Position heißt wie die Aufgabe. Die Beschreibung darunter nennt das Projekt und den Zeitraum. "
            "Mit den Tätigkeiten steht auch jeder Zeiteintrag mit seiner Beschreibung auf der Rechnung, "
            "und der Kunde sieht sie."
        ),
    )

    login_max_attempts = models.PositiveSmallIntegerField(
        _("Fehlversuche bis zur Sperre"),
        default=5,
        help_text=_(
            "Nach so vielen falschen Passwörtern oder Codes von einer IP-Adresse ist die Anmeldung von dort "
            "gesperrt. 0 schaltet die Sperre aus."
        ),
    )
    login_lockout_minutes = models.PositiveSmallIntegerField(
        _("Sperre in Minuten"),
        default=15,
        validators=[MinValueValidator(1)],
        help_text=_("Zählt die Fehlversuche in diesem Zeitraum und sperrt so lange."),
    )

    login_link_enabled = models.BooleanField(
        _("Anmeldung per E-Mail-Link erlauben"),
        default=True,
        help_text=_(
            "Bietet auf der Anmeldeseite einen Link per E-Mail statt des Passworts an. "
            "Die Zwei-Faktor-Anmeldung gilt auch dann. Nur wenn der E-Mail-Versand eingerichtet ist."
        ),
    )

    class SyncInterval(models.IntegerChoices):
        # Minutes between two automatic runs.
        OFF = 0, _("aus")
        QUARTER_HOUR = 15, _("alle 15 Minuten")
        HALF_HOUR = 30, _("alle 30 Minuten")
        HOUR = 60, _("stündlich")
        TWO_HOURS = 120, _("alle 2 Stunden")
        FOUR_HOURS = 240, _("alle 4 Stunden")
        SIX_HOURS = 360, _("alle 6 Stunden")
        TWELVE_HOURS = 720, _("alle 12 Stunden")
        DAY = 1440, _("täglich")
        WEEK = 10080, _("wöchentlich")

    lexware_sync_interval = models.PositiveIntegerField(
        _("Kunden importieren"), choices=SyncInterval, default=SyncInterval.HOUR
    )
    lexware_sync_from = models.TimeField(_("ab"), null=True, blank=True)
    lexware_sync_until = models.TimeField(_("bis"), null=True, blank=True)
    invoice_sync_interval = models.PositiveIntegerField(
        _("Rechnungsstatus abgleichen"), choices=SyncInterval, default=SyncInterval.HOUR
    )
    invoice_sync_from = models.TimeField(_("ab"), null=True, blank=True)
    invoice_sync_until = models.TimeField(_("bis"), null=True, blank=True)
    # Written by the import, not on the settings page.
    lexware_synced_at = models.DateTimeField(_("letzter Kundenimport"), null=True, blank=True, editable=False)
    lexware_sync_status = models.CharField(
        _("Ergebnis des letzten Imports"), max_length=500, blank=True, editable=False
    )
    lexware_sync_failed = models.BooleanField(_("letzter Import fehlgeschlagen"), default=False, editable=False)
    invoices_synced_at = models.DateTimeField(
        _("letzter Abgleich der Rechnungen"), null=True, blank=True, editable=False
    )
    invoices_sync_status = models.CharField(
        _("Ergebnis des letzten Rechnungsabgleichs"), max_length=500, blank=True, editable=False
    )
    invoices_sync_failed = models.BooleanField(
        _("letzter Rechnungsabgleich fehlgeschlagen"), default=False, editable=False
    )

    backup_enabled = models.BooleanField(_("Datenbank täglich sichern"), default=True)
    backup_time = models.TimeField(
        _("Uhrzeit"),
        default=time(3),
        help_text=_("Ist der Server zu der Zeit aus, holt er die Sicherung am selben Tag nach."),
    )
    backup_keep = models.PositiveSmallIntegerField(
        _("Kopien aufbewahren"),
        default=14,
        validators=[MinValueValidator(1)],
        help_text=_("Ältere Kopien werden nach jeder Sicherung gelöscht."),
    )
    # Written by the scheduler, not on the settings page.
    backup_at = models.DateTimeField(_("letzte Sicherung"), null=True, blank=True, editable=False)
    backup_status = models.CharField(_("Ergebnis der letzten Sicherung"), max_length=500, blank=True, editable=False)
    backup_failed = models.BooleanField(_("letzte Sicherung fehlgeschlagen"), default=False, editable=False)

    class Weekday(models.IntegerChoices):
        MONDAY = 0, _("montags")
        TUESDAY = 1, _("dienstags")
        WEDNESDAY = 2, _("mittwochs")
        THURSDAY = 3, _("donnerstags")
        FRIDAY = 4, _("freitags")
        SATURDAY = 5, _("samstags")
        SUNDAY = 6, _("sonntags")

    weekly_report_enabled = models.BooleanField(_("Wochenbericht per E-Mail"), default=True)
    weekly_report_weekday = models.PositiveSmallIntegerField(_("Tag"), choices=Weekday, default=Weekday.MONDAY)
    weekly_report_time = models.TimeField(_("Uhrzeit"), default=time(7))
    timer_reminder_hours = models.PositiveSmallIntegerField(
        _("Erinnern, wenn ein Timer länger läuft als (Stunden)"),
        default=10,
        help_text=_("Eine E-Mail pro Timer an den, der ihn gestartet hat. 0 schaltet die Erinnerung aus."),
    )

    class OverdueNotice(models.TextChoices):
        OFF = "off", _("aus")
        ADMINS = "admins", _("an Administratoren")
        CUSTOMER = "customer", _("an den Kunden und an Administratoren")

    overdue_notice = models.CharField(
        _("Hinweis bei überfälligen Rechnungen"),
        max_length=10,
        choices=OverdueNotice,
        default=OverdueNotice.ADMINS,
        help_text=_(
            "Eine E-Mail pro Rechnung, sobald sie überfällig ist. Der Kunde bekommt eine freundliche "
            "Zahlungserinnerung an die E-Mail-Adresse aus Lexware."
        ),
    )
    overdue_notice_days = models.PositiveSmallIntegerField(
        _("Tage nach Fälligkeit"),
        default=3,
        help_text=_("So lange wartet der Hinweis, damit eine gerade eingegangene Zahlung nicht übersehen wird."),
    )
    invite_by_mail = models.BooleanField(
        _("Einladung per E-Mail schicken"),
        default=True,
        help_text=_("Neue Benutzer mit E-Mail-Adresse bekommen ihren Einladungslink direkt per E-Mail."),
    )
    # Written by the scheduler, not on the settings page.
    weekly_report_at = models.DateTimeField(_("letzter Wochenbericht"), null=True, blank=True, editable=False)

    # Written by the scheduler every check, so the web app can tell whether it is still alive.
    scheduler_started_at = models.DateTimeField(_("Scheduler gestartet"), null=True, blank=True, editable=False)
    scheduler_seen_at = models.DateTimeField(_("Scheduler zuletzt gemeldet"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = _("Einstellungen")

    def __str__(self) -> str:
        return "Einstellungen"

    @classmethod
    def load(cls) -> AppSettings:
        return cls.objects.get_or_create(pk=1)[0]

    @classmethod
    async def aload(cls) -> AppSettings:
        return (await cls.objects.aget_or_create(pk=1))[0]


class JobStatus(UUIDModel):
    """How the scheduler's last run of one job went, shown on the jobs page. One row per job."""

    key = models.SlugField(_("Aufgabe"), unique=True)
    last_run_at = models.DateTimeField(_("letzter Lauf"), null=True, blank=True)
    last_success_at = models.DateTimeField(_("letzter erfolgreicher Lauf"), null=True, blank=True)
    duration_ms = models.PositiveIntegerField(_("Dauer in Millisekunden"), default=0)
    last_ok = models.BooleanField(_("letzter Lauf erfolgreich"), default=True)
    last_result = models.CharField(_("Ergebnis des letzten Laufs"), max_length=500, blank=True)
    failures = models.PositiveIntegerField(_("Fehlschläge in Folge"), default=0)
    last_error = models.CharField(_("letzte Fehlermeldung"), max_length=500, blank=True)
    last_error_at = models.DateTimeField(_("letzter Fehlschlag"), null=True, blank=True)

    class Meta:
        verbose_name = _("Aufgabenstatus")
        verbose_name_plural = _("Aufgabenstatus")

    def __str__(self) -> str:
        return self.key

    @property
    def duration_seconds(self) -> float:
        return self.duration_ms / 1000
