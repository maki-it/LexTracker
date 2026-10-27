"""The Markdown texts whose checklists can be ticked on the page, see ``core.views.markdown_toggle``."""

from dataclasses import dataclass

from django.db.models import Model

from customers.models import Customer
from projects.models import Project, Task, TaskTemplate
from reminders.models import Reminder


@dataclass(frozen=True)
class Target:
    model: type[Model]
    field: str
    # The field with the user the object belongs to. Only that user may change it. Empty: shared by all users.
    owner: str = ""


# By the name in the URL.
TARGETS = {
    "customer": Target(Customer, "notes"),
    "project": Target(Project, "description"),
    "task": Target(Task, "description"),
    "task-template": Target(TaskTemplate, "description"),
    "reminder": Target(Reminder, "notes", owner="user"),
}
