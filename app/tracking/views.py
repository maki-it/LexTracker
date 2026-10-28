from collections import Counter
from datetime import date, datetime, time, timedelta
from urllib.parse import urlencode
from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.dialogs import in_dialog
from core.ids import parse_uuid
from core.models import AppSettings
from core.shortcuts import arender
from projects.models import Task
from tracking.forms import TimeEntryForm, open_tasks, recent_tasks, search_tasks, task_choices
from tracking.models import TimeEntry
from tracking.queries import entry_filter
from tracking.services import start_timer, stop_timer

TIMER_CHANGED = "timer-changed"


def _entries(user):
    return TimeEntry.objects.filter(user=user).select_related(
        "task", "task__project", "task__project__customer", "invoice"
    )


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
        # The most recently used task is preselected, so starting it again is one click.
        context = {
            "last_task": await task_choices(request.user).afirst(),
            "recent_tasks": [t async for t in recent_tasks(request.user)],
        }
        return render(request, "tracking/timer_start.html", context)
    try:
        task = await open_tasks(request.user).aget(pk=parse_uuid(request.POST.get("task", "")))
    except Task.DoesNotExist:
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


@require_GET
async def task_search(request: HttpRequest) -> HttpResponse:
    """Suggestions for the task search field (tracking/_task_search.html)."""
    tasks = [t async for t in search_tasks(request.user, request.GET.get("q", ""))]
    return render(request, "tracking/_task_results.html", {"tasks": tasks})


@require_POST
async def timer_stop(request: HttpRequest) -> HttpResponse:
    await sync_to_async(stop_timer)(request.user)
    if not request.htmx:
        return redirect(request.POST.get("next") or "core:dashboard")
    return _timer_response(request, None)


def _filter_query(request: HttpRequest) -> str:
    """``&customer=…`` or ``&project=…`` of the current filter, to append to other links."""
    params = {k: request.GET[k] for k in ("customer", "project") if parse_uuid(request.GET.get(k, ""))}
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
    year, week, _weekday = monday.isocalendar()
    return f"{year}-W{week:02d}"


def _parse_month(value: str | None, fallback: date) -> date:
    """First day of the month given as "2026-10", or of ``fallback``."""
    try:
        year, month = value.split("-")
        if not 1900 <= int(year) <= 2100:
            raise ValueError(year)
        return date(int(year), int(month), 1)
    except AttributeError, ValueError:
        return fallback.replace(day=1)


def _dots(entries: int) -> int:
    """Dots under a day in the week picker: one entry, two or three, four or more."""
    return 0 if entries == 0 else 1 if entries == 1 else 2 if entries < 4 else 3


@require_GET
async def entry_list(request: HttpRequest) -> HttpResponse:
    monday = _parse_week(request.GET.get("week"))
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
            "is_this_week": monday == today - timedelta(days=today.weekday()),
            "filter_label": active_filter["label"],
            # Filter links keep the week; the week links keep the filter.
            "filter_base": f"week={_week_param(monday)}&",
            "filter_query": _filter_query(request),
        },
    )


@require_GET
async def week_picker(request: HttpRequest) -> HttpResponse:
    """The month calendar of the week picker (tracking/_week_picker.html), loaded when it is first opened.

    ``?week=`` is the week shown in the list and ``?month=`` the month to show. A day carries dots for the
    entries of the active customer or project filter, so the calendar matches the list.
    """
    selected = _parse_week(request.GET.get("week"))
    month = _parse_month(request.GET.get("month"), selected + timedelta(days=3))
    next_month = (month + timedelta(days=31)).replace(day=1)
    # Always six whole weeks from the Monday of the first day, so the picker keeps its height from month to month.
    first_monday = month - timedelta(days=month.weekday())
    end = first_monday + timedelta(weeks=6)

    tz = timezone.get_current_timezone()
    active_filter = await entry_filter(request)
    started = TimeEntry.objects.filter(
        user=request.user,
        started_at__gte=datetime.combine(first_monday, time.min, tzinfo=tz),
        started_at__lt=datetime.combine(end, time.min, tzinfo=tz),
        **active_filter["filters"],
    ).values_list("started_at", flat=True)
    per_day = Counter([timezone.localtime(s).date() async for s in started])

    today = timezone.localdate()
    weeks = []
    for monday in (first_monday + timedelta(days=n) for n in range(0, (end - first_monday).days, 7)):
        days = [monday + timedelta(days=n) for n in range(7)]
        weeks.append(
            {
                "param": _week_param(monday),
                "number": monday.isocalendar().week,
                "monday": monday,
                "sunday": monday + timedelta(days=6),
                "is_selected": monday == selected,
                "days": [
                    {
                        "date": d,
                        "in_month": d.month == month.month,
                        "is_today": d == today,
                        "dots": range(_dots(per_day[d])),
                    }
                    for d in days
                ],
            }
        )
    return render(
        request,
        "tracking/_week_picker.html",
        {
            "month": month,
            "prev_month": (month - timedelta(days=1)).strftime("%Y-%m"),
            "next_month": next_month.strftime("%Y-%m"),
            "selected": _week_param(selected),
            "weeks": weeks,
            "filter_query": _filter_query(request),
        },
    )


async def _get_entry(request: HttpRequest, pk: UUID) -> TimeEntry:
    try:
        return await _entries(request.user).aget(pk=pk)
    except TimeEntry.DoesNotExist as exc:
        raise Http404 from exc


def _back_to_week(entry: TimeEntry) -> str:
    return f"{reverse('tracking:list')}?week={_week_param(timezone.localtime(entry.started_at).date())}"


@require_http_methods(["GET", "POST"])
async def entry_form(request: HttpRequest, pk: UUID | None = None) -> HttpResponse:
    entry = await _get_entry(request, pk) if pk else TimeEntry(user=request.user)
    if entry.is_locked:
        return await _locked_entry(request, entry)
    initial = None
    if not pk:
        now = timezone.localtime().replace(second=0, microsecond=0)
        initial = {"started_at": now - timedelta(hours=1), "ended_at": now, "task": request.GET.get("task")}
    rounding = (await AppSettings.aload()).time_rounding
    form = TimeEntryForm(request.POST or None, instance=entry, initial=initial, user=request.user, rounding=rounding)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        entry = await sync_to_async(form.save)()
        messages.success(request, _("Zeiteintrag gespeichert."))
        return redirect(_back_to_week(entry))
    # A new entry starts as a duration ending now; an existing one, or one that did not validate, shows its times.
    mode = "duration" if request.method == "GET" and not pk else "range"
    return await arender(request, "tracking/form.html", {"form": form, "entry": entry if pk else None, "mode": mode})


async def _locked_entry(request: HttpRequest, entry: TimeEntry) -> HttpResponse:
    """A billed entry is not edited: a page says why and where it is billed, a change is refused."""
    if request.method == "POST":
        messages.error(request, _("Der Zeiteintrag ist abgerechnet und kann nicht mehr geändert werden."))
        return redirect(_back_to_week(entry))
    return await arender(request, "tracking/entry_locked.html", {"entry": entry, "invoice": entry.invoice})


@require_POST
async def entry_delete(request: HttpRequest, pk: UUID) -> HttpResponse:
    entry = await _get_entry(request, pk)
    back = _back_to_week(entry)
    if entry.is_locked:
        messages.error(request, _("Der Zeiteintrag ist abgerechnet und kann nicht gelöscht werden."))
        return redirect(back)
    await entry.adelete()
    messages.success(request, _("Zeiteintrag gelöscht."))
    return redirect(back)
