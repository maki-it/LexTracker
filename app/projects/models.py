from decimal import Decimal

from django.db import models

from core.models import TimeStampedModel


class Project(TimeStampedModel):
    class Status(models.TextChoices):
        PLANNED = "planned", "geplant"
        ACTIVE = "active", "aktiv"
        PAUSED = "paused", "pausiert"
        DONE = "done", "abgeschlossen"

    customer = models.ForeignKey(
        "customers.Customer", verbose_name="Kunde", on_delete=models.PROTECT, related_name="projects"
    )
    name = models.CharField("Name", max_length=255)
    description = models.TextField("Beschreibung", blank=True)
    status = models.CharField("Status", max_length=20, choices=Status, default=Status.ACTIVE)
    hourly_rate = models.DecimalField(
        "Stundensatz (netto)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leer lassen, um den Stundensatz des Kunden zu verwenden.",
    )
    budget_hours = models.DecimalField("Budget (Stunden)", max_digits=8, decimal_places=2, null=True, blank=True)
    start_date = models.DateField("Start", null=True, blank=True)
    end_date = models.DateField("Ende", null=True, blank=True)

    class Meta:
        verbose_name = "Projekt"
        verbose_name_plural = "Projekte"
        ordering = ["customer__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["customer", "name"], name="unique_project_name_per_customer"),
        ]

    def __str__(self) -> str:
        return self.name


class Task(TimeStampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "offen"
        IN_PROGRESS = "in_progress", "in Arbeit"
        DONE = "done", "erledigt"

    project = models.ForeignKey(Project, verbose_name="Projekt", on_delete=models.CASCADE, related_name="tasks")
    name = models.CharField("Name", max_length=255)
    description = models.TextField("Beschreibung", blank=True)
    status = models.CharField("Status", max_length=20, choices=Status, default=Status.OPEN)
    is_billable = models.BooleanField("abrechenbar", default=True)
    hourly_rate = models.DecimalField(
        "Stundensatz (netto)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leer lassen, um den Stundensatz des Projekts zu verwenden.",
    )
    estimated_hours = models.DecimalField("Schätzung (Stunden)", max_digits=8, decimal_places=2, null=True, blank=True)

    class Meta:
        verbose_name = "Aufgabe"
        verbose_name_plural = "Aufgaben"
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

    name = models.CharField("Name", max_length=255, unique=True)
    description = models.TextField("Beschreibung", blank=True)
    is_billable = models.BooleanField("abrechenbar", default=True)
    hourly_rate = models.DecimalField(
        "Stundensatz (netto)",
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Leer lassen, damit die Aufgabe den Stundensatz des Projekts verwendet.",
    )
    estimated_hours = models.DecimalField("Schätzung (Stunden)", max_digits=8, decimal_places=2, null=True, blank=True)

    COPIED_FIELDS = ("name", "description", "is_billable", "hourly_rate", "estimated_hours")

    class Meta:
        verbose_name = "Aufgabenvorlage"
        verbose_name_plural = "Aufgabenvorlagen"
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
