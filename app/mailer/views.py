from uuid import UUID

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from core import branding
from mailer import outbox
from mailer.forms import MailSettingsForm, TestMailForm
from mailer.models import MailSettings, OutgoingMail

# How many e-mails the outbox on the page lists.
OUTBOX_SIZE = 30


async def _page(request: HttpRequest, form: MailSettingsForm, test_form: TestMailForm | None = None) -> HttpResponse:
    mails = [m async for m in OutgoingMail.objects.order_by("-created_at")[:OUTBOX_SIZE]]
    context = {
        "form": form,
        "config": form.instance,
        "test_form": test_form or TestMailForm(initial={"to": request.user.email}),
        "mails": mails,
        "pending": await OutgoingMail.objects.filter(status=OutgoingMail.Status.PENDING).acount(),
    }
    return render(request, "mailer/settings.html", context)


@sensitive_post_parameters("password")
@require_http_methods(["GET", "POST"])
async def mail_settings(request: HttpRequest) -> HttpResponse:
    config = await MailSettings.aload()
    initial = {} if config.base_url else {"base_url": request.build_absolute_uri("/").rstrip("/")}
    form = MailSettingsForm(request.POST or None, instance=config, initial=initial)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        form.instance.updated_at = timezone.now()
        await sync_to_async(form.save)()
        messages.success(request, _("E-Mail-Einstellungen gespeichert. Schick eine Testmail, um sie zu prüfen."))
        return redirect("mailer:settings")
    return await _page(request, form)


@require_POST
async def test_mail(request: HttpRequest) -> HttpResponse:
    """Send straight away instead of through the queue, so the page can show what the server says."""
    config = await MailSettings.aload()
    test_form = TestMailForm(request.POST)
    if not test_form.is_valid():
        return await _page(request, MailSettingsForm(instance=config), test_form)
    if not config.is_configured:
        messages.error(request, _("Trag zuerst SMTP-Server und Absenderadresse ein."))
        return redirect("mailer:settings")
    to = test_form.cleaned_data["to"]
    brand = await branding.aload()
    subject = _("Testmail von %(app)s") % {"app": brand.name}
    text, html = outbox.render("test", {"subject": subject, "config": config, "brand": brand})
    error = await outbox.asend_now(config, outbox.Message(to, subject, text, html))
    if error:
        messages.error(request, _("Die Testmail wurde nicht verschickt: %(error)s") % {"error": error})
    else:
        messages.success(request, _("Testmail an %(to)s verschickt. Schau in dein Postfach.") % {"to": to})
    return redirect("mailer:settings")


@require_POST
async def retry(request: HttpRequest, pk: UUID) -> HttpResponse:
    if await outbox.aretry(pk):
        messages.success(request, _("Die E-Mail wird gleich noch einmal verschickt."))
    return redirect("mailer:settings")
