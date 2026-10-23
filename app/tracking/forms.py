from datetime import datetime

from django import forms
from django.db.models import F, Max, Q, QuerySet
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe

from core.forms import StyledFormMixin
from projects.models import Project, Task
from tracking.models import TimeEntry
from tracking.services import round_to_step, rounded_times


def task_choices(user, include_pk: int | None = None):
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
        is_pk = str(value or "").isdigit()
        task = Task.objects.select_related("project__customer").filter(pk=value).first() if is_pk else None
        context["widget"]["task"] = task
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


def open_tasks(user, include_pk: int | None = None):
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


class StepDateTimeWidget(forms.MultiWidget):
    """A date field next to the time of day: a list of times in rounding steps, or a free time field without rounding.

    A datetime-local field only steps its arrows, the browser's picker still offers every minute.
    """

    def __init__(self, step: int = 0, attrs=None):
        self.step = step
        self.step_choices = [(f"{m // 60:02}:{m % 60:02}",) * 2 for m in range(0, 24 * 60, step)] if step else []
        if step:
            time_widget = forms.Select(attrs={"aria-label": "Uhrzeit"}, choices=self.step_choices)
        else:
            time_widget = forms.TimeInput(attrs={"type": "time", "aria-label": "Uhrzeit"}, format="%H:%M")
        date_widget = forms.DateInput(attrs={"type": "date", "aria-label": "Datum"}, format="%Y-%m-%d")
        super().__init__([date_widget, time_widget], attrs)

    def decompress(self, value):
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return [None, None]
        if not value:
            return [None, None]
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return [value.date(), value.strftime("%H:%M")]

    def get_context(self, name, value, attrs):
        if self.step:
            clock = (value if isinstance(value, list) else self.decompress(value))[1]
            choices = self.step_choices
            # An old entry may sit between two steps; keep its time instead of jumping to midnight.
            if clock and (clock, clock) not in choices:
                choices = sorted([*choices, (clock, clock)])
            self.widgets[1].choices = choices
        return super().get_context(name, value, attrs)

    def render(self, name, value, attrs=None, renderer=None):
        return mark_safe(f'<span class="grid grid-cols-2 gap-2">{super().render(name, value, attrs, renderer)}</span>')

    def value_from_datadict(self, data, files, name):
        if name in data:  # a single combined value, as the tests and older forms send it
            return data[name]
        day, clock = super().value_from_datadict(data, files, name)
        return f"{day}T{clock}" if day and clock else None

    def value_omitted_from_data(self, data, files, name):
        return name not in data and super().value_omitted_from_data(data, files, name)


class TimeEntryForm(StyledFormMixin, forms.ModelForm):
    task = TaskChoiceField(label="Aufgabe", queryset=Task.objects.none(), widget=TaskSearchInput)

    class Meta:
        model = TimeEntry
        fields = ["task", "started_at", "ended_at", "description", "is_billable"]
        widgets = {
            "started_at": StepDateTimeWidget(),
            "ended_at": StepDateTimeWidget(),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, user, rounding: int = 0, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the entry's current task selectable even if it is done or no longer unlocked by now.
        include = self.instance.task_id if self.instance.pk else None
        self.fields["task"].queryset = task_choices(user, include_pk=include)
        self.fields["ended_at"].required = True
        self.rounding = rounding
        for name in ("started_at", "ended_at"):
            # Only times on a step can be picked, and the shown times already sit on one.
            self.fields[name].widget = StepDateTimeWidget(step=rounding, attrs={"class": "input"})
            if rounding and self.initial.get(name):
                self.initial[name] = round_to_step(self.initial[name], rounding)

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("started_at"), cleaned.get("ended_at")
        if start and end and end <= start:
            self.add_error("ended_at", "Das Ende muss nach dem Beginn liegen.")
        elif start and end:
            cleaned["started_at"], cleaned["ended_at"] = rounded_times(start, end, self.rounding)
        return cleaned
