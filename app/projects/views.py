from datetime import timedelta
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.dialogs import navigate
from core.paging import apage, wants_rows
from core.shortcuts import arender
from projects.forms import ProjectForm, TaskEditForm, TaskForm
from projects.models import Project, Task
from tracking.models import TimeEntry
from tracking.queries import booked_time


async def _get_project(pk: int) -> Project:
    try:
        return await Project.objects.select_related("customer").aget(pk=pk)
    except Project.DoesNotExist as exc:
        raise Http404 from exc


# The status filter on the project list: key in the URL, label, statuses. Active projects come first.
STATUS_FILTERS = {
    "aktiv": ("Aktiv", [Project.Status.ACTIVE]),
    "geplant": ("Geplant", [Project.Status.PLANNED]),
    "pausiert": ("Pausiert", [Project.Status.PAUSED]),
    "abgeschlossen": ("Abgeschlossen", [Project.Status.DONE]),
    "alle": ("Alle", list(Project.Status.values)),
}


@require_GET
async def project_list(request: HttpRequest) -> HttpResponse:
    status = request.GET.get("status", "aktiv")
    if status not in STATUS_FILTERS:
        status = "aktiv"
    query = request.GET.get("q", "").strip()
    projects = Project.objects.all()
    if query:
        projects = projects.filter(
            Q(name__icontains=query) | Q(customer__name__icontains=query) | Q(description__icontains=query)
        )
    page = await apage(
        request,
        projects.filter(status__in=STATUS_FILTERS[status][1])
        .select_related("customer")
        .annotate(booked=booked_time("tasks__time_entries__")),
    )
    if wants_rows(request):
        return render(request, "projects/_rows.html", {"page": page})
    counts = await projects.aaggregate(
        **{key: Count("pk", filter=Q(status__in=statuses)) for key, (_, statuses) in STATUS_FILTERS.items()}
    )
    q = "&" + urlencode({"q": query}) if query else ""
    context = {
        "page": page,
        "status": status,
        "query": query,
        "count": counts[status],
        "filters": [(key, label, counts[key], f"?status={key}{q}") for key, (label, _) in STATUS_FILTERS.items()],
    }
    return render(request, "projects/list.html", context)


@require_http_methods(["GET", "POST"])
async def project_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    project = await _get_project(pk) if pk else None
    initial = {"customer": request.GET.get("kunde")} if not project else None
    form = ProjectForm(request.POST or None, instance=project, initial=initial)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        project = await sync_to_async(form.save)()
        messages.success(request, f"Projekt „{project.name}“ gespeichert.")
        if pk:
            return redirect("projects:detail", pk=project.pk)
        return navigate("projects:detail", pk=project.pk)
    has_entries = project and await TimeEntry.objects.filter(task__project=project).aexists()
    return await arender(request, "projects/form.html", {"form": form, "project": project, "has_entries": has_entries})


@require_POST
async def project_delete(request: HttpRequest, pk: int) -> HttpResponse:
    project = await _get_project(pk)
    # Booked time must not disappear with its project; such projects can be closed instead.
    if await TimeEntry.objects.filter(task__project=project).aexists():
        messages.error(
            request,
            f"„{project.name}“ hat gebuchte Zeiten und kann nicht gelöscht werden. Setze es auf abgeschlossen.",
        )
        return redirect("projects:detail", pk=project.pk)
    await project.adelete()
    messages.success(request, f"Projekt „{project.name}“ gelöscht.")
    return navigate("projects:list")


async def _task_context(project: Project, task_form: TaskForm | None = None) -> dict:
    tasks = project.tasks.annotate(booked=booked_time("time_entries__")).order_by("status", "name")
    return {
        "project": project,
        "tasks": [t async for t in tasks],
        "task_form": task_form or TaskForm(),
        "status_choices": Task.Status.choices,
    }


@require_GET
async def project_detail(request: HttpRequest, pk: int) -> HttpResponse:
    project = await _get_project(pk)
    context = await _task_context(project)
    context["booked"] = sum((t.booked for t in context["tasks"] if t.booked), timedelta())
    return render(request, "projects/detail.html", context)


@require_POST
async def task_create(request: HttpRequest, pk: int) -> HttpResponse:
    """Add a task and return the refreshed task list (htmx)."""
    project = await _get_project(pk)
    form = TaskForm(request.POST)
    if await sync_to_async(form.is_valid)():
        form.instance.project = project
        await sync_to_async(form.save)()
        form = None
    return render(request, "projects/_tasks.html", await _task_context(project, form))


async def _get_task(project: Project, task_pk: int) -> Task:
    try:
        return await project.tasks.aget(pk=task_pk)
    except Task.DoesNotExist as exc:
        raise Http404 from exc


@require_http_methods(["GET", "POST"])
async def task_edit(request: HttpRequest, pk: int, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    task = await _get_task(project, task_pk)
    form = TaskEditForm(request.POST or None, instance=task)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await sync_to_async(form.save)()
        messages.success(request, f"Aufgabe „{task.name}“ gespeichert.")
        return redirect("projects:detail", pk=project.pk)
    has_entries = await task.time_entries.aexists()
    return render(
        request, "projects/task_form.html", {"form": form, "project": project, "task": task, "has_entries": has_entries}
    )


@require_POST
async def task_delete(request: HttpRequest, pk: int, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    task = await _get_task(project, task_pk)
    # Booked time must not disappear with its task; such tasks can be set to done instead.
    if await task.time_entries.aexists():
        messages.error(
            request, f"„{task.name}“ hat gebuchte Zeiten und kann nicht gelöscht werden. Setze sie auf erledigt."
        )
        return redirect("projects:task_edit", pk=project.pk, task_pk=task.pk)
    await task.adelete()
    messages.success(request, f"Aufgabe „{task.name}“ gelöscht.")
    return redirect("projects:detail", pk=project.pk)


@require_POST
async def task_set_status(request: HttpRequest, pk: int, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    status = request.POST.get("status")
    if status in Task.Status.values:
        await Task.objects.filter(pk=task_pk, project=project).aupdate(status=status)
    return render(request, "projects/_tasks.html", await _task_context(project))
