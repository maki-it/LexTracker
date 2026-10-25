from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from lexware import credentials
from lexware.client import LexwareError
from lexware.forms import ApiKeyForm


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
    else:
        messages.error(request, form.errors["api_key"][0])
    return redirect(f"{reverse('core:settings')}?tab=lexware")


@require_POST
async def test_key(request: HttpRequest) -> HttpResponse:
    try:
        api_key = await credentials.aget_api_key()
        profile = await credentials.acheck(api_key)
    except LexwareError as exc:
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
    messages.success(request, _("API-Schlüssel entfernt."))
    return redirect(f"{reverse('core:settings')}?tab=lexware")
