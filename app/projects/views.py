from datetime import timedelta

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.shortcuts import arender
from projects.forms import ProjectForm, TaskForm
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
    projects = Project.objects.select_related("customer").annotate(booked=booked_time("tasks__time_entries__"))
    if not show_done:
        projects = projects.exclude(status=Project.Status.DONE)
    return render(request, "projects/list.html", {"projects": [p async for p in projects], "show_done": show_done})


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


@require_POST
async def task_set_status(request: HttpRequest, pk: int, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    status = request.POST.get("status")
    if status in Task.Status.values:
        await Task.objects.filter(pk=task_pk, project=project).aupdate(status=status)
    return render(request, "projects/_tasks.html", await _task_context(project))
