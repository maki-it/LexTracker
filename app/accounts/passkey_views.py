"""The passkey ceremonies, answered as JSON for the script in ``static/js/app.js`` ("Passkeys").

On the login page (public): ``passkey_options`` starts a sign-in, ``passkey_login`` checks the browser's answer.
In the account settings: ``passkey_register_options`` and ``passkey_add`` add a passkey, ``passkey_remove`` removes one.
"""

import json
import logging
from uuid import UUID

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import alogin
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, resolve_url
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from accounts import passkeys, ratelimit
from accounts.views import account_url, locked_message

LOGIN_KEY = "passkey_login"
REGISTER_KEY = "passkey_register"
logger = logging.getLogger(__name__)


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


def _body(request: HttpRequest) -> dict:
    try:
        body = json.loads(request.body)
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _redirect_after_login(request: HttpRequest, next_url: object) -> str:
    allowed = isinstance(next_url, str) and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    )
    return next_url if allowed else resolve_url(settings.LOGIN_REDIRECT_URL)


@require_POST
async def passkey_options(request: HttpRequest) -> HttpResponse:
    """Start a sign-in: the challenge the browser has to have signed."""
    if not passkeys.enabled():
        raise Http404
    begun = passkeys.begin_authentication()
    await request.session.aset(LOGIN_KEY, begun.state)
    return JsonResponse(begun.options)


@require_POST
async def passkey_login(request: HttpRequest) -> HttpResponse:
    """Sign in with the signed challenge. Like SSO, it does not ask for the code of an authenticator app."""
    if not passkeys.enabled():
        raise Http404
    if (await request.auser()).is_authenticated:
        return JsonResponse({"redirect": resolve_url(settings.LOGIN_REDIRECT_URL)})
    if minutes := await ratelimit.locked_minutes(request):
        return _error(locked_message(minutes), 429)
    body = _body(request)
    state = await request.session.apop(LOGIN_KEY, None)
    try:
        user = await sync_to_async(passkeys.finish_authentication)(body.get("credential") or {}, state)
    except passkeys.PasskeyError as error:
        logger.warning("Passkey sign-in failed: %s", error)
        await ratelimit.record_failure(request)
        return _error(_("Die Anmeldung mit Passkey hat nicht geklappt."))
    await alogin(request, user, backend="django.contrib.auth.backends.ModelBackend")
    await ratelimit.clear_failures(request, user.get_username())
    return JsonResponse({"redirect": _redirect_after_login(request, body.get("next"))})


@require_POST
async def passkey_register_options(request: HttpRequest) -> HttpResponse:
    """Start adding a passkey to the signed-in account."""
    if not passkeys.enabled():
        raise Http404
    begun = await sync_to_async(passkeys.begin_registration)(request.user, request.brand.name)
    await request.session.aset(REGISTER_KEY, begun.state)
    return JsonResponse(begun.options)


@require_POST
async def passkey_add(request: HttpRequest) -> HttpResponse:
    """Save the passkey the browser has made."""
    if not passkeys.enabled():
        raise Http404
    body = _body(request)
    state = await request.session.apop(REGISTER_KEY, None)
    try:
        passkey = await sync_to_async(passkeys.finish_registration)(
            request.user, body.get("credential") or {}, state, str(body.get("name") or "")
        )
    except passkeys.PasskeyError as error:
        logger.warning("Passkey registration failed: %s", error)
        return _error(_("Der Passkey konnte nicht hinzugefügt werden."))
    messages.success(request, _("Passkey „%(name)s“ hinzugefügt.") % {"name": passkey.name})
    return JsonResponse({"redirect": account_url("security")})


@require_POST
async def passkey_remove(request: HttpRequest, pk: UUID) -> HttpResponse:
    passkey = await request.user.passkeys.filter(pk=pk).afirst()
    if passkey is None:
        raise Http404
    await passkey.adelete()
    messages.success(request, _("Passkey „%(name)s“ entfernt.") % {"name": passkey.name})
    return redirect(account_url("security"))
