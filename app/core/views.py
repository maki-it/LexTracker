from datetime import datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from tracking.forms import open_tasks
from tracking.models import TimeEntry


@require_GET
async def dashboard(request: HttpRequest) -> HttpResponse:
    today_start = datetime.combine(timezone.localdate(), time.min, tzinfo=timezone.get_current_timezone())
    today_entries = [
        e
        async for e in TimeEntry.objects.filter(user=request.user, started_at__gte=today_start)
        .select_related("task", "task__project", "task__project__customer")
        .order_by("started_at")
    ]
    return render(
        request,
        "core/dashboard.html",
        {
            "tasks": [t async for t in open_tasks()],
            "today_entries": today_entries,
            "today_total": sum((e.duration for e in today_entries), timedelta()),
        },
    )


def _database_ok() -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        return cursor.fetchone() == (1,)


@require_GET
async def health(request: HttpRequest) -> JsonResponse:
    try:
        ok = await sync_to_async(_database_ok)()
    except Exception:
        ok = False
    return JsonResponse({"status": "ok" if ok else "error"}, status=200 if ok else 503)
