from uuid import UUID

from django import forms
from django.db.models import F, Max, Q, QuerySet
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin
from core.ids import parse_uuid
from projects.models import Project, Task
from tracking.models import TimeEntry
from tracking.services import round_to_step, rounded_times


def task_choices(user, include_pk: UUID | None = None):
    """The tasks offered when booking time: open tasks of active projects, the ones the user booked last first."""
    tasks = open_tasks(user, include_pk=include_pk).filter(Q(project__status=Project.Status.ACTIVE) | Q(pk=include_pk))
    last_used = Max("time_entries__started_at", filter=Q(time_entries__user=user))
    return tasks.annotate(last_used=last_used).order_by(
        F("last_used").desc(nulls_last=True), "project__customer__name", "project__name", "name"
    )


# Suggestions shown at once in the task search; enough to find a task without a long list.
SEARCH_LIMIT = 8


def search_tasks(user, query: str):
    """Tasks for the task search: every word of ``query`` in the task, project or customer name.

    Without a query these are the recently used tasks.
    """
    tasks = task_choices(user)
    for word in query.split():
        tasks = tasks.filter(
            Q(name__icontains=word) | Q(project__name__icontains=word) | Q(project__customer__name__icontains=word)
        )
    return tasks[:SEARCH_LIMIT]


class TaskSearchInput(forms.Widget):
    """The task as a search field with suggestions from the server instead of a long list."""

    template_name = "tracking/_task_search_widget.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        task_id = parse_uuid(value)
        task = Task.objects.select_related("project__customer").filter(pk=task_id).first() if task_id else None
        context["widget"]["task"] = task
        return context

    def _render(self, template_name, context, renderer=None):
        # The template lives in templates/, which Django's default form renderer does not search.
        return mark_safe(render_to_string(template_name, context))


class NowDateTimeInput(forms.DateTimeInput):
    """A date-time field with a "Jetzt" button next to it that app.js wires up (data-now-for)."""

    template_name = "tracking/_datetime_now_widget.html"
    with_now_button = True

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["now_label"] = getattr(self, "now_label", "")
        return context

    def _render(self, template_name, context, renderer=None):
        # The template lives in templates/, which Django's default form renderer does not search.
        return mark_safe(render_to_string(template_name, context))


class TaskChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, task: Task) -> str:
        return f"{task.project.customer.name} · {task.project.name} · {task.name}"


def bookable_projects(user) -> QuerySet[Project]:
    """The projects the user may book time on: all for administrators, the unlocked ones for employees."""
    if user.is_admin:
        return Project.objects.all()
    if not user.is_employee:
        return Project.objects.none()
    return Project.objects.filter(Q(bookable_by=user) | Q(customer__bookable_by=user)).distinct()


def open_tasks(user, include_pk: UUID | None = None):
    """Tasks the user can book time on: not done, in a project that is not done and is unlocked for them."""
    is_open = ~Q(status=Task.Status.DONE) & ~Q(project__status=Project.Status.DONE)
    is_open &= Q(project__in=bookable_projects(user).values("pk"))
    if include_pk:
        is_open |= Q(pk=include_pk)
    return (
        Task.objects.filter(is_open)
        .select_related("project", "project__customer")
        .order_by("project__customer__name", "project__name", "name")
    )


class TimeEntryForm(StyledFormMixin, forms.ModelForm):
    task = TaskChoiceField(label=_("Aufgabe"), queryset=Task.objects.none(), widget=TaskSearchInput)

    class Meta:
        model = TimeEntry
        fields = ["task", "started_at", "ended_at", "description", "is_billable"]
        widgets = {
            "started_at": NowDateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ended_at": NowDateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user, rounding: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the entry's current task selectable even if it is done or no longer unlocked by now.
        include = None if self.instance._state.adding else self.instance.task_id
        self.fields["task"].queryset = task_choices(user, include_pk=include)
        self.fields["ended_at"].required = True
        self.rounding = rounding
        for name in ("started_at", "ended_at"):
            self.fields[name].widget.now_label = _("%(field)s auf jetzt setzen") % {"field": self.fields[name].label}
        if rounding:
            # The arrows move in rounding steps, app.js snaps a picked time to a step, and the shown times sit on one.
            for name in ("started_at", "ended_at"):
                self.fields[name].widget.attrs.update({"step": rounding * 60, "data-snap-minutes": rounding})
                if self.initial.get(name):
                    self.initial[name] = round_to_step(self.initial[name], rounding)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("started_at"), cleaned.get("ended_at")
        if start and end and end <= start:
            self.add_error("ended_at", _("Das Ende muss nach dem Beginn liegen."))
        elif start and end:
            cleaned["started_at"], cleaned["ended_at"] = rounded_times(start, end, self.rounding)
        return cleaned
