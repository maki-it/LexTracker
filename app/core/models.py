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
    lexware_sync_interval = models.PositiveIntegerField(
        "Automatischer Kundenimport alle (Minuten)",
        default=60,
        help_text="0 schaltet den automatischen Import ab.",
    )
    # Written by the import, not on the settings page.
    lexware_synced_at = models.DateTimeField("letzter Kundenimport", null=True, blank=True, editable=False)
    lexware_sync_status = models.CharField("Ergebnis des letzten Imports", max_length=500, blank=True, editable=False)
    lexware_sync_failed = models.BooleanField("letzter Import fehlgeschlagen", default=False, editable=False)

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
