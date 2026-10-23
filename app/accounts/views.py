import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import aauthenticate, alogin, alogout, aupdate_session_auth_hash
from django.contrib.auth.tokens import default_token_generator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme, urlencode, urlsafe_base64_decode
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from accounts import links, mfa, ratelimit
from accounts.forms import (
    ApiTokenForm,
    CodeForm,
    ConfirmPasswordForm,
    InviteForm,
    LinkRequestForm,
    LoginForm,
    PreferencesForm,
    StyledPasswordChangeForm,
)
from accounts.models import ApiToken, User

# Password checked, code from the authenticator app still missing.
MFA_PENDING_KEY = "mfa_pending"
MFA_PENDING_SECONDS = 300


def _safe_next(request: HttpRequest) -> str:
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return next_url
    return settings.LOGIN_REDIRECT_URL


def _locked(request: HttpRequest, template: str, form, minutes: int) -> HttpResponse:
    error = f"Zu viele Fehlversuche. Versuche es in {minutes} Minute{'n' if minutes > 1 else ''} wieder."
    context = {"form": form, "error": error, "next": _safe_next(request)}
    return render(request, template, context, status=429)


@require_http_methods(["GET", "POST"])
async def login_view(request: HttpRequest) -> HttpResponse:
    if (await request.auser()).is_authenticated:
        return redirect(_safe_next(request))

    form = LoginForm(request.POST or None, initial={"username": request.GET.get("username", "")})
    error = None
    if request.method == "POST" and (minutes := await ratelimit.locked_minutes(request)):
        return _locked(request, "accounts/login.html", form, minutes)
    if request.method == "POST" and form.is_valid():
        user = await aauthenticate(
            request, username=form.cleaned_data["username"], password=form.cleaned_data["password"]
        )
        if user is not None:
            return await _sign_in(request, user, user.backend)
        await ratelimit.record_failure(request, form.cleaned_data["username"])
        error = "Benutzername oder Passwort ist falsch."

    context = {"form": form, "error": error, "next": _safe_next(request), "links": await links.available()}
    return render(request, "accounts/login.html", context)


async def _sign_in(request: HttpRequest, user: User, backend: str) -> HttpResponse:
    """Sign in a user who proved who they are, after the code from the authenticator app if they use one."""
    if await sync_to_async(mfa.has_mfa)(user):
        pending = {"user": user.pk, "backend": backend, "at": time.time()}
        await request.session.aset(MFA_PENDING_KEY, pending)
        return redirect(f"{reverse('accounts:login_code')}?next={_safe_next(request)}")
    await alogin(request, user, backend=backend)
    await ratelimit.clear_failures(request)
    return redirect(_safe_next(request))


@require_http_methods(["GET", "POST"])
async def login_code(request: HttpRequest) -> HttpResponse:
    """Second login step: the code from the authenticator app or a recovery code."""
    pending = await request.session.aget(MFA_PENDING_KEY)
    if not pending or time.time() - pending["at"] > MFA_PENDING_SECONDS:
        await request.session.apop(MFA_PENDING_KEY, None)
        return redirect(settings.LOGIN_URL)

    form = CodeForm(request.POST or None)
    error = None
    if request.method == "POST" and (minutes := await ratelimit.locked_minutes(request)):
        return _locked(request, "accounts/login_code.html", form, minutes)
    if request.method == "POST" and form.is_valid():
        user = await User.objects.aget(pk=pending["user"])
        if await sync_to_async(mfa.verify)(user, form.cleaned_data["code"]):
            await request.session.apop(MFA_PENDING_KEY, None)
            await alogin(request, user, backend=pending["backend"])
            await ratelimit.clear_failures(request)
            return redirect(_safe_next(request))
        await ratelimit.record_failure(request, user.get_username())
        error = "Der Code ist ungültig oder abgelaufen."
    return render(request, "accounts/login_code.html", {"form": form, "error": error, "next": _safe_next(request)})


async def _request_link(request: HttpRequest, template: str, send) -> HttpResponse:
    """Ask for a username or e-mail address and send a link there, if such an account exists."""
    form = LinkRequestForm(request.POST or None)
    if request.method == "POST" and (minutes := await ratelimit.locked_minutes(request)):
        return _locked(request, template, form, minutes)
    if request.method == "POST" and form.is_valid():
        identifier = form.cleaned_data["identifier"]
        # Every request counts towards the rate limit, so nobody can flood an inbox or probe for accounts.
        await ratelimit.record_failure(request, identifier)
        await send(request, identifier)
        return render(request, template, {"sent": True, "identifier": identifier})
    return render(request, template, {"form": form})


