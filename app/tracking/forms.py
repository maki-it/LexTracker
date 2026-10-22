from django import forms
from django.db.models import Q

from core.forms import StyledFormMixin
from projects.models import Project, Task
from tracking.models import TimeEntry


class TaskChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, task: Task) -> str:
        return f"{task.project.customer.name} · {task.project.name} · {task.name}"


def open_tasks(include_pk: int | None = None):
    """Tasks time can be booked on: not done, in a project that is not done."""
    is_open = ~Q(status=Task.Status.DONE) & ~Q(project__status=Project.Status.DONE)
    if include_pk:
        is_open |= Q(pk=include_pk)
    return (
        Task.objects.filter(is_open)
        .select_related("project", "project__customer")
        .order_by("project__customer__name", "project__name", "name")
    )


class TimeEntryForm(StyledFormMixin, forms.ModelForm):
    task = TaskChoiceField(label="Aufgabe", queryset=Task.objects.none())

    class Meta:
        model = TimeEntry
        fields = ["task", "started_at", "ended_at", "description", "is_billable"]
        widgets = {
            "started_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "ended_at": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
            "description": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the entry's current task selectable even if it is done by now.
        self.fields["task"].queryset = open_tasks(include_pk=self.instance.task_id if self.instance.pk else None)
        self.fields["ended_at"].required = True

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("started_at"), cleaned.get("ended_at")
        if start and end and end <= start:
            self.add_error("ended_at", "Das Ende muss nach dem Beginn liegen.")
        return cleaned
