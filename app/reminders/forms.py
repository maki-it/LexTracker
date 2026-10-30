from django import forms
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.forms import MARKDOWN_HELP, MarkdownTextarea, StyledFormMixin
from customers.models import Customer
from projects.models import Project
from reminders.models import Reminder


class ReminderForm(StyledFormMixin, forms.ModelForm):
    """A reminder for the customer or project it is opened from.

    Without one (on the page with all reminders), ``customers`` and ``projects`` are offered in a field.
    """

    target = forms.ChoiceField(label=_("Bezug"), required=False)

    class Meta:
        model = Reminder
        fields = [
            "target",
            "title",
            "due_at",
            "repeat",
            "repeat_every",
            "repeat_until",
            "notes",
            "notify_bell",
            "notify_email",
        ]
        widgets = {
            "due_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "repeat_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notes": MarkdownTextarea(attrs={"rows": 3}),
        }
        help_texts = {
            "due_at": _("Ohne Datum gibt es keine Benachrichtigung."),
            "notes": MARKDOWN_HELP,
        }

    def __init__(
        self,
        *args,
        user,
        customer: Customer | None = None,
        project: Project | None = None,
        customers: list[Customer] | None = None,
        projects: list[Project] | None = None,
        mail_configured: bool = True,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.user = user
        # Only counts with a repetition; without one it is left empty.
        self.fields["repeat_every"].required = False
        # Hidden while it never repeats (data-shown-for in app.js).
        self.fields["repeat_every"].shown_for = self.fields["repeat_until"].shown_for = "repeat!="
        self.customer = customer
        self.project = project
        if not mail_configured:
            self.fields["notify_email"].help_text = _(
                "Der E-Mail-Versand ist noch nicht eingerichtet. Das geht in den Einstellungen."
            )
        self._targets: dict[str, Customer | Project] = {}
        if customer or project or not self.instance._state.adding:
            del self.fields["target"]
            return
        self._targets = {f"customer:{c.pk}": c for c in customers or []} | {
            f"project:{p.pk}": p for p in projects or []
        }
        customer_choices = [(f"customer:{c.pk}", c.name) for c in customers or []]
        project_choices = [(f"project:{p.pk}", f"{p.customer.name} · {p.name}") for p in projects or []]
        self.fields["target"].required = True
        self.fields["target"].choices = [
            ("", "–"),
            (_("Kunden"), customer_choices),
            (_("Projekte"), project_choices),
        ]

    def clean_due_at(self):
        # The field shows minutes, so seconds would make an untouched date look changed.
        due_at = self.cleaned_data["due_at"]
        return due_at.replace(second=0, microsecond=0) if due_at else due_at

    def clean(self):
        cleaned = super().clean()
        due_at, repeat, until = cleaned.get("due_at"), cleaned.get("repeat"), cleaned.get("repeat_until")
        if repeat and not due_at:
            self.add_error("repeat", _("Eine Wiederholung braucht ein Datum."))
        elif repeat and until and until < timezone.localtime(due_at).date():
            self.add_error("repeat_until", _("Das Ende liegt vor dem ersten Datum."))
        if not cleaned.get("repeat_every"):
            cleaned["repeat_every"] = 1
        if not repeat:
            # What is left of an earlier repetition must not come back when it is switched on again.
            cleaned["repeat_every"], cleaned["repeat_until"] = 1, None
        return cleaned

    def clean_target(self) -> str:
        value = self.cleaned_data["target"]
        target = self._targets.get(value)
        if isinstance(target, Project):
            self.project = target
        elif target is not None:
            self.customer = target
        return value

    def save(self, commit: bool = True) -> Reminder:
        reminder = super().save(commit=False)
        if reminder._state.adding:
            reminder.user = self.user
            reminder.project = self.project
            reminder.customer = self.project.customer if self.project else self.customer
        if "due_at" in self.changed_data:
            # A new date is a new reminder: announce it again, and it is open again.
            reminder.notified_at = None
            reminder.done_at = None
        repeat_changed = bool({"repeat", "repeat_every"} & set(self.changed_data))
        if not reminder.repeat:
            reminder.repeat_from = None
        elif reminder.repeat_from is None or repeat_changed or "due_at" in self.changed_data:
            # The series is counted from this date.
            reminder.repeat_from = reminder.due_at
        if commit:
            reminder.save()
        return reminder
