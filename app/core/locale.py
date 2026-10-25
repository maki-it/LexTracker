"""The language of each request.

Signed-in users get the language from their account (``User.language``). Everyone else (the login page,
the setup) gets the one in the language cookie, then the one the browser asks for, then German.
The cookie is set from the account so that the login page keeps the language after signing out.
"""

from collections.abc import Awaitable, Callable

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils import translation
from django.utils.cache import patch_vary_headers
from django.utils.decorators import async_only_middleware

COOKIE_MAX_AGE = 365 * 24 * 60 * 60
SKIPPED = ("/static/", "/health/")


def language_for(request: HttpRequest) -> str:
    """The language code for the request, always one of ``settings.LANGUAGES``."""
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and translation.check_for_language(user.language):
        return user.language
    return translation.get_language_from_request(request, check_path=False)


@async_only_middleware
def LocaleMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """Activate the language for the rest of the request.

    Django's own ``LocaleMiddleware`` is not used because it cannot know the user's setting and would run
    in a thread. This one needs ``request.user``, so it comes after ``LoginRequiredMiddleware``.
    """

    async def middleware(request: HttpRequest) -> HttpResponse:
        if request.path.startswith(SKIPPED):
            return await get_response(request)
        language = language_for(request)
        with translation.override(language):
            request.LANGUAGE_CODE = language
            response = await get_response(request)
        response.headers.setdefault("Content-Language", language)
        if request.user.is_authenticated:
            # The account page may have changed it during the request.
            language = request.user.language
            if request.COOKIES.get(settings.LANGUAGE_COOKIE_NAME) != language:
                response.set_cookie(settings.LANGUAGE_COOKIE_NAME, language, max_age=COOKIE_MAX_AGE, samesite="Lax")
        else:
            patch_vary_headers(response, ("Accept-Language", "Cookie"))
        return response

    return middleware
