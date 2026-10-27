from django import forms
from django.db import transaction
from django.utils.translation import gettext_lazy as _

from core.forms import MARKDOWN_HELP, MarkdownTextarea, StyledFormMixin
from customers.models import Customer
from projects.models import Project, Task, TaskTemplate


class ProjectForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Project
        fields = ["customer", "name", "status", "description", "hourly_rate", "budget_hours", "start_date", "end_date"]
        widgets = {
            "description": MarkdownTextarea(attrs={"rows": 3}),
            "start_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "end_date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }
        help_texts = {"description": MARKDOWN_HELP}

    templates = forms.ModelMultipleChoiceField(
        label=_("Aufgaben aus Vorlagen"),
        queryset=TaskTemplate.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    def __init__(self, *args, offer_templates: bool = False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(is_archived=False)
        # Offered when creating a project; afterwards templates are added on the project page.
        if not offer_templates:
            del self.fields["templates"]

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", _("Das Ende liegt vor dem Start."))
        return cleaned

    @transaction.atomic
    def save(self, commit=True):
        project = super().save(commit)
        if commit and self.cleaned_data.get("templates"):
            Task.objects.bulk_create(t.to_task(project) for t in self.cleaned_data["templates"])
        return project


class TaskForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ["name", "is_billable", "hourly_rate", "estimated_hours"]


class TaskEditForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Task
        fields = ["name", "status", "description", "hourly_rate", "estimated_hours", "is_billable"]
        widgets = {"description": MarkdownTextarea(attrs={"rows": 3})}
        help_texts = {"description": MARKDOWN_HELP}


class TaskTemplateForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = TaskTemplate
        fields = ["name", "description", "hourly_rate", "estimated_hours", "is_billable"]
        widgets = {"description": MarkdownTextarea(attrs={"rows": 3})}
        help_texts = {"description": MARKDOWN_HELP}
