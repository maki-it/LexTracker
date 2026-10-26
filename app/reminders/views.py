"""Reminders for customers and projects: the page with all of them and the actions on one."""

from urllib.parse import urlencode
from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.ids import parse_uuid
from core.shortcuts import arender
from customers.models import Customer
from inbox.service import aresolve
from mailer.models import MailSettings
from projects.models import Project
from reminders import queries
from reminders.forms import ReminderForm
from reminders.models import Reminder

# How many done reminders the page lists at most.
DONE_LISTED = 200

# The status filter: key in the URL, label. Only one applies; the open reminders are the default.
VIEWS = {"open": gettext_lazy("Offen"), "done": gettext_lazy("Erledigt"), "all": gettext_lazy("Alle")}
DEFAULT_VIEW = "open"


def _query_string(**params) -> str:
    return urlencode({k: v for k, v in params.items() if v})


@require_GET
async def reminder_list(request: HttpRequest) -> HttpResponse:
    view = request.GET.get("view", DEFAULT_VIEW)
    if view not in VIEWS:
        view = DEFAULT_VIEW
    mine = queries.with_context(Reminder.objects.filter(user=request.user))
    # What can be filtered by: the customers and projects the user has reminders for.
    customers = [c async for c in Customer.objects.filter(reminders__user=request.user).distinct()]
    customer = next((c for c in customers if c.pk == parse_uuid(request.GET.get("customer", ""))), None)
    projects = Project.objects.filter(reminders__user=request.user).distinct().select_related("customer")
    if customer:
        projects = projects.filter(customer=customer)
    projects = [p async for p in projects]
    project = next((p for p in projects if p.pk == parse_uuid(request.GET.get("project", ""))), None)
    if customer:
        mine = mine.filter(customer=customer)
    if project:
        mine = mine.filter(project=project)

    counts = await mine.aaggregate(
        open=Count("pk", filter=Q(done_at__isnull=True)),
        done=Count("pk", filter=Q(done_at__isnull=False)),
        all=Count("pk"),
    )
    now = timezone.now()
    open_ = [r async for r in mine.filter(done_at__isnull=True)] if view != "done" else []
    done = (
        [r async for r in mine.filter(done_at__isnull=False).order_by("-done_at")[:DONE_LISTED]]
        if view != "open"
        else []
    )
    selection = {"customer": customer.pk if customer else "", "project": project.pk if project else ""}
    context = {
        "overdue": [r for r in open_ if r.due_at and r.due_at <= now],
        "upcoming": [r for r in open_ if r.due_at and r.due_at > now],
        "undated": [r for r in open_ if not r.due_at],
        "done": done,
        "view": view,
        "view_links": [
            (key, label, counts[key], _query_string(view="" if key == DEFAULT_VIEW else key, **selection))
            for key, label in VIEWS.items()
        ],
        "view_param": "" if view == DEFAULT_VIEW else view,
        "customers": customers,
        "projects": projects,
        "customer": customer,
        "project": project,
        "filtered": bool(customer or project),
        "total": counts["all"],
    }
    return render(request, "reminders/list.html", context)


async def _get_reminder(request: HttpRequest, pk: UUID) -> Reminder:
    """Only the user's own reminders: anyone else's is "not found"."""
    try:
        return await queries.with_context(Reminder.objects.filter(user=request.user)).aget(pk=pk)
    except Reminder.DoesNotExist as exc:
        raise Http404 from exc


def _back(request: HttpRequest) -> str:
    """Where an action returns to: the page it was started from, else the list."""
    target = request.POST.get("next") or request.GET.get("next") or ""
    return target if url_has_allowed_host_and_scheme(target, allowed_hosts=None) else reverse("reminders:list")


async def _scope(request: HttpRequest) -> tuple[Customer | None, Project | None]:
    """The customer or project the new reminder is for, from the link that opened the form."""
    if project_id := parse_uuid(request.GET.get("project")):
        try:
            return None, await Project.objects.select_related("customer").aget(pk=project_id)
        except Project.DoesNotExist as exc:
            raise Http404 from exc
    if customer_id := parse_uuid(request.GET.get("customer")):
        try:
            return await Customer.objects.aget(pk=customer_id), None
        except Customer.DoesNotExist as exc:
            raise Http404 from exc
    return None, None


@require_http_methods(["GET", "POST"])
async def reminder_form(request: HttpRequest, pk: UUID | None = None) -> HttpResponse:
    reminder = await _get_reminder(request, pk) if pk else None
    customer = project = None
    if reminder is None:
        customer, project = await _scope(request)
    options = {}
    if reminder is None and not (customer or project):
        options = {
            "customers": [c async for c in Customer.objects.filter(is_archived=False)],
            "projects": [
                p async for p in Project.objects.select_related("customer").exclude(status=Project.Status.DONE)
            ],
        }
    form = await sync_to_async(ReminderForm)(
        request.POST or None,
        instance=reminder,
        user=request.user,
        customer=customer,
        project=project,
        mail_configured=(await MailSettings.aload()).is_configured,
        **options,
    )
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        saved = await sync_to_async(form.save)()
        if "due_at" in form.changed_data:
            # The message about the old date is obsolete.
            await aresolve(f"reminder:{saved.pk}", user=request.user)
        messages.success(request, _("Erinnerung „%(title)s“ gespeichert.") % {"title": saved.title})
        return redirect(_back(request))
    return await arender(request, "reminders/form.html", {"form": form, "reminder": reminder})


async def _finish(request: HttpRequest, pk: UUID, *, done: bool) -> HttpResponse:
    reminder = await _get_reminder(request, pk)
    await Reminder.objects.filter(pk=reminder.pk).aupdate(done_at=timezone.now() if done else None)
    if done:
        # Whoever has read it in the bell does not need the message anymore.
        await aresolve(f"reminder:{reminder.pk}", user=request.user)
    return redirect(_back(request))


@require_POST
async def reminder_done(request: HttpRequest, pk: UUID) -> HttpResponse:
    return await _finish(request, pk, done=True)


@require_POST
async def reminder_reopen(request: HttpRequest, pk: UUID) -> HttpResponse:
    return await _finish(request, pk, done=False)


@require_POST
async def reminder_delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    reminder = await _get_reminder(request, pk)
    await aresolve(f"reminder:{reminder.pk}", user=request.user)
    await reminder.adelete()
    messages.success(request, _("Erinnerung „%(title)s“ gelöscht.") % {"title": reminder.title})
    return redirect(_back(request))
