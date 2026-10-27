import calendar
from datetime import date, datetime, timedelta

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from core.models import TimeStampedModel

# Far more than anybody needs; keeps the search for the next date short.
MAX_REPEAT_EVERY = 99


def _add_months(day: date, months: int) -> date:
    """The same day of the month ``months`` later; a 31st becomes the last day of a shorter month."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    return day.replace(year=year, month=month + 1, day=min(day.day, calendar.monthrange(year, month + 1)[1]))


class Reminder(TimeStampedModel):
    """Something to remember about a customer or a project, optionally at a date and time.

    When it is due, the scheduler tells its user in the bell and by e-mail, as set on the reminder
    (see ``reminders.jobs``). A reminder without a date is a plain note to self that never notifies.
    """

    class Repeat(models.TextChoices):
        NONE = "", _("nie")
        DAILY = "daily", _("täglich")
        WEEKLY = "weekly", _("wöchentlich")
        MONTHLY = "monthly", _("monatlich")
        YEARLY = "yearly", _("jährlich")

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
    repeat = models.CharField(_("Wiederholung"), max_length=10, choices=Repeat, blank=True, default=Repeat.NONE)
    repeat_every = models.PositiveSmallIntegerField(
        _("Abstand"),
        default=1,
        validators=[MinValueValidator(1), MaxValueValidator(MAX_REPEAT_EVERY)],
        help_text=_("Zum Beispiel 2 bei „wöchentlich“ für alle zwei Wochen."),
    )
    repeat_until = models.DateField(
        _("Wiederholen bis"), null=True, blank=True, help_text=_("Leer lassen für ohne Ende.")
    )
    # The first date of the series. The next ones are counted from it, so a reminder on the 31st returns to the 31st
    # after a shorter month instead of staying on the 28th. Set when the date or the repetition is changed.
    repeat_from = models.DateTimeField(null=True, blank=True, editable=False)
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
    def repeat_text(self) -> str:
        """How often it comes back, e.g. "wöchentlich" or "alle 2 Wochen"; empty if it does not."""
        if not self.repeat:
            return ""
        once, many = {
            self.Repeat.DAILY: (gettext("täglich"), gettext("alle %(count)d Tage")),
            self.Repeat.WEEKLY: (gettext("wöchentlich"), gettext("alle %(count)d Wochen")),
            self.Repeat.MONTHLY: (gettext("monatlich"), gettext("alle %(count)d Monate")),
            self.Repeat.YEARLY: (gettext("jährlich"), gettext("alle %(count)d Jahre")),
        }[self.repeat]
        return once if self.repeat_every == 1 else many % {"count": self.repeat_every}

    def next_due(self, after: datetime) -> datetime | None:
        """The first date of the series that lies after both ``after`` and the current one, or None if it ends.

        Counted from the first date of the series, at the same local time of day. Dates that were missed (the
        scheduler was not running) are skipped: a reminder is announced once, not once per missed date.
        """
        if not (self.repeat and self.due_at):
            return None
        anchor = timezone.localtime(self.repeat_from or self.due_at)
        start = anchor.date()
        later = max(after, self.due_at)
        step = self.repeat_every
        for count in range(1, 10_000):
            match self.repeat:
                case self.Repeat.DAILY:
                    day = start + timedelta(days=count * step)
                case self.Repeat.WEEKLY:
                    day = start + timedelta(weeks=count * step)
                case self.Repeat.MONTHLY:
                    day = _add_months(start, count * step)
                case _:
                    day = _add_months(start, 12 * count * step)
            if self.repeat_until and day > self.repeat_until:
                return None
            occurrence = timezone.make_aware(datetime.combine(day, anchor.time()))
            if occurrence > later:
                return occurrence
        return None

    @property
    def subject(self) -> str:
        """What it is about: the project with its customer, or the customer."""
        if self.project_id:
            return f"{self.project.customer.name} · {self.project.name}"
        return self.customer.name if self.customer_id else ""
