import asyncio
from datetime import datetime, time, timedelta
from pathlib import Path

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.views.generic import RedirectView

from accounts.models import User
from core import backup
from core.dialogs import navigate
from core.forms import AppSettingsForm
from core.models import AppSettings
from lexware import credentials
from lexware.forms import ApiKeyForm
from mailer.models import MailSettings, OutgoingMail
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
            # Preselected in the timer's task search, so starting it again is one click.
            "last_task": await task_choices(request.user).afirst(),
            "today_entries": today_entries,
            "today_total": sum((e.duration for e in today_entries), timedelta()),
            "filter_label": active_filter["label"],
            "filter_base": "",
            "lexware_missing": request.user.is_admin and not await credentials.ais_configured(),
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


def _require_admin(request: HttpRequest) -> None:
    if request.user.role != User.Role.ADMIN:
        raise PermissionDenied


SETTINGS_TABS = [
    ("allgemein", "Allgemein"),
    ("lexware", "Lexware"),
    ("e-mail", "E-Mail"),
    ("datensicherung", "Datensicherung"),
    ("sicherheit", "Sicherheit"),
]
_SETTINGS_TAB_FIELDS = {
    "allgemein": ["default_hourly_rate", "time_rounding"],
    "lexware": [
        "lexware_sync_interval",
        "lexware_sync_from",
        "lexware_sync_until",
        "invoice_sync_interval",
        "invoice_sync_from",
        "invoice_sync_until",
    ],
    "e-mail": [
        "weekly_report_enabled",
        "weekly_report_weekday",
        "weekly_report_time",
        "timer_reminder_hours",
        "overdue_notice",
        "overdue_notice_days",
        "invite_by_mail",
    ],
    "datensicherung": ["backup_enabled", "backup_time", "backup_keep"],
    "sicherheit": ["login_max_attempts", "login_lockout_minutes", "login_link_enabled"],
}
SETTINGS_FIELD_TABS = {field: tab for tab, fields in _SETTINGS_TAB_FIELDS.items() for field in fields}


def settings_tab(name: str | None) -> str:
    """The requested settings tab, or the first one for a missing or unknown name."""
    return name if name in dict(SETTINGS_TABS) else SETTINGS_TABS[0][0]


@require_http_methods(["GET", "POST"])
async def app_settings(request: HttpRequest) -> HttpResponse:
    _require_admin(request)
    form = AppSettingsForm(request.POST or None, instance=await AppSettings.aload())
    # The tab is only a view onto one long form: every tab's fields are always on the page and posted together.
    tab = settings_tab(request.POST.get("tab") or request.GET.get("tab"))
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        # Save only the fields on the page; the import writes its status columns itself.
        await form.instance.asave(update_fields=list(form.fields))
        messages.success(request, "Einstellungen gespeichert.")
        return redirect(f"{reverse('core:settings')}?tab={tab}")
    if form.errors and not form.non_field_errors():
        # Show the tab that holds the first mistake, whichever one was open.
        tab = next((t for name in form.errors if (t := SETTINGS_FIELD_TABS.get(name))), tab)
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
    copies = await sync_to_async(backup.listing)()
    backup_info = {
        "dir": settings.BACKUP_DIR,
        "count": len(copies),
        "newest": copies[0].created if copies else None,
        "last_run": current.backup_at,
        "status": current.backup_status,
        "failed": current.backup_failed,
    }
    context = {
        "form": form,
        "tab": tab,
        "tabs": SETTINGS_TABS,
        "sync_jobs": sync_jobs,
        "backup": backup_info,
        "lexware": await credentials.astatus(),
        "key_form": ApiKeyForm(),
        "mail": await MailSettings.aload(),
        "mail_failed": await OutgoingMail.objects.filter(
            status=OutgoingMail.Status.FAILED, created_at__gte=timezone.now() - timedelta(days=7)
        ).acount(),
    }
    return render(request, "core/settings.html", context)


