"""The tools an AI agent can call. Each one acts as the user the API token belongs to."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.models import AppSettings
from projects.models import Project, Task
from tracking import services
from tracking.forms import bookable_projects, open_tasks
from tracking.models import TimeEntry


class ToolError(Exception):
    """A mistake the agent can fix, such as an unknown id. Reported back as the tool result."""


@dataclass
class Tool:
    name: str
    description: str
    properties: dict
    required: list[str]
    handler: Callable[..., object]

    @property
    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {"type": "object", "properties": self.properties, "required": self.required},
        }


TOOLS: dict[str, Tool] = {}


def tool(description: str, properties: dict | None = None, required: list[str] | None = None):
    def register(handler):
        TOOLS[handler.__name__] = Tool(handler.__name__, description, properties or {}, required or [], handler)
        return handler

    return register


def _local(value: datetime | None) -> str | None:
    return timezone.localtime(value).isoformat(timespec="minutes") if value else None


def _minutes(delta: timedelta) -> int:
    return round(delta.total_seconds() / 60)


def _task(task: Task) -> dict:
    return {
        "id": task.pk,
        "name": task.name,
        "status": task.get_status_display(),
        "project": task.project.name,
        "project_id": task.project_id,
        "customer": task.project.customer.name,
    }


def _entry(entry: TimeEntry) -> dict:
    return {
        "id": entry.pk,
        "task": _task(entry.task),
        "description": entry.description,
        "start": _local(entry.started_at),
        "end": _local(entry.ended_at),
        "minutes": _minutes(entry.duration),
        "billable": entry.is_billable,
        "running": entry.is_running,
    }


def _get_task(user, task_id) -> Task:
    try:
        return open_tasks(user).get(pk=int(task_id))
    except Task.DoesNotExist, TypeError, ValueError:
        raise ToolError(
            f"Keine offene Aufgabe mit der ID {task_id}. Finde die richtige mit find_tasks oder lege sie an."
        ) from None


def _parse_datetime(value: str, field: str) -> datetime:
    parsed = parse_datetime(value) if isinstance(value, str) else None
    if parsed is None:
        raise ToolError(f"{field}: erwartet wird ein Zeitpunkt nach ISO 8601, z. B. 2026-10-22T09:30.")
    # Without a time zone, the time is local time.
    return timezone.make_aware(parsed) if timezone.is_naive(parsed) else parsed


def _parse_date(value: str | None, field: str, default: date) -> date:
    if not value:
        return default
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is None:
        raise ToolError(f"{field}: erwartet wird ein Datum wie 2026-10-22.")
    return parsed


@tool(
    "Lists active projects with their customer and open tasks. Use it to find the task to book time on.",
    {"query": {"type": "string", "description": "Only projects whose name or customer contains this text."}},
)
def list_projects(user, query: str = ""):
    projects = bookable_projects(user).exclude(status=Project.Status.DONE).select_related("customer")
    if query:
        projects = projects.filter(Q(name__icontains=query) | Q(customer__name__icontains=query))
    tasks_by_project: dict[int, list] = {}
    for task in open_tasks(user).filter(project__in=projects):
        tasks_by_project.setdefault(task.project_id, []).append({"id": task.pk, "name": task.name})
    return [
        {
            "id": p.pk,
            "name": p.name,
            "customer": p.customer.name,
            "status": p.get_status_display(),
            "tasks": tasks_by_project.get(p.pk, []),
        }
        for p in projects
    ]


@tool(
    "Searches open tasks by the name of the task, its project or its customer.",
    {"query": {"type": "string", "description": "Text to search for, e.g. a project or task name."}},
    ["query"],
)
def find_tasks(user, query: str):
    words = query.split()
    tasks = open_tasks(user)
    for word in words:
        tasks = tasks.filter(
            Q(name__icontains=word) | Q(project__name__icontains=word) | Q(project__customer__name__icontains=word)
        )
    return [_task(t) for t in tasks[:50]]


@tool(
    "Creates a task in a project, for work that has no task yet.",
    {
        "project_id": {"type": "integer"},
        "name": {"type": "string", "description": "Short name of the task."},
        "description": {"type": "string"},
    },
    ["project_id", "name"],
)
def create_task(user, project_id: int, name: str, description: str = ""):
    name = (name or "").strip()
    if not name:
        raise ToolError("name darf nicht leer sein.")
    try:
        project = bookable_projects(user).exclude(status=Project.Status.DONE).get(pk=int(project_id))
    except Project.DoesNotExist, TypeError, ValueError:
        raise ToolError(f"Kein aktives Projekt mit der ID {project_id}. Siehe list_projects.") from None
    task = Task.objects.create(project=project, name=name[:255], description=description or "")
    return _task(Task.objects.select_related("project__customer").get(pk=task.pk))


@tool("Shows the running timer, if there is one.")
def get_running_timer(user):
    entry = TimeEntry.objects.filter(user=user, ended_at__isnull=True).select_related("task__project__customer")
    entry = entry.first()
    return {"running": False} if entry is None else _entry(entry)


@tool(
    "Starts the timer on a task. A timer that is already running is stopped and saved first.",
    {
        "task_id": {"type": "integer"},
        "description": {"type": "string", "description": "What is being worked on."},
    },
    ["task_id"],
)
def start_timer(user, task_id: int, description: str = ""):
    task = _get_task(user, task_id)
    with transaction.atomic():
        stopped = services.stop_timer(user)
        entry = services.start_timer(user, task, description or "")
    result = {"started": _entry(entry)}
    if stopped:
        result["stopped"] = _entry(stopped)
    return result


@tool(
    "Stops the running timer and saves the time. Timers under 30 seconds are discarded.",
    {"description": {"type": "string", "description": "Replaces the description, e.g. with a summary of the work."}},
)
def stop_timer(user, description: str | None = None):
    with transaction.atomic():
        if description is not None:
            TimeEntry.objects.filter(user=user, ended_at__isnull=True).update(description=description)
        running = TimeEntry.objects.filter(user=user, ended_at__isnull=True).exists()
        entry = services.stop_timer(user)
    if entry is None:
        return {"stopped": False, "reason": "Kürzer als 30 Sekunden, verworfen." if running else "Kein Timer lief."}
    return {"stopped": True, "entry": _entry(entry)}


@tool(
    "Books time on a task after the fact. Give either end or duration_minutes. "
    "Times without a time zone are local time. The end is rounded as set in LexTracker.",
    {
        "task_id": {"type": "integer"},
        "start": {"type": "string", "description": "ISO 8601, e.g. 2026-10-22T09:30"},
        "end": {"type": "string", "description": "ISO 8601"},
        "duration_minutes": {"type": "integer", "minimum": 1},
        "description": {"type": "string"},
        "billable": {"type": "boolean", "description": "Defaults to the task's setting."},
    },
    ["task_id", "start"],
)
def add_time_entry(user, task_id, start, end=None, duration_minutes=None, description="", billable=None):
    task = _get_task(user, task_id)
    started_at = _parse_datetime(start, "start")
    if (end is None) == (duration_minutes is None):
        raise ToolError("Gib entweder end oder duration_minutes an.")
    if end is not None:
        ended_at = _parse_datetime(end, "end")
    else:
        if not isinstance(duration_minutes, int) or duration_minutes < 1:
            raise ToolError("duration_minutes muss eine ganze Zahl ab 1 sein.")
        ended_at = started_at + timedelta(minutes=duration_minutes)
    if ended_at <= started_at:
        raise ToolError("Das Ende muss nach dem Beginn liegen.")
    if ended_at > timezone.now() + timedelta(minutes=5):
        raise ToolError("Zeiten in der Zukunft können nicht gebucht werden.")
    ended_at = services.rounded_end(started_at, ended_at, AppSettings.load().time_rounding)
    entry = TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=started_at,
        ended_at=ended_at,
        description=description or "",
        is_billable=task.is_billable if billable is None else bool(billable),
    )
    entry.task = task
    return _entry(entry)


@tool(
    "Lists booked time, newest first, with the total. Defaults to the last 7 days.",
    {
        "date_from": {"type": "string", "description": "First day, e.g. 2026-10-01"},
        "date_to": {"type": "string", "description": "Last day, inclusive"},
        "task_id": {"type": "integer"},
    },
)
def list_time_entries(user, date_from=None, date_to=None, task_id=None):
    today = timezone.localdate()
    first = _parse_date(date_from, "date_from", today - timedelta(days=6))
    last = _parse_date(date_to, "date_to", today)
    entries = TimeEntry.objects.filter(
        user=user, started_at__date__gte=first, started_at__date__lte=last
    ).select_related("task__project__customer")
    if task_id is not None:
        entries = entries.filter(task_id=task_id)
    entries = list(entries[:200])
    return {
        "from": first.isoformat(),
        "to": last.isoformat(),
        "total_minutes": sum(_minutes(e.duration) for e in entries),
        "entries": [_entry(e) for e in entries],
    }
