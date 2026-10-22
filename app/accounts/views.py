import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import aauthenticate, alogin, alogout, aupdate_session_auth_hash
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from accounts import mfa
from accounts.forms import CodeForm, ConfirmPasswordForm, LoginForm, PreferencesForm, StyledPasswordChangeForm
from accounts.models import User

# Password checked, code from the authenticator app still missing.
MFA_PENDING_KEY = "mfa_pending"
MFA_PENDING_SECONDS = 300


def _safe_next(request: HttpRequest) -> str:
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return settings.LOGIN_REDIRECT_URL


@require_http_methods(["GET", "POST"])
async def login_view(request: HttpRequest) -> HttpResponse:
    if (await request.auser()).is_authenticated:
        return redirect(_safe_next(request))

    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        user = await aauthenticate(
            request, username=form.cleaned_data["username"], password=form.cleaned_data["password"]
        )
        if user is not None and await sync_to_async(mfa.has_mfa)(user):
            pending = {"user": user.pk, "backend": user.backend, "at": time.time()}
            await request.session.aset(MFA_PENDING_KEY, pending)
            return redirect(f"{reverse('accounts:login_code')}?next={_safe_next(request)}")
        if user is not None:
            await alogin(request, user)
            return redirect(_safe_next(request))
        error = "Benutzername oder Passwort ist falsch."

    return render(request, "accounts/login.html", {"form": form, "error": error, "next": _safe_next(request)})


@require_http_methods(["GET", "POST"])
async def login_code(request: HttpRequest) -> HttpResponse:
    """Second login step: the code from the authenticator app or a recovery code."""
    pending = await request.session.aget(MFA_PENDING_KEY)
    if not pending or time.time() - pending["at"] > MFA_PENDING_SECONDS:
        await request.session.apop(MFA_PENDING_KEY, None)
        return redirect(settings.LOGIN_URL)

    form = CodeForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        user = await User.objects.aget(pk=pending["user"])
        if await sync_to_async(mfa.verify)(user, form.cleaned_data["code"]):
            await request.session.apop(MFA_PENDING_KEY, None)
            await alogin(request, user, backend=pending["backend"])
            return redirect(_safe_next(request))
        error = "Der Code ist ungültig oder abgelaufen."
    return render(request, "accounts/login_code.html", {"form": form, "error": error, "next": _safe_next(request)})


@require_POST
async def logout_view(request: HttpRequest) -> HttpResponse:
    await alogout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)


# Account settings


@require_http_methods(["GET", "POST"])
async def account(request: HttpRequest) -> HttpResponse:
    form = PreferencesForm(request.POST or None, instance=request.user)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await sync_to_async(form.save)()
        messages.success(request, "Einstellungen gespeichert.")
        return redirect("account:settings")
    return render(
        request,
        "accounts/account.html",
        {"form": form, "has_mfa": await sync_to_async(mfa.has_mfa)(request.user)},
    )


@require_http_methods(["GET", "POST"])
async def password_change(request: HttpRequest) -> HttpResponse:
    form = StyledPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await sync_to_async(form.save)()
        # Keep this session signed in; other sessions are signed out by the new password.
        await aupdate_session_auth_hash(request, form.user)
        messages.success(request, "Passwort geändert.")
        return redirect("account:settings")
    return render(request, "accounts/password.html", {"form": form})


@require_http_methods(["GET", "POST"])
async def mfa_setup(request: HttpRequest) -> HttpResponse:
    if await sync_to_async(mfa.has_mfa)(request.user):
        return redirect("account:mfa_manage")
    device = await sync_to_async(mfa.pending_device)(request.user)
    form = CodeForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        codes = await sync_to_async(mfa.confirm)(device, form.cleaned_data["code"])
        if codes is not None:
            messages.success(request, "Zwei-Faktor-Anmeldung ist eingeschaltet.")
            return render(request, "accounts/recovery_codes.html", {"codes": codes})
        form.add_error("code", "Der Code stimmt nicht. Prüfe die Uhrzeit auf dem Handy und versuche es erneut.")
    context = {
        "form": form,
        "qr_code": await sync_to_async(mfa.qr_code_svg)(device),
        "secret": mfa.secret_for_manual_entry(device),
    }
    return render(request, "accounts/mfa_setup.html", context)


@require_http_methods(["GET", "POST"])
async def mfa_manage(request: HttpRequest) -> HttpResponse:
    """Turn two-factor login off or create new recovery codes. Both need the password."""
    form = ConfirmPasswordForm(request.user, request.POST or None)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        if request.POST.get("action") == "codes":
            codes = await sync_to_async(mfa.new_recovery_codes)(request.user)
            return render(request, "accounts/recovery_codes.html", {"codes": codes})
        await sync_to_async(mfa.disable)(request.user)
        messages.success(request, "Zwei-Faktor-Anmeldung ist ausgeschaltet.")
        return redirect("account:settings")
    return render(request, "accounts/mfa_manage.html", {"form": form})
