"""Setup of a fresh instance: the first administrator with two-factor login, the Lexware key, e-mail, backups,
then on to the start page.

While no account exists, every page leads here (see core.middleware). The later steps need the new
administrator's login, so they can also be opened again afterwards.
"""

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import alogin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from accounts import mfa
from accounts.forms import CodeForm
from accounts.models import User
from core import branding
from core.models import AppSettings
from customers.sync import sync_and_record
from lexware import credentials
from lexware.client import LexwareError
from lexware.forms import ApiKeyForm
from lexware.views import check_and_store
from mailer import outbox
from mailer.forms import MailSettingsForm
from mailer.models import MailSettings
from setup import code as setup_code
from setup.forms import AdminAccountForm, AlreadySetUp, BackupForm

# (URL name, label)
STEPS = [
    ("setup:account", gettext_lazy("Admin-Konto")),
    ("setup:mfa", gettext_lazy("Zwei-Faktor")),
    ("setup:lexware", "Lexware Office"),
    ("setup:mail", gettext_lazy("E-Mail")),
    ("setup:backup", gettext_lazy("Datensicherung")),
    ("setup:done", gettext_lazy("Fertig")),
]


async def is_fresh() -> bool:
    """No account exists yet, so the app needs setting up."""
    return not await User.objects.aexists()


def _render(request: HttpRequest, template: str, step: str, context: dict) -> HttpResponse:
    current = [name for name, _label in STEPS].index(step)
    steps = [
        {"label": label, "number": i + 1, "done": i < current, "current": i == current}
        for i, (_name, label) in enumerate(STEPS)
    ]
    # bare_layout: no sidebar, even though the new administrator is logged in.
    return render(request, template, {**context, "steps": steps, "bare_layout": True})


async def _not_admin(request: HttpRequest) -> HttpResponse | None:
    """Where to send someone who may not open the later steps, or None for the administrator.

    The administrator has to set up two-factor login before anything else.
    """
    if not request.user.is_authenticated:
        # Only possible while no account exists, see core.middleware.
        return redirect("setup:account")
    if not request.user.is_admin:
        raise PermissionDenied
    if not await sync_to_async(mfa.has_mfa)(request.user):
        return redirect("setup:mfa")
    return None


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
async def account(request: HttpRequest) -> HttpResponse:
    if not await is_fresh():
        return redirect("setup:mfa" if request.user.is_authenticated and request.user.is_admin else "/")
    if not await request.session.aget(setup_code.SESSION_KEY):
        return await _unlock(request)
    form = AdminAccountForm(request.POST or None)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        try:
            user = await sync_to_async(form.save)()
        except AlreadySetUp:
            messages.error(request, _("Die App wurde in der Zwischenzeit schon eingerichtet. Bitte melde dich an."))
            return redirect("accounts:login")
        await alogin(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("setup:mfa")
    return _render(request, "setup/account.html", "setup:account", {"form": form})


@require_http_methods(["GET", "POST"])
async def two_factor(request: HttpRequest) -> HttpResponse:
    """Two-factor login with an authenticator app, required for the administrator before the setup goes on."""
    if not request.user.is_authenticated:
        return redirect("setup:account")
    if not request.user.is_admin:
        raise PermissionDenied
    if await sync_to_async(mfa.has_mfa)(request.user):
        return redirect("setup:lexware")
    device = await sync_to_async(mfa.pending_device)(request.user)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        codes = await sync_to_async(mfa.confirm)(device, form.cleaned_data["code"])
        if codes is not None:
            return _render(request, "setup/recovery_codes.html", "setup:mfa", {"codes": codes})
        form.add_error("code", _("Der Code stimmt nicht. Prüfe die Uhrzeit auf dem Handy und versuche es erneut."))
    context = {
        "form": form,
        "qr_code": await sync_to_async(mfa.qr_code_svg)(device),
        "secret": mfa.secret_for_manual_entry(device),
    }
    return _render(request, "setup/mfa.html", "setup:mfa", context)


async def _unlock(request: HttpRequest) -> HttpResponse:
    """Ask for the setup code from the log; a link from the log carries it already."""
    code = request.POST.get("code") or request.GET.get("code") or ""
    if code and setup_code.matches(code):
        await request.session.aset(setup_code.SESSION_KEY, True)
        return redirect("setup:account")
    if not code:
        setup_code.log_setup_link(request)
    error = _("Der Code stimmt nicht.") if code else None
    return _render(request, "setup/unlock.html", "setup:account", {"error": error})


@sensitive_post_parameters("api_key")
@require_http_methods(["GET", "POST"])
async def lexware(request: HttpRequest) -> HttpResponse:
    if response := await _not_admin(request):
        return response
    form = ApiKeyForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and await check_and_store(form) is not None:
        return redirect("setup:mail")
    context = {"form": form, "lexware": await credentials.astatus()}
    return _render(request, "setup/lexware.html", "setup:lexware", context)


@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
async def mail(request: HttpRequest) -> HttpResponse:
    """The SMTP server, optional. A test mail goes to the administrator's address before moving on."""
    if response := await _not_admin(request):
        return response
    config = await MailSettings.aload()
    initial = {} if config.base_url else {"base_url": request.build_absolute_uri("/").rstrip("/")}
    form = MailSettingsForm(request.POST or None, instance=config, initial=initial)
    test_result = None
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        form.instance.updated_at = timezone.now()
        await sync_to_async(form.save)()
        if request.POST.get("test") and config.is_configured:
            to = request.user.email
            if not to:
                test_result = {"error": _("Dein Konto hat keine E-Mail-Adresse. Trag unter Konto eine ein.")}
            else:
                brand = await branding.aload()
                subject = _("Testmail von %(app)s") % {"app": brand.name}
                text, html = outbox.render("test", {"subject": subject, "config": config, "brand": brand})
                error = await outbox.asend_now(config, outbox.Message(to, subject, text, html))
                test_result = {"error": error} if error else {"ok": to}
        else:
            return redirect("setup:backup")
    context = {"form": form, "config": form.instance, "test_result": test_result}
    return _render(request, "setup/mail.html", "setup:mail", context)


@require_http_methods(["GET", "POST"])
async def backup(request: HttpRequest) -> HttpResponse:
    if response := await _not_admin(request):
        return response
    form = BackupForm(request.POST or None, instance=await AppSettings.aload())
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await form.instance.asave(update_fields=list(form.fields))
        return redirect("setup:done")
    return _render(request, "setup/backup.html", "setup:backup", {"form": form, "backup_dir": settings.BACKUP_DIR})


@require_http_methods(["GET", "POST"])
async def done(request: HttpRequest) -> HttpResponse:
    if response := await _not_admin(request):
        return response
    status = await credentials.astatus()
    if request.method == "POST":
        if status.configured and request.POST.get("import_customers"):
            try:
                result = await sync_and_record()
            except LexwareError as exc:
                messages.error(request, _("Der Kundenimport ist fehlgeschlagen: %(error)s") % {"error": exc})
            else:
                messages.success(request, _("Kunden importiert: %(summary)s") % {"summary": result.summary})
        messages.success(
            request, _("Die Einrichtung ist abgeschlossen. Viel Spaß mit %(app)s!") % {"app": request.brand.name}
        )
        return redirect("core:dashboard")
    context = {
        "lexware": status,
        "app_settings": await AppSettings.aload(),
        "mail": await MailSettings.aload(),
    }
    return _render(request, "setup/done.html", "setup:done", context)