async def _get_backup(name: str) -> Path:
    path = await sync_to_async(backup.get)(name)
    if path is None:
        raise Http404
    return path


@require_GET
async def backup_list(request: HttpRequest) -> HttpResponse:
    _require_admin(request)
    context = {"backups": await sync_to_async(backup.listing)(), "dir": settings.BACKUP_DIR}
    return render(request, "core/backups.html", context)


@require_POST
async def backup_create(request: HttpRequest) -> HttpResponse:
    _require_admin(request)
    try:
        path = await sync_to_async(backup.backup_and_record)()
    except Exception as exc:
        messages.error(request, f"Die Sicherung ist fehlgeschlagen: {exc}")
    else:
        messages.success(request, f"Sicherung {path.name} erstellt.")
    return redirect("core:backups")


@require_http_methods(["GET", "POST"])
async def backup_upload(request: HttpRequest) -> HttpResponse:
    """Store a backup file from elsewhere, e.g. another server, in the folder. Restoring it is a separate step.

    Oversized requests are refused before Django reads them, see core/upload_limit.py.
    """
    _require_admin(request)
    error = None
    if request.method == "POST":
        file = request.FILES.get("datei")
        if file is None:
            error = "Bitte wähle eine Datei aus."
        elif file.size > settings.BACKUP_UPLOAD_MAX_SIZE:
            error = f"Die Datei ist größer als {filesizeformat(settings.BACKUP_UPLOAD_MAX_SIZE)}."
        else:
            try:
                path = await sync_to_async(backup.save_upload)(file.chunks())
            except backup.InvalidBackup as exc:
                error = str(exc)
            else:
                messages.success(request, f"Sicherung hochgeladen und als {path.name} gespeichert.")
                return navigate("core:backups")
    context = {"error": error, "max_size": settings.BACKUP_UPLOAD_MAX_SIZE}
    return render(request, "core/backup_upload.html", context)


@require_GET
async def backup_download(request: HttpRequest, name: str) -> HttpResponse:
    _require_admin(request)
    path = await _get_backup(name)

    async def chunks():
        file = await asyncio.to_thread(path.open, "rb")
        try:
            while chunk := await asyncio.to_thread(file.read, 1024 * 1024):
                yield chunk
        finally:
            file.close()

    response = StreamingHttpResponse(chunks(), content_type="application/vnd.sqlite3")
    response["Content-Disposition"] = content_disposition_header(True, path.name)
    response["Content-Length"] = str(path.stat().st_size)
    return response


@require_POST
async def backup_delete(request: HttpRequest, name: str) -> HttpResponse:
    _require_admin(request)
    path = await _get_backup(name)
    await asyncio.to_thread(path.unlink)
    messages.success(request, f"Sicherung {name} gelöscht.")
    return redirect("core:backups")


@require_http_methods(["GET", "POST"])
async def backup_restore(request: HttpRequest, name: str) -> HttpResponse:
    _require_admin(request)
    path = await _get_backup(name)
    error = None
    if request.method == "POST":
        if request.POST.get("bestaetigt") != "1":
            error = "Bitte bestätige, dass der aktuelle Stand ersetzt wird."
        else:
            try:
                before = await sync_to_async(backup.restore)(path)
            except backup.InvalidBackup as exc:
                error = str(exc)
            else:
                # The restored sessions table may not have this session; a new key keeps you signed in,
                # as long as your account exists in the backup with the same password.
                await request.session.acycle_key()
                messages.success(
                    request,
                    f"Sicherung {name} wiederhergestellt. Der vorherige Stand liegt als {before.name} im Ordner.",
                )
                return navigate("core:backups")
    return render(request, "core/backup_restore.html", {"name": name, "error": error})


class FaviconView(RedirectView):
    """Redirect /favicon.ico to the static file.

    The URL is looked up per request: in production it carries a hash from the
    staticfiles manifest, which does not exist yet while the Docker image runs
    collectstatic.
    """

    permanent = True

    def get_redirect_url(self, *args, **kwargs) -> str:
        return static("img/favicon.ico")
