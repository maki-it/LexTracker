from collections.abc import Awaitable, Callable

from django.conf import settings
from django.contrib.auth.views import redirect_to_login
from django.http import HttpRequest, HttpResponse
from django.utils.decorators import async_only_middleware

# /mcp/ checks its own API token.
PUBLIC_PREFIXES = ("/accounts/login/", "/health/", "/admin/", "/static/", "/mcp/", "/favicon.ico")


@async_only_middleware
def LoginRequiredMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Load the user asynchronously and require a login for every non-public page.

    Django's lazy ``request.user`` would query the database synchronously the first
    time a template touches it, which is not allowed inside async views. Loading it
    once here with ``auser()`` avoids that.
    """

    async def middleware(request: HttpRequest) -> HttpResponse:
        if request.path.startswith("/static/"):
            return await get_response(request)
        request.user = await request.auser()
        if not request.user.is_authenticated and not request.path.startswith(PUBLIC_PREFIXES):
            return redirect_to_login(request.get_full_path(), settings.LOGIN_URL)
        return await get_response(request)

    return middleware
