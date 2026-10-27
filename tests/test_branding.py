import json
from pathlib import Path

import pytest
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import mfa
from accounts.models import ApiToken, User
from core import access, branding
from core.models import AppSettings
from mailer.models import MailSettings, OutgoingMail

pytestmark = pytest.mark.django_db

TEMPLATES = Path(__file__).parent.parent / "app" / "templates"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="4"/></svg>'

SETTINGS = {
    "time_rounding": 0,
    "invoice_detail": "summary",
    "login_max_attempts": 5,
    "login_lockout_minutes": 15,
    "lexware_sync_interval": 60,
    "invoice_sync_interval": 60,
    "backup_time": "03:00",
    "backup_keep": 14,
    "weekly_report_weekday": 0,
    "weekly_report_time": "07:00",
    "timer_reminder_hours": 10,
    "overdue_notice": "admins",
    "overdue_notice_days": 3,
}


@pytest.fixture
def admin(client, user):
    user.email = "kim@example.de"
    user.save()
    client.force_login(user)
    return client


def save(client, **data):
    return client.post(reverse("core:settings"), SETTINGS | data)


def upload(client, content: bytes, name: str = "logo.png", **data):
    return save(client, logo=SimpleUploadedFile(name, content), **data)


def test_without_settings_the_app_is_called_lextracker(admin):
    page = admin.get(reverse("core:dashboard")).text
    assert "<title>Übersicht · LexTracker</title>" in page
    assert "<svg" in page
    assert reverse("core:logo") not in page
    assert admin.get(reverse("core:logo")).status_code == 404


def test_the_name_replaces_lextracker_in_pages(admin, client):
    assert save(admin, app_name="Acme Zeit").status_code == 302

    page = admin.get(reverse("core:dashboard")).text
    assert "<title>Übersicht · Acme Zeit</title>" in page
    assert "Acme Zeit" in page
    assert "LexTracker" not in page.replace("„LexTracker“", "")

    admin.get(reverse("accounts:logout"))
    anonymous = client.__class__().get(reverse("accounts:login")).text
    assert "Acme Zeit" in anonymous
    assert "LexTracker" not in anonymous


def test_pages_have_a_description_with_the_name(admin, client):
    assert '<meta name="description" content="LexTracker: Zeiterfassung und Projektsteuerung">' in (
        admin.get(reverse("core:dashboard")).text
    )

    save(admin, app_name="Acme Zeit")
    assert 'content="Acme Zeit: Zeiterfassung und Projektsteuerung"' in admin.get(reverse("core:dashboard")).text

    anonymous = client.__class__().get(reverse("accounts:login")).text
    assert 'content="Acme Zeit: Zeiterfassung und Projektsteuerung"' in anonymous


def test_the_description_follows_the_language(admin, user, english):
    user.language = "en"
    user.save()
    assert 'content="LexTracker: time tracking and project management"' in admin.get(reverse("core:dashboard")).text


def test_the_name_is_escaped(admin):
    save(admin, app_name="<b>Zeit</b>")
    assert "<b>Zeit</b>" not in admin.get(reverse("core:dashboard")).text


def test_an_empty_name_goes_back_to_the_default(admin):
    save(admin, app_name="Acme Zeit")
    save(admin, app_name="")
    assert "<title>Übersicht · LexTracker</title>" in admin.get(reverse("core:dashboard")).text


def test_the_name_has_a_limit(admin):
    response = save(admin, app_name="x" * 41)
    assert response.status_code == 200
    assert AppSettings.load().app_name == ""


def test_uploaded_logo_is_shown_and_served_to_everyone(admin, client):
    assert upload(admin, PNG).status_code == 302

    page = admin.get(reverse("core:dashboard")).text
    assert f'src="{reverse("core:logo")}?v=' in page
    assert f'<link rel="icon" href="{reverse("core:logo")}?v=' in page

    # The login page needs it before anyone is signed in.
    response = client.__class__().get(reverse("core:logo"))
    assert response.status_code == 200
    assert response["Content-Type"] == "image/png"
    assert response.content == PNG
    assert "sandbox" in response["Content-Security-Policy"]


def test_logo_is_not_read_for_every_page(admin):
    upload(admin, PNG)
    assert branding.load().logo_url
    assert "logo_data" in AppSettings.load().get_deferred_fields()


def test_svg_logo_is_served_as_svg(admin):
    upload(admin, SVG, "logo.svg")
    response = admin.get(reverse("core:logo"))
    assert response["Content-Type"] == "image/svg+xml"
    assert "apple-touch-icon" not in admin.get(reverse("core:dashboard")).text.split("</head>")[0].replace(
        "img/apple-touch-icon.png", ""
    )


