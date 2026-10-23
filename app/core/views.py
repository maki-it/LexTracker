from datetime import datetime, time, timedelta

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.templatetags.static import static
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from django.views.generic import RedirectView

from accounts.models import User
from core.forms import AppSettingsForm
from core.models import AppSettings
from tracking.forms import task_choices
from tracking.models import TimeEntry
from tracking.queries import entry_filter


@require_GET
async def dashboard(request: HttpRequest) -> HttpResponse:
    today_start = datetime.combine(timezone.localdate(), time.min, tzinfo=timezone.get_current_timezone())
    active_filter = await entry_filter(request)
    today_entries = [
        e
        async for e in TimeEntry.objects.filter(
            user=request.user, started_at__gte=today_start, **active_filter["filters"]
        )
        .select_related("task", "task__project", "task__project__customer")
        .order_by("started_at")
    ]
    return render(
        request,
        "core/dashboard.html",
        {
            "tasks": [t async for t in task_choices(request.user)],
            "today_entries": today_entries,
            "today_total": sum((e.duration for e in today_entries), timedelta()),
            "filter_label": active_filter["label"],
            "filter_base": "",
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


@require_http_methods(["GET", "POST"])
async def app_settings(request: HttpRequest) -> HttpResponse:
    if request.user.role != User.Role.ADMIN:
        raise PermissionDenied
    form = AppSettingsForm(request.POST or None, instance=await AppSettings.aload())
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        # Save only the fields on the page; the import writes its status columns itself.
        await form.instance.asave(update_fields=list(form.fields))
        messages.success(request, "Einstellungen gespeichert.")
        return redirect("core:settings")
    current = form.instance
    sync_jobs = [
        {
            "interval": form["lexware_sync_interval"],
            "start": form["lexware_sync_from"],
            "end": form["lexware_sync_until"],
            "last_run": current.lexware_synced_at,
            "status": current.lexware_sync_status,
            "failed": current.lexware_sync_failed,
        },
        {
            "interval": form["invoice_sync_interval"],
            "start": form["invoice_sync_from"],
            "end": form["invoice_sync_until"],
            "last_run": current.invoices_synced_at,
            "status": current.invoices_sync_status,
            "failed": current.invoices_sync_failed,
        },
    ]
    return render(request, "core/settings.html", {"form": form, "sync_jobs": sync_jobs})


class FaviconView(RedirectView):
    """Redirect /favicon.ico to the static file.

    The URL is looked up per request: in production it carries a hash from the
    staticfiles manifest, which does not exist yet while the Docker image runs
    collectstatic.
    """

    permanent = True

    def get_redirect_url(self, *args, **kwargs) -> str:
        return static("img/favicon.ico")
