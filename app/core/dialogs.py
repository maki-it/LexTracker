"""Pages shown in the dialog of base.html.

A page opened with ``{% dialog_link %}`` is requested by htmx with the header
``HX-Target: dialog-body``. Such pages render with the ``dialog.html`` layout (only
their content, no sidebar). A redirect after a successful save reloads the page
behind the dialog instead of landing inside it, unless the view uses ``navigate()``.
"""

from collections.abc import Awaitable, Callable

from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import redirect
from django.utils.decorators import async_only_middleware

DIALOG_TARGET = "dialog-body"


def in_dialog(request: HttpRequest) -> bool:
    return request.headers.get("HX-Request") == "true" and request.headers.get("HX-Target") == DIALOG_TARGET


def layout(request: HttpRequest) -> dict:
    """Context processor: pages extend ``{{ layout }}`` instead of "base.html"."""
    dialog = in_dialog(request)
    return {"layout": "dialog.html" if dialog else "base.html", "in_dialog": dialog}


def navigate(*args, **kwargs) -> HttpResponseRedirect:
    """Like ``redirect()``, but from a dialog it goes to that page instead of reloading the one behind it.

    Use it when the page behind the dialog is no longer the right one, e.g. after deleting
    what it shows or creating something that has its own page.
    """
    response = redirect(*args, **kwargs)
    response.dialog_navigate = True
    return response


@async_only_middleware
def DialogMiddleware(get_response: Callable[[HttpRequest], Awaitable[HttpResponse]]):
    """After a save in the dialog, reload the page behind it (shows the change and the message)."""

    async def middleware(request: HttpRequest) -> HttpResponse:
        response = await get_response(request)
        if not in_dialog(request) or not 300 <= response.status_code < 400 or "Location" not in response:
            return response
        reload = HttpResponse()
        if getattr(response, "dialog_navigate", False):
            reload["HX-Redirect"] = response["Location"]
        else:
            reload["HX-Refresh"] = "true"
        return reload

    return middleware
