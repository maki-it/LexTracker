from django.conf import settings
from django.contrib.auth import aauthenticate, alogin, alogout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from accounts.forms import LoginForm


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
        if user is not None:
            await alogin(request, user)
            return redirect(_safe_next(request))
        error = "Benutzername oder Passwort ist falsch."

    return render(request, "accounts/login.html", {"form": form, "error": error, "next": _safe_next(request)})


@require_POST
async def logout_view(request: HttpRequest) -> HttpResponse:
    await alogout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)
