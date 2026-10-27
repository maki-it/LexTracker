"""Push notifications: the script of the service worker, the key and the subscription of a device (answered as
JSON for ``static/js/app.js``), and the buttons for a device on the account page."""

import json
import logging
from functools import cache
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_GET, require_POST

from push import service, topics
from push.models import PushSubscription
from push.topics import Topic

logger = logging.getLogger(__name__)

SCRIPT = Path(__file__).with_name("sw.js")
# A browser sends nothing longer than this; the limits keep a made-up subscription from filling the table.
MAX_ENDPOINT = 2000


@cache
def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


@require_GET
async def service_worker(request: HttpRequest) -> HttpResponse:
    """The service worker. It lives below /push/, but may handle the whole app."""
    response = HttpResponse(_script(), content_type="text/javascript; charset=utf-8")
    response["Service-Worker-Allowed"] = "/"
    # The browser checks for a new version on its own, but never from its cache.
    response["Cache-Control"] = "no-cache"
    return response


def _error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": message}, status=status)


@require_GET
async def public_key(request: HttpRequest) -> HttpResponse:
    """The key a browser needs to subscribe (``applicationServerKey``)."""
    _private, public = await service.aload_keys()
    return JsonResponse({"key": public})


@require_POST
async def subscribe(request: HttpRequest) -> HttpResponse:
    """Remember the subscription a browser made, for the signed-in user."""
    try:
        body = json.loads(request.body)
        endpoint, keys = body["endpoint"], body["keys"]
        p256dh, auth = keys["p256dh"], keys["auth"]
        name = str(body.get("name") or "").strip()[:100]
    except ValueError, KeyError, TypeError:
        return _error(_("Das Gerät hat keine gültige Anmeldung geschickt."))
    if (
        not all(isinstance(v, str) and v for v in (endpoint, p256dh, auth))
        or len(endpoint) > MAX_ENDPOINT
        or urlsplit(endpoint).scheme != "https"
    ):
        return _error(_("Das Gerät hat keine gültige Anmeldung geschickt."))
    sub = await PushSubscription.objects.filter(endpoint=endpoint).afirst()
    if sub is None:
        await PushSubscription.objects.acreate(
            user=request.user, endpoint=endpoint, p256dh=p256dh, auth=auth, name=name or _("Unbenanntes Gerät")
        )
    else:
        # The same browser, signed in with another account: it belongs to that one now, with fresh settings.
        if sub.user_id != request.user.pk:
            sub.user, sub.topics, sub.timer_shown = request.user, topics.default_topics(), None
        sub.p256dh, sub.auth = p256dh, auth
        sub.name = name or sub.name
        await sub.asave()
    return JsonResponse({"ok": True})


async def _device(request: HttpRequest, pk: UUID) -> PushSubscription:
    try:
        return await request.user.push_subscriptions.aget(pk=pk)
    except PushSubscription.DoesNotExist:
        raise Http404 from None


def _back() -> HttpResponse:
    return redirect(f"{reverse('account:settings')}?tab=notifications")


@require_POST
async def device_topics(request: HttpRequest, pk: UUID) -> HttpResponse:
    sub = await _device(request, pk)
    allowed = {t.value for t in topics.available(request.user)}
    sub.topics = [t.value for t in Topic if t.value in allowed and t.value in request.POST.getlist("topics")]
    if name := request.POST.get("name", "").strip()[:100]:
        sub.name = name
    await sub.asave(update_fields=["topics", "name"])
    messages.success(request, _("Einstellungen gespeichert."))
    return _back()


@require_POST
async def device_test(request: HttpRequest, pk: UUID) -> HttpResponse:
    sub = await _device(request, pk)
    delivered = await service.apush(
        [sub],
        {
            "kind": "message",
            "title": _("Test"),
            "body": _("So sehen Benachrichtigungen auf diesem Gerät aus."),
            "url": reverse("account:settings") + "?tab=notifications",
            "tag": "test",
        },
        ttl=60,
    )
    if delivered:
        messages.success(request, _("Die Testnachricht ist unterwegs."))
    else:
        messages.error(
            request, _("Die Testnachricht konnte nicht zugestellt werden. Aktiviere Push auf dem Gerät neu.")
        )
    return _back()


@require_POST
async def device_remove(request: HttpRequest, pk: UUID) -> HttpResponse:
    sub = await _device(request, pk)
    await sub.adelete()
    messages.success(request, _("Das Gerät bekommt keine Push-Benachrichtigungen mehr."))
    return _back()
