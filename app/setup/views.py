"""Setup of a fresh instance: the first administrator, the Lexware key, then on to the start page.

While no account exists, every page leads here (see core.middleware). The later steps need the new
administrator's login, so they can also be opened again afterwards.
"""

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.contrib.auth import alogin
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods

from accounts.models import User
from customers.sync import sync_and_record
from lexware import credentials
from lexware.client import LexwareError
from lexware.forms import ApiKeyForm
from lexware.views import check_and_store
from setup.forms import AdminAccountForm, AlreadySetUp

# (URL name, label). A step for backups goes between "lexware" and "done" once they are set in the app.
STEPS = [
    ("setup:account", "Admin-Konto"),
    ("setup:lexware", "Lexware Office"),
    ("setup:done", "Fertig"),
]


async def is_fresh() -> bool:
    """No account exists yet, so the app needs setting up."""
    return not await User.objects.aexists()


def _render(request: HttpRequest, template: str, step: str, context: dict) -> HttpResponse:
    current = [name for name, _ in STEPS].index(step)
    steps = [
        {"label": label, "number": i + 1, "done": i < current, "current": i == current}
        for i, (_, label) in enumerate(STEPS)
    ]
    # bare_layout: no sidebar, even though the new administrator is logged in.
    return render(request, template, {**context, "steps": steps, "bare_layout": True})


def _not_admin(request: HttpRequest) -> HttpResponse | None:
    """Where to send someone who may not open the later steps, or None for the administrator."""
    if not request.user.is_authenticated:
        # Only possible while no account exists, see core.middleware.
        return redirect("setup:account")
    if not request.user.is_admin:
        raise PermissionDenied
    return None


@sensitive_post_parameters("password1", "password2")
@require_http_methods(["GET", "POST"])
async def account(request: HttpRequest) -> HttpResponse:
    if not await is_fresh():
        return redirect("setup:lexware" if request.user.is_authenticated and request.user.is_admin else "/")
    form = AdminAccountForm(request.POST or None)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        try:
            user = await sync_to_async(form.save)()
        except AlreadySetUp:
            messages.error(request, "Die App wurde in der Zwischenzeit schon eingerichtet. Bitte melde dich an.")
            return redirect("accounts:login")
        await alogin(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("setup:lexware")
    return _render(request, "setup/account.html", "setup:account", {"form": form})


@sensitive_post_parameters("api_key")
@require_http_methods(["GET", "POST"])
async def lexware(request: HttpRequest) -> HttpResponse:
    if response := _not_admin(request):
        return response
    form = ApiKeyForm(request.POST or None)
    if request.method == "POST" and form.is_valid() and await check_and_store(form) is not None:
        return redirect("setup:done")
    context = {"form": form, "lexware": await credentials.astatus()}
    return _render(request, "setup/lexware.html", "setup:lexware", context)


@require_http_methods(["GET", "POST"])
async def done(request: HttpRequest) -> HttpResponse:
    if response := _not_admin(request):
        return response
    status = await credentials.astatus()
    if request.method == "POST":
        if status.configured and request.POST.get("import_customers"):
            try:
                result = await sync_and_record()
            except LexwareError as exc:
                messages.error(request, f"Der Kundenimport ist fehlgeschlagen: {exc}")
            else:
                messages.success(request, f"Kunden importiert: {result.summary}")
        messages.success(request, "Die Einrichtung ist abgeschlossen. Viel Spaß mit LexTracker!")
        return redirect("core:dashboard")
    return _render(request, "setup/done.html", "setup:done", {"lexware": status})
