from collections.abc import Awaitable, Callable

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.utils.decorators import async_only_middleware

from accounts.models import User

# Never redirected, not even to the setup. /mcp/ checks its own API token, /webhooks/ the secret in its address.
ALWAYS_PUBLIC_PREFIXES = ("/health/", "/static/", "/mcp/", "/webhooks/", "/favicon.ico", "/branding/")
PUBLIC_PREFIXES = (
    *ALWAYS_PUBLIC_PREFIXES,
    "/accounts/login/",
    "/accounts/language/",
    "/accounts/invite/",
    "/accounts/password/",
    "/admin/",
)
# Open without a login only while no account exists.
SETUP_PREFIX = "/setup/"


@async_only_middleware
def LoginRequiredMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Load the user asynchronously and require a login for every non-public page.

    On a fresh instance without any account, every page leads to the setup instead.

    Django's lazy ``request.user`` would query the database synchronously the first
    time a template touches it, which is not allowed inside async views. Loading it
    once here with ``auser()`` avoids that.
    """

    async def middleware(request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/static/"):
            return await get_response(request)
        request.user = await request.auser()
        if request.user.is_authenticated or request.path.startswith(ALWAYS_PUBLIC_PREFIXES):
            return await get_response(request)
        # Only anonymous visitors get here, and once an account exists that is one cheap query.
        if not await User.objects.aexists():
            if request.path.startswith(SETUP_PREFIX):
                return await get_response(request)
            return redirect("setup:account")
        if not request.path.startswith(PUBLIC_PREFIXES):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return await get_response(request)

    return middleware
