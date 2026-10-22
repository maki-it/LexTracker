from datetime import timedelta

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.shortcuts import arender
from projects.forms import ProjectForm, TaskEditForm, TaskForm
from projects.models import Project, Task
from tracking.queries import booked_time


async def _get_project(pk: int) -> Project:
    try:
        return await Project.objects.select_related("customer").aget(pk=pk)
    except Project.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def project_list(request: HttpRequest) -> HttpResponse:
    show_done = request.GET.get("abgeschlossen") == "1"
    query = request.GET.get("q", "").strip()
    projects = Project.objects.select_related("customer").annotate(booked=booked_time("tasks__time_entries__"))
    if not show_done:
        projects = projects.exclude(status=Project.Status.DONE)
    if query:
        projects = projects.filter(
            Q(name__icontains=query) | Q(customer__name__icontains=query) | Q(description__icontains=query)
        )
    context = {"projects": [p async for p in projects], "show_done": show_done, "query": query}
    return render(request, "projects/list.html", context)


@require_http_methods(["GET", "POST"])
async def project_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    project = await _get_project(pk) if pk else None
    initial = {"customer": request.GET.get("kunde")} if not project else None
    form = ProjectForm(request.POST or None, instance=project, initial=initial)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        project = await sync_to_async(form.save)()
        messages.success(request, f"Projekt „{project.name}“ gespeichert.")
        return redirect("projects:detail", pk=project.pk)
    return await arender(request, "projects/form.html", {"form": form, "project": project})


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
