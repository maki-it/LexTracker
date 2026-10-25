from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class TimeEntry(TimeStampedModel):
    """A block of worked time. An entry without ``ended_at`` is a running timer."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name=_("Benutzer"), on_delete=models.PROTECT, related_name="time_entries"
    )
    task = models.ForeignKey(
        "projects.Task", verbose_name=_("Aufgabe"), on_delete=models.PROTECT, related_name="time_entries"
    )
    started_at = models.DateTimeField(_("Beginn"), default=timezone.now)
    ended_at = models.DateTimeField(_("Ende"), null=True, blank=True)
    description = models.TextField(_("Beschreibung"), blank=True)
    is_billable = models.BooleanField(_("abrechenbar"), default=True)
    # Set once the entry has been billed. Billed entries are not billed again.
    invoice = models.ForeignKey(
        "billing.Invoice",
        verbose_name=_("Rechnung"),
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="time_entries",
    )

    class Meta:
        verbose_name = _("Zeiteintrag")
        verbose_name_plural = _("Zeiteinträge")
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["user", "-started_at"]),
            models.Index(fields=["task", "started_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True) | models.Q(ended_at__gt=models.F("started_at")),
                name="time_entry_ends_after_start",
            ),
            models.UniqueConstraint(
                fields=["user"], condition=models.Q(ended_at__isnull=True), name="one_running_timer_per_user"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.task_id} – {self.started_at:%d.%m.%Y %H:%M}"

    @property
    def is_running(self) -> bool:
        return self.ended_at is None

    @property
    def duration(self) -> timedelta:
        return (self.ended_at or timezone.now()) - self.started_at
