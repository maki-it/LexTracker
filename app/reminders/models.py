from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel


class Reminder(TimeStampedModel):
    """Something to remember about a customer or a project, optionally at a date and time.

    When it is due, the scheduler tells its user in the bell and by e-mail, as set on the reminder
    (see ``reminders.jobs``). A reminder without a date is a plain note to self that never notifies.
    """

    title = models.CharField(_("Titel"), max_length=255)
    notes = models.TextField(_("Notizen"), blank=True)
    due_at = models.DateTimeField(_("Fällig am"), null=True, blank=True)
    # A reminder belongs to a customer or to one of its projects. Project reminders also name the customer,
    # so the customer's page lists them too.
    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name=_("Kunde"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
    )
    project = models.ForeignKey(
        "projects.Project",
        verbose_name=_("Projekt"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="reminders",
    )
    # Who is reminded.
    user = models.ForeignKey("accounts.User", verbose_name=_("Benutzer"), on_delete=models.CASCADE, related_name="+")
    notify_bell = models.BooleanField(_("Per Glocke erinnern"), default=True)
    notify_email = models.BooleanField(_("Per E-Mail erinnern"), default=True)
    # When the user was told. Set once, so a reminder is not announced again and again.
    notified_at = models.DateTimeField(_("benachrichtigt"), null=True, blank=True, editable=False)
    done_at = models.DateTimeField(_("erledigt"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("Erinnerung")
        verbose_name_plural = _("Erinnerungen")
        ordering = [models.F("due_at").asc(nulls_last=True), "created_at"]
        indexes = [
            # What the scheduler looks for every minute, and the count in the sidebar.
            models.Index(
                fields=["due_at"],
                condition=Q(done_at__isnull=True, due_at__isnull=False),
                name="reminder_open_due",
            ),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(customer__isnull=False) | Q(project__isnull=False), name="reminder_has_customer_or_project"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def is_done(self) -> bool:
        return self.done_at is not None

    @property
    def is_overdue(self) -> bool:
        return self.due_at is not None and self.done_at is None and self.due_at <= timezone.now()

    @property
    def subject(self) -> str:
        """What it is about: the project with its customer, or the customer."""
        if self.project_id:
            return f"{self.project.customer.name} · {self.project.name}"
        return self.customer.name if self.customer_id else ""
