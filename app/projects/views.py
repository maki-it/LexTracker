from datetime import timedelta
from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.dialogs import navigate
from core.filters import filter_pills, selected_filters
from core.ids import parse_uuid
from core.paging import apage, wants_rows
from core.shortcuts import arender
from projects.forms import ProjectForm, TaskEditForm, TaskForm, TaskTemplateForm
from projects.models import Project, Task, TaskTemplate
from tracking.models import TimeEntry
from tracking.queries import booked_time


async def _get_project(pk: UUID) -> Project:
    try:
        return await Project.objects.select_related("customer").aget(pk=pk)
    except Project.DoesNotExist as exc:
        raise Http404 from exc


# The status filters on the project list: key in the URL, label, statuses. Active projects come first.
# They can be combined, except "Alle".
STATUS_FILTERS = {
    "active": ("Aktiv", [Project.Status.ACTIVE]),
    "planned": ("Geplant", [Project.Status.PLANNED]),
    "paused": ("Pausiert", [Project.Status.PAUSED]),
    "done": ("Abgeschlossen", [Project.Status.DONE]),
    "all": ("Alle", list(Project.Status.values)),
}


@require_GET
async def project_list(request: HttpRequest) -> HttpResponse:
    selected = selected_filters(request, STATUS_FILTERS)
    if "all" in selected:
        selected = ["all"]
    elif not selected:
        selected = ["active"]
    query = request.GET.get("q", "").strip()
    projects = Project.objects.all()
    if query:
        projects = projects.filter(
            Q(name__icontains=query) | Q(customer__name__icontains=query) | Q(description__icontains=query)
        )
    page = await apage(
        request,
        projects.filter(status__in=[s for key in selected for s in STATUS_FILTERS[key][1]])
        .select_related("customer")
        .annotate(booked=booked_time("tasks__time_entries__")),
    )
    if wants_rows(request):
        return render(request, "projects/_rows.html", {"page": page})
    counts = await projects.aaggregate(
        **{key: Count("pk", filter=Q(status__in=statuses)) for key, (_label, statuses) in STATUS_FILTERS.items()}
    )
    context = {
        "page": page,
        "statuses": selected,
        "query": query,
        "count": sum(counts[key] for key in selected),
        "selected_labels": [STATUS_FILTERS[key][0] for key in selected],
        "filters": filter_pills(request, STATUS_FILTERS, counts, selected, exclusive="all", when_empty=["all"]),
    }
    return render(request, "projects/list.html", context)


@require_http_methods(["GET", "POST"])
async def project_form(request: HttpRequest, pk: UUID | None = None) -> HttpResponse:
    project = await _get_project(pk) if pk else None
    initial = {"customer": request.GET.get("customer")} if not project else None
    offer_templates = not project and await TaskTemplate.objects.aexists()
    form = ProjectForm(request.POST or None, instance=project, initial=initial, offer_templates=offer_templates)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        project = await sync_to_async(form.save)()
        messages.success(request, _("Projekt „%(name)s“ gespeichert.") % {"name": project.name})
        if pk:
            return redirect("projects:detail", pk=project.pk)
        return navigate("projects:detail", pk=project.pk)
    has_entries = project and await TimeEntry.objects.filter(task__project=project).aexists()
    return await arender(request, "projects/form.html", {"form": form, "project": project, "has_entries": has_entries})


@require_POST
async def project_delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    project = await _get_project(pk)
    # Booked time must not disappear with its project; such projects can be closed instead.
    if await TimeEntry.objects.filter(task__project=project).aexists():
        messages.error(
            request,
            _("„%(name)s“ hat gebuchte Zeiten und kann nicht gelöscht werden. Setze es auf abgeschlossen.")
            % {"name": project.name},
        )
        return redirect("projects:detail", pk=project.pk)
    await project.adelete()
    messages.success(request, _("Projekt „%(name)s“ gelöscht.") % {"name": project.name})
    return navigate("projects:list")


async def _task_context(project: Project, task_form: TaskForm | None = None) -> dict:
    tasks = [t async for t in project.tasks.annotate(booked=booked_time("time_entries__")).order_by("status", "name")]
    task_names = {t.name for t in tasks}
    return {
        "project": project,
        "tasks": tasks,
        "task_form": task_form or TaskForm(),
        "status_choices": Task.Status.choices,
        # Templates already in the project are shown, but cannot be added a second time.
        "templates": [(t, t.name in task_names) async for t in TaskTemplate.objects.all()],
    }


@require_GET
async def project_detail(request: HttpRequest, pk: UUID) -> HttpResponse:
    project = await _get_project(pk)
    context = await _task_context(project)
    context["booked"] = sum((t.booked for t in context["tasks"] if t.booked), timedelta())
    return render(request, "projects/detail.html", context)


