import json

from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from core.ids import parse_uuid
from lexware import credentials, webhooks
from lexware.client import LexwareError, LexwareUnauthorized, client_from_settings
from lexware.forms import ApiKeyForm
from lexware.models import WebhookSubscription

# Lexware's calls are a few hundred bytes. Anything bigger is not from Lexware.
WEBHOOK_MAX_BYTES = 16_384


async def check_and_store(form: ApiKeyForm) -> str | None:
    """Check the key in a valid form against Lexware and store it. Returns the Lexware account's name.

    On failure the form gets the error and nothing is stored.
    """
    api_key = form.cleaned_data["api_key"]
    try:
        profile = await credentials.acheck(api_key)
    except LexwareError as exc:
        form.add_error("api_key", _("Der Schlüssel wurde nicht gespeichert: %(error)s") % {"error": exc})
        return None
    await credentials.astore(api_key, company_name=profile.company_name)
    return profile.company_name


@sensitive_post_parameters("api_key")
@require_POST
async def save_key(request: HttpRequest) -> HttpResponse:
    form = ApiKeyForm(request.POST)
    if not form.is_valid():
        messages.error(request, _("Bitte gib einen API-Schlüssel ein."))
    elif (company_name := await check_and_store(form)) is not None:
        messages.success(
            request,
            _("API-Schlüssel geprüft und gespeichert (%(company)s).") % {"company": company_name or "Lexware Office"},
        )
        if await WebhookSubscription.objects.aexists():
            # Lexware removes the subscriptions together with the key they were created with.
            await _subscribe(request)
    else:
        messages.error(request, form.errors["api_key"][0])
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def test_key(request: HttpRequest) -> HttpResponse:
    try:
        api_key = await credentials.aget_api_key()
        profile = await credentials.acheck(api_key)
    except LexwareError as exc:
        # Only a rejected key says something about the key. A network error or a rate limit does not.
        if isinstance(exc, LexwareUnauthorized) and (await credentials.astatus()).source == "app":
            await credentials.amark_rejected()
        messages.error(request, _("Verbindung fehlgeschlagen: %(error)s") % {"error": exc})
    else:
        if (await credentials.astatus()).source == "app":
            await credentials.amark_verified(profile.company_name)
        messages.success(
            request,
            _("Verbindung zu Lexware Office klappt (%(company)s).")
            % {"company": profile.company_name or _("ohne Firmennamen")},
        )
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def remove_key(request: HttpRequest) -> HttpResponse:
    await credentials.aremove()
    await webhooks.aforget()
    messages.success(request, _("API-Schlüssel entfernt."))
    return redirect(f"{reverse('core:settings')}?tab=lexware")


async def _subscribe(request: HttpRequest) -> None:
    """Subscribe to Lexware's events and tell the user how it went."""
    base_url = await webhooks.abase_url(request.build_absolute_uri("/"))
    if not base_url.startswith("https://"):
        messages.error(request, (await webhooks.astatus(base_url)).problem)
        return
    try:
        async with client_from_settings() as client:
            result = await webhooks.aenable(client, base_url)
    except LexwareError as exc:
        messages.error(request, _("Webhooks konnten nicht eingerichtet werden: %(error)s") % {"error": exc})
        return
    if result.subscribed:
        messages.success(
            request,
            _("Lexware meldet Änderungen jetzt direkt (%(count)d Ereignisse abonniert).")
            % {"count": len(result.subscribed)},
        )
    for event_type, error in result.failed.items():
        messages.warning(request, f"{event_type}: {error}")
    if not result.subscribed:
        messages.error(request, _("Lexware hat kein Ereignis angenommen. Ist die Adresse von außen erreichbar?"))


@require_POST
async def enable_webhooks(request: HttpRequest) -> HttpResponse:
    await _subscribe(request)
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def disable_webhooks(request: HttpRequest) -> HttpResponse:
    try:
        async with client_from_settings() as client:
            await webhooks.adisable(client)
    except LexwareError as exc:
        messages.error(request, _("Webhooks konnten nicht entfernt werden: %(error)s") % {"error": exc})
    else:
        messages.success(request, _("Webhooks entfernt. Lexware ruft die App nicht mehr auf."))
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def save_webhook_key(request: HttpRequest) -> HttpResponse:
    try:
        await webhooks.astore_public_key(request.POST.get("public_key", ""))
    except ValueError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, _("Schlüssel gespeichert. Die App nimmt nur noch von Lexware signierte Aufrufe an."))
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def remove_webhook_key(request: HttpRequest) -> HttpResponse:
    await webhooks.aremove_public_key()
    messages.success(request, _("Schlüssel entfernt. Aufrufe werden nicht mehr auf eine Signatur geprüft."))
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@csrf_exempt
@require_http_methods(["GET", "HEAD", "POST"])
async def webhook(request: HttpRequest, token: str) -> HttpResponse:
    """Where Lexware reports changes. Public; the secret in the address stands in for a login.

    Lexware checks a new address with a HEAD request before it accepts the subscription.
    """
    if not await webhooks.avalid_token(token):
        return HttpResponse(status=404)
    if request.method != "POST":
        return HttpResponse(status=200)
    try:
        if int(request.headers.get("Content-Length") or 0) > WEBHOOK_MAX_BYTES:
            return HttpResponse(status=413)
        payload = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    if not isinstance(payload, dict):
        return HttpResponse(status=400)
    if not await webhooks.asignature_ok(request.body, request.headers.get("X-Lxo-Signature", "")):
        return HttpResponse(status=401)
    await webhooks.arecord(str(payload.get("eventType", "")), parse_uuid(payload.get("resourceId")))
    return HttpResponse(status=200)
