from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.dialogs import in_dialog
from core.shortcuts import arender
from projects.models import Task
from tracking.forms import TimeEntryForm, open_tasks
from tracking.models import TimeEntry
from tracking.queries import entry_filter
from tracking.services import start_timer, stop_timer

TIMER_CHANGED = "timer-changed"


def _entries(user):
    return TimeEntry.objects.filter(user=user).select_related("task", "task__project", "task__project__customer")


async def _running_entry(user) -> TimeEntry | None:
    return await _entries(user).filter(ended_at__isnull=True).afirst()


def _timer_response(request: HttpRequest, entry: TimeEntry | None) -> HttpResponse:
    response = render(request, "tracking/_timer.html", {"running_entry": entry})
    # Lets other parts of the page (e.g. today's entries) reload themselves.
    response["HX-Trigger"] = TIMER_CHANGED
    return response


@require_GET
async def timer(request: HttpRequest) -> HttpResponse:
    """The running-timer badge in the navigation bar."""
    return render(request, "tracking/_timer.html", {"running_entry": await _running_entry(request.user)})


@require_http_methods(["GET", "POST"])
async def timer_start(request: HttpRequest) -> HttpResponse:
    """GET: the start form (opened in the dialog from the sidebar). POST: start the timer."""
    if request.method == "GET":
        return render(request, "tracking/timer_start.html", {"tasks": [t async for t in open_tasks(request.user)]})
    try:
        task = await open_tasks(request.user).aget(pk=int(request.POST.get("task", "")))
    except ValueError, Task.DoesNotExist:
        raise Http404 from None
    await sync_to_async(start_timer)(request.user, task, request.POST.get("description", "").strip())
    if not request.htmx:
        return redirect(request.POST.get("next") or "core:dashboard")
    if in_dialog(request):
        # The sidebar timer and today's entries reload themselves; the dialog closes.
        response = HttpResponse()
        response["HX-Trigger"] = f"{TIMER_CHANGED}, close-dialog"
        response["HX-Reswap"] = "none"
        return response
    return _timer_response(request, await _running_entry(request.user))


@require_POST
async def timer_stop(request: HttpRequest) -> HttpResponse:
    await sync_to_async(stop_timer)(request.user)
    if not request.htmx:
        return redirect(request.POST.get("next") or "core:dashboard")
    return _timer_response(request, None)


def _filter_query(request: HttpRequest) -> str:
    """``&kunde=…`` or ``&projekt=…`` of the current filter, to append to other links."""
    params = {k: request.GET[k] for k in ("kunde", "projekt") if request.GET.get(k, "").isdigit()}
    return f"&{urlencode(params)}" if params else ""


def _parse_week(value: str | None) -> date:
    """Monday of the ISO week given as "2026-W43", or of the current week."""
    try:
        year, week = value.split("-W")
        return date.fromisocalendar(int(year), int(week), 1)
    except AttributeError, ValueError:
        today = timezone.localdate()
        return today - timedelta(days=today.weekday())


def _week_param(monday: date) -> str:
    year, week, _ = monday.isocalendar()
    return f"{year}-W{week:02d}"


@require_GET
async def entry_list(request: HttpRequest) -> HttpResponse:
    monday = _parse_week(request.GET.get("woche"))
    tz = timezone.get_current_timezone()
    start = datetime.combine(monday, time.min, tzinfo=tz)
    active_filter = await entry_filter(request)
    entries = [
        e
        async for e in _entries(request.user).filter(
            started_at__gte=start, started_at__lt=start + timedelta(days=7), **active_filter["filters"]
        )
    ]

    days = []
    for offset in range(7):
        day = monday + timedelta(days=offset)
        day_entries = sorted(
            (e for e in entries if timezone.localtime(e.started_at).date() == day), key=lambda e: e.started_at
        )
        days.append({"date": day, "entries": day_entries, "total": sum((e.duration for e in day_entries), timedelta())})
    # Bar length per day in the week strip, relative to the longest day.
    longest = max(d["total"] for d in days) or timedelta(hours=1)
    today = timezone.localdate()
    for d in days:
        d["share"] = round(d["total"] / longest * 100)
        d["is_today"] = d["date"] == today

    return render(
        request,
        "tracking/list.html",
        {
            "days": days,
            "monday": monday,
            "sunday": monday + timedelta(days=6),
            "week_total": sum((d["total"] for d in days), timedelta()),
            "prev_week": _week_param(monday - timedelta(days=7)),
            "next_week": _week_param(monday + timedelta(days=7)),
            "this_week": _week_param(monday),
            "filter_label": active_filter["label"],
            # Filter links keep the week; the week links keep the filter.
            "filter_base": f"woche={_week_param(monday)}&",
            "filter_query": _filter_query(request),
        },
    )


async def _get_entry(request: HttpRequest, pk: int) -> TimeEntry:
    try:
        return await _entries(request.user).aget(pk=pk)
    except TimeEntry.DoesNotExist as exc:
        raise Http404 from exc


def _back_to_week(entry: TimeEntry) -> str:
    return f"{reverse('tracking:list')}?woche={_week_param(timezone.localtime(entry.started_at).date())}"


@require_http_methods(["GET", "POST"])
async def entry_form(request: HttpRequest, pk: int | None = None) -> HttpResponse:
    entry = await _get_entry(request, pk) if pk else TimeEntry(user=request.user)
    initial = None
    if not pk:
        now = timezone.localtime().replace(second=0, microsecond=0)
        initial = {"started_at": now - timedelta(hours=1), "ended_at": now, "task": request.GET.get("aufgabe")}
    form = TimeEntryForm(request.POST or None, instance=entry, initial=initial, user=request.user)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        entry = await sync_to_async(form.save)()
        messages.success(request, "Zeiteintrag gespeichert.")
        return redirect(_back_to_week(entry))
    return await arender(request, "tracking/form.html", {"form": form, "entry": entry if pk else None})


@require_POST
async def entry_delete(request: HttpRequest, pk: int) -> HttpResponse:
    entry = await _get_entry(request, pk)
    back = _back_to_week(entry)
    await entry.adelete()
    messages.success(request, "Zeiteintrag gelöscht.")
    return redirect(back)