@require_POST
async def task_create(request: HttpRequest, pk: UUID) -> HttpResponse:
    """Add a task and return the refreshed task list (htmx)."""
    project = await _get_project(pk)
    form = TaskForm(request.POST)
    if await sync_to_async(form.is_valid)():
        form.instance.project = project
        await sync_to_async(form.save)()
        form = None
    return render(request, "projects/_tasks.html", await _task_context(project, form))


@require_POST
async def task_from_templates(request: HttpRequest, pk: UUID) -> HttpResponse:
    """Add a task for each chosen template and return the refreshed task list (htmx)."""
    project = await _get_project(pk)
    ids = [i for value in request.POST.getlist("template") if (i := parse_uuid(value))]
    existing = {name async for name in project.tasks.values_list("name", flat=True)}
    new_tasks = [t.to_task(project) async for t in TaskTemplate.objects.filter(pk__in=ids) if t.name not in existing]
    await Task.objects.abulk_create(new_tasks)
    return render(request, "projects/_tasks.html", await _task_context(project))


async def _get_task(project: Project, task_pk: UUID) -> Task:
    try:
        return await project.tasks.aget(pk=task_pk)
    except Task.DoesNotExist as exc:
        raise Http404 from exc


@require_http_methods(["GET", "POST"])
async def task_edit(request: HttpRequest, pk: UUID, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    task = await _get_task(project, task_pk)
    form = TaskEditForm(request.POST or None, instance=task)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await sync_to_async(form.save)()
        messages.success(request, _("Aufgabe „%(name)s“ gespeichert.") % {"name": task.name})
        return redirect("projects:detail", pk=project.pk)
    has_entries = await task.time_entries.aexists()
    return render(
        request, "projects/task_form.html", {"form": form, "project": project, "task": task, "has_entries": has_entries}
    )


@require_POST
async def task_save_as_template(request: HttpRequest, pk: UUID, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    task = await _get_task(project, task_pk)
    if await TaskTemplate.objects.filter(name=task.name).aexists():
        messages.error(request, _("Es gibt schon eine Vorlage „%(name)s“.") % {"name": task.name})
    else:
        await TaskTemplate.from_task(task).asave()
        messages.success(request, _("„%(name)s“ als Vorlage gespeichert.") % {"name": task.name})
    return redirect("projects:detail", pk=project.pk)


@require_POST
async def task_delete(request: HttpRequest, pk: UUID, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    task = await _get_task(project, task_pk)
    # Booked time must not disappear with its task; such tasks can be set to done instead.
    if await task.time_entries.aexists():
        messages.error(
            request,
            _("„%(name)s“ hat gebuchte Zeiten und kann nicht gelöscht werden. Setze sie auf erledigt.")
            % {"name": task.name},
        )
        return redirect("projects:task_edit", pk=project.pk, task_pk=task.pk)
    await task.adelete()
    messages.success(request, _("Aufgabe „%(name)s“ gelöscht.") % {"name": task.name})
    return redirect("projects:detail", pk=project.pk)


@require_POST
async def task_set_status(request: HttpRequest, pk: UUID, task_pk: int) -> HttpResponse:
    project = await _get_project(pk)
    status = request.POST.get("status")
    if status in Task.Status.values:
        await Task.objects.filter(pk=task_pk, project=project).aupdate(status=status)
    return render(request, "projects/_tasks.html", await _task_context(project))


@require_GET
async def template_list(request: HttpRequest) -> HttpResponse:
    context = {"templates": [t async for t in TaskTemplate.objects.all()]}
    return render(request, "projects/template_list.html", context)


async def _get_template(pk: UUID) -> TaskTemplate:
    try:
        return await TaskTemplate.objects.aget(pk=pk)
    except TaskTemplate.DoesNotExist as exc:
        raise Http404 from exc


@require_http_methods(["GET", "POST"])
async def template_form(request: HttpRequest, pk: UUID | None = None) -> HttpResponse:
    template = await _get_template(pk) if pk else None
    form = TaskTemplateForm(request.POST or None, instance=template)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        template = await sync_to_async(form.save)()
        messages.success(request, _("Vorlage „%(name)s“ gespeichert.") % {"name": template.name})
        return redirect("projects:templates")
    return render(request, "projects/template_form.html", {"form": form, "template": template})


@require_POST
async def template_delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    # Tasks created from the template are copies and stay untouched.
    template = await _get_template(pk)
    await template.adelete()
    messages.success(request, _("Vorlage „%(name)s“ gelöscht.") % {"name": template.name})
    return redirect("projects:templates")