@require_http_methods(["GET", "POST"])
async def password_forgot(request: HttpRequest) -> HttpResponse:
    if not (await links.available())["password_reset"]:
        return render(request, "accounts/password_forgot.html", {"unavailable": True})
    return await _request_link(request, "accounts/password_forgot.html", links.send_password_reset)


@sensitive_post_parameters()
@require_http_methods(["GET", "POST"])
async def password_reset(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    """Set a new password from the link in the e-mail."""
    if request.method == "POST" and (minutes := await ratelimit.locked_minutes(request)):
        return _locked(request, "accounts/password_reset.html", None, minutes)
    user = await links.reset_user(uidb64, token)
    if user is None:
        if request.method == "POST":
            await ratelimit.record_failure(request)
        return render(request, "accounts/password_reset.html", {"invalid": True}, status=400)
    form = InviteForm(user, request.POST or None)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        await sync_to_async(form.save)()
        messages.success(request, "Neues Passwort gesetzt. Melde dich jetzt damit an.")
        return redirect(f"{reverse('accounts:login')}?{urlencode({'username': user.get_username()})}")
    return render(request, "accounts/password_reset.html", {"form": form, "reset_user": user})


@require_http_methods(["GET", "POST"])
async def login_link_request(request: HttpRequest) -> HttpResponse:
    if not (await links.available())["login_link"]:
        return redirect(settings.LOGIN_URL)
    return await _request_link(request, "accounts/login_link_request.html", links.send_login_link)


@require_http_methods(["GET", "POST"])
async def login_link(request: HttpRequest, key: str) -> HttpResponse:
    """Sign in with the link from the e-mail.

    Opening the link only shows a button; the button signs in. Mail programs that open links to check
    them would otherwise use up the link before the user clicks it.
    """
    if request.method == "GET":
        if not await links.login_link_valid(key):
            return render(request, "accounts/login_link.html", {"invalid": True}, status=400)
        return render(request, "accounts/login_link.html", {})
    if minutes := await ratelimit.locked_minutes(request):
        return _locked(request, "accounts/login_link.html", None, minutes)
    user = await links.redeem_login_link(key)
    if user is None:
        await ratelimit.record_failure(request)
        return render(request, "accounts/login_link.html", {"invalid": True}, status=400)
    return await _sign_in(request, user, "django.contrib.auth.backends.ModelBackend")


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
    return await _account_page(request, form)


async def _account_page(request: HttpRequest, form, token_form=None, new_key: str = "") -> HttpResponse:
    return render(
        request,
        "accounts/account.html",
        {
            "form": form,
            "has_mfa": await sync_to_async(mfa.has_mfa)(request.user),
            "tokens": [t async for t in request.user.api_tokens.all()],
            "token_form": token_form or ApiTokenForm(),
            "new_key": new_key,
            "mcp_url": request.build_absolute_uri(reverse("mcp:endpoint")),
        },
    )


@require_POST
async def token_create(request: HttpRequest) -> HttpResponse:
    token_form = ApiTokenForm(request.POST)
    new_key = ""
    if await sync_to_async(token_form.is_valid)():
        _, new_key = await sync_to_async(ApiToken.issue)(request.user, token_form.cleaned_data["name"])
        token_form = None
    # Rendered, not redirected: the key is shown only on this response.
    return await _account_page(request, PreferencesForm(instance=request.user), token_form, new_key)


@require_POST
async def token_revoke(request: HttpRequest, pk: int) -> HttpResponse:
    deleted, _ = await request.user.api_tokens.filter(pk=pk).adelete()
    if deleted:
        messages.success(request, "Token widerrufen. Programme, die ihn nutzen, haben keinen Zugriff mehr.")
    return redirect("account:settings")


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


@require_http_methods(["GET", "POST"])
async def invite(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    """Set the first password from an invitation link (also works to reset a forgotten one)."""
    try:
        user = await User.objects.aget(pk=urlsafe_base64_decode(uidb64).decode(), is_active=True)
    except User.DoesNotExist, ValueError, UnicodeDecodeError:
        user = None
    if user is None or not default_token_generator.check_token(user, token):
        return render(request, "accounts/invite.html", {"invalid": True}, status=400)
    form = InviteForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        await sync_to_async(form.save)()
        messages.success(request, "Passwort gesetzt. Melde dich jetzt an.")
        return redirect(f"{reverse('accounts:login')}?{urlencode({'username': user.get_username()})}")
    return render(request, "accounts/invite.html", {"form": form, "invited": user})
