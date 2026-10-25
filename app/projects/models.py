from decimal import Decimal

from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class Project(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", _("geplant")
        ACTIVE = "active", _("aktiv")
        PAUSED = "paused", _("pausiert")
        DONE = "done", _("abgeschlossen")

    customer = models.ForeignKey(
        "customers.Customer", verbose_name=_("Kunde"), on_delete=models.PROTECT, related_name="projects"
    )
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Beschreibung"), blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status, default=Status.ACTIVE)
    hourly_rate = models.DecimalField(
        _("Stundensatz (netto)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer lassen, um den Stundensatz des Kunden zu verwenden."),
    )
    budget_hours = models.DecimalField(_("Budget (Stunden)"), max_digits=8, decimal_places=2, null=True, blank=True)
    start_date = models.DateField(_("Start"), null=True, blank=True)
    end_date = models.DateField(_("Ende"), null=True, blank=True)

    class Meta:
        verbose_name = _("Projekt")
        verbose_name_plural = _("Projekte")
        ordering = ["customer__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "name"], name="unique_project_name_per_customer"),
        ]

    def __str__(self) -> str:
        return self.name


class Task(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", _("offen")
        IN_PROGRESS = "in_progress", _("in Arbeit")
        DONE = "done", _("erledigt")

    project = models.ForeignKey(Project, verbose_name=_("Projekt"), on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField(_("Name"), max_length=255)
    description = models.TextField(_("Beschreibung"), blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=Status, default=Status.OPEN)
    is_billable = models.BooleanField(_("abrechenbar"), default=True)
    hourly_rate = models.DecimalField(
        _("Stundensatz (netto)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer lassen, um den Stundensatz des Projekts zu verwenden."),
    )
    estimated_hours = models.DecimalField(
        _("Schätzung (Stunden)"), max_digits=8, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = _("Aufgabe")
        verbose_name_plural = _("Aufgaben")
        ordering = ["project", "name"]

    def __str__(self) -> str:
        return self.name

    @property
    def effective_hourly_rate(self) -> Decimal | None:
        """Rate of the task, falling back to the project and then the customer.

        Needs ``project__customer`` loaded (``select_related``) when used in async code.
        """
        for rate in (self.hourly_rate, self.project.hourly_rate, self.project.customer.default_hourly_rate):
            if rate is not None:
                return rate
        return None


class TaskTemplate(TimeStampedModel):
    """A task that recurs across projects. Adding it to a project copies its values into a new task."""

    name = models.CharField(_("Name"), max_length=255, unique=True)
    description = models.TextField(_("Beschreibung"), blank=True)
    is_billable = models.BooleanField(_("abrechenbar"), default=True)
    hourly_rate = models.DecimalField(
        _("Stundensatz (netto)"),
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("Leer lassen, damit die Aufgabe den Stundensatz des Projekts verwendet."),
    )
    estimated_hours = models.DecimalField(
        _("Schätzung (Stunden)"), max_digits=8, decimal_places=2, null=True, blank=True
    )

    COPIED_FIELDS = ("name", "description", "is_billable", "hourly_rate", "estimated_hours")

    class Meta:
        verbose_name = _("Aufgabenvorlage")
        verbose_name_plural = _("Aufgabenvorlagen")
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def to_task(self, project: Project) -> Task:
        """An unsaved task in ``project`` with this template's values."""
        return Task(project=project, **{field: getattr(self, field) for field in self.COPIED_FIELDS})

    @classmethod
    def from_task(cls, task: Task) -> TaskTemplate:
        """An unsaved template with the values of ``task``."""
        return cls(**{field: getattr(task, field) for field in cls.COPIED_FIELDS})
