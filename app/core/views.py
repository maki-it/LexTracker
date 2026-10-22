from asgiref.sync import sync_to_async
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET

from tracking.models import TimeEntry


@require_GET
async def dashboard(request: HttpRequest) -> HttpResponse:
    running = await (
        TimeEntry.objects.filter(user=request.user, ended_at__isnull=True)
        .select_related("task", "task__project", "task__project__customer")
        .afirst()
    )
    return render(request, "core/dashboard.html", {"running_entry": running})


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