def test_the_logo_can_be_replaced_and_removed(admin):
    upload(admin, PNG)
    jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 32
    upload(admin, jpeg, "logo.jpg")
    assert admin.get(reverse("core:logo"))["Content-Type"] == "image/jpeg"

    # Saving the form without a file keeps the logo.
    save(admin)
    assert admin.get(reverse("core:logo")).status_code == 200

    save(admin, remove_logo="on")
    assert admin.get(reverse("core:logo")).status_code == 404
    assert reverse("core:logo") not in admin.get(reverse("core:dashboard")).text


@pytest.mark.parametrize(
    ("content", "name"),
    [
        (b"not an image", "logo.png"),
        (b"GIF89a" + b"\x00" * 16, "logo.gif"),
        (b"<html><script>alert(1)</script></html>", "logo.svg"),
        (b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>', "logo.svg"),
        (PNG + b"\x00" * branding.LOGO_MAX_SIZE, "big.png"),
    ],
)
def test_unusable_logos_are_refused(admin, content, name):
    response = upload(admin, content, name, app_name="Acme Zeit")
    assert response.status_code == 200
    assert 'class="text-sm text-danger"' in response.text
    app_settings = AppSettings.load()
    assert not app_settings.logo_type
    assert app_settings.app_name == ""


def test_only_administrators_change_the_branding(client, user):
    user.role = User.Role.EMPLOYEE
    user.save()
    client.force_login(user)
    assert save(client, app_name="Acme Zeit").status_code == 403
    assert AppSettings.load().app_name == ""


def test_customers_may_load_the_logo():
    customer = User(username="kunde", role=User.Role.CUSTOMER)
    assert access.allowed(customer, "core:logo")
    assert not access.allowed(customer, "core:settings")


def test_authenticator_apps_show_the_name(admin, user):
    save(admin, app_name="Acme Zeit")
    device = mfa.pending_device(user)
    assert "issuer=Acme%20Zeit" in TOTPDevice.objects.get(pk=device.pk).config_url
    # Without a name: the default.
    save(admin, app_name="")
    assert "issuer=LexTracker" in TOTPDevice.objects.get(pk=device.pk).config_url


@pytest.fixture
def smtp(db) -> MailSettings:
    config = MailSettings.objects.create(pk=1, host="smtp.example.de", from_address="zeit@example.de", from_name="Zeit")
    config.set_password("smtp-geheim")
    config.save()
    return config


def test_mails_are_written_with_the_name(admin, smtp):
    save(admin, app_name="Acme Zeit")

    admin.post(reverse("mailer:test"), {"to": "kim@example.de"})
    [sent] = mail.outbox
    assert sent.subject == "Testmail von Acme Zeit"
    html = sent.alternatives[0].content
    assert "Acme Zeit" in html and "LexTracker" not in html
    assert "Acme Zeit" in sent.body and "LexTracker" not in sent.body

    admin.__class__().post(reverse("accounts:password_forgot"), {"identifier": "kim@example.de"})
    queued = OutgoingMail.objects.get()
    assert queued.subject == "Neues Passwort für Acme Zeit"
    assert "LexTracker" not in queued.text + queued.html
    assert "Diese E-Mail hat Acme Zeit automatisch verschickt." in queued.html


def test_no_template_has_the_name_written_in():
    """Names in templates come from ``brand.name``; a new hard-coded one would show up in every e-mail and page."""
    found = [
        str(p.relative_to(TEMPLATES)) for p in TEMPLATES.rglob("*") if p.is_file() and "LexTracker" in p.read_text()
    ]
    assert found == []


def test_mail_subject_follows_language_and_name(admin, user, smtp, english):
    user.language = "en"
    user.save()
    save(admin, app_name="Acme Zeit")
    admin.__class__().post(reverse("accounts:password_forgot"), {"identifier": "kim@example.de"})
    queued = OutgoingMail.objects.get()
    assert queued.subject == "New password for Acme Zeit"


def test_mcp_server_introduces_itself_with_the_name(client, user):
    AppSettings.objects.update_or_create(pk=1, defaults={"app_name": "Acme Zeit"})
    _, key = ApiToken.issue(user, "Test")
    message = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    response = client.post(
        "/mcp/", json.dumps(message), content_type="application/json", headers={"Authorization": f"Bearer {key}"}
    )
    result = response.json()["result"]
    assert result["serverInfo"]["title"] == "Acme Zeit"
    # The identifier stays, since clients key their configuration on it.
    assert result["serverInfo"]["name"] == "lextracker"
    assert result["instructions"].startswith("Acme Zeit tracks")
