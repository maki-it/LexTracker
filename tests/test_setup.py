from datetime import time

import pytest
from asgiref.sync import async_to_sync
from django.core import mail
from django.core.management import call_command
from django.urls import reverse

from accounts.models import User
from core.models import AppSettings
from customers.sync import SyncResult
from lexware import credentials
from lexware.schemas import Profile
from mailer import outbox
from mailer.models import MailSettings
from setup.code import setup_code, setup_path

pytestmark = pytest.mark.django_db

API_KEY = "lx-secret-key-0123456789abcdef"
ACCOUNT = {
    "username": "kim",
    "first_name": "Kim",
    "email": "kim@example.com",
    "password1": "ein-langes-passwort-42",
    "password2": "ein-langes-passwort-42",
}


@pytest.fixture
def unlocked(client):
    """A browser that opened the setup link from the log."""
    response = client.get(setup_path())
    assert response.url == reverse("setup:account")
    return client


@pytest.fixture
def accept_key(monkeypatch):
    async def check(api_key):
        return Profile(companyName="Maki IT")

    monkeypatch.setattr(credentials, "acheck", check)


@pytest.mark.parametrize("path", ["/", "/kunden/", "/accounts/login/", "/einstellungen/"])
def test_fresh_instance_leads_to_setup(client, path):
    response = client.get(path)
    assert response.status_code == 302
    assert response.url == reverse("setup:account")


def test_health_stays_reachable(client):
    assert client.get(reverse("core:health")).status_code == 200


def test_setup_creates_admin_and_logs_in(unlocked, client, settings, accept_key):
    settings.LEXWARE_API_KEY = ""
    assert "Admin-Konto" in client.get(reverse("setup:account")).text

    response = client.post(reverse("setup:account"), ACCOUNT)

    assert response.url == reverse("setup:lexware")
    user = User.objects.get()
    assert user.role == User.Role.ADMIN and user.is_superuser and user.is_staff
    assert user.check_password(ACCOUNT["password1"])
    # The new administrator is logged in and goes on with the Lexware key.
    assert "Lexware Office verbinden" in client.get(response.url).text


def test_full_setup_ends_on_start_page(unlocked, client, settings, accept_key, monkeypatch):
    settings.LEXWARE_API_KEY = ""
    imported = []

    async def fake_sync():
        imported.append(True)
        return SyncResult(created=3)

    monkeypatch.setattr("setup.views.sync_and_record", fake_sync)
    client.post(reverse("setup:account"), ACCOUNT)

    response = client.post(reverse("setup:lexware"), {"api_key": API_KEY})
    assert response.url == reverse("setup:mail")
    assert async_to_sync(credentials.aget_api_key)() == API_KEY

    mail_data = {
        "host": "smtp.example.de",
        "port": "587",
        "security": "starttls",
        "password": "smtp-geheim",
        "from_address": "zeit@example.de",
        "from_name": "LexTracker",
        "base_url": "https://zeit.example.de",
    }
    response = client.post(reverse("setup:mail"), mail_data)
    assert response.url == reverse("setup:backup")
    assert MailSettings.objects.get().password == "smtp-geheim"

    response = client.post(
        reverse("setup:backup"), {"backup_enabled": "on", "backup_time": "02:30", "backup_keep": "7"}
    )
    assert response.url == reverse("setup:done")
    app_settings = AppSettings.load()
    assert app_settings.backup_enabled and app_settings.backup_time == time(2, 30) and app_settings.backup_keep == 7
    summary = client.get(reverse("setup:done")).text
    assert "Maki IT" in summary and "ab 02:30 Uhr, 7 Kopien" in summary
    assert "E-Mail-Versand über smtp.example.de" in summary

    response = client.post(reverse("setup:done"), {"import_customers": "1"}, follow=True)

    assert response.redirect_chain[-1][0] == reverse("core:dashboard")
    assert imported == [True]
    assert "Einrichtung ist abgeschlossen" in response.text


def test_lexware_step_can_be_skipped(unlocked, client, settings):
    settings.LEXWARE_API_KEY = ""
    client.post(reverse("setup:account"), ACCOUNT)
    assert reverse("setup:mail") in client.get(reverse("setup:lexware")).text
    # Empty: no e-mail, on to the backup.
    response = client.post(reverse("setup:mail"), {"port": "587", "security": "starttls"})
    assert response.url == reverse("setup:backup")
    assert not MailSettings.objects.get().is_configured
    # Unchecked: no automatic backups.
    client.post(reverse("setup:backup"), {"backup_time": "03:00", "backup_keep": "14"})
    assert not AppSettings.load().backup_enabled

    response = client.get(reverse("setup:done"))

    assert "noch nicht verbunden" in response.text
    assert "Keine automatische Datensicherung" in response.text
    assert "E-Mail-Versand noch nicht eingerichtet" in response.text
    assert "Kunden jetzt" not in response.text
    assert client.post(reverse("setup:done")).url == reverse("core:dashboard")


def test_mail_step_sends_a_test_mail_to_the_admin(unlocked, client, settings):
    settings.LEXWARE_API_KEY = ""
    client.post(reverse("setup:account"), ACCOUNT)
    data = {
        "host": "smtp.example.de",
        "port": "587",
        "security": "starttls",
        "from_address": "zeit@example.de",
        "from_name": "LexTracker",
        "test": "1",
    }

    response = client.post(reverse("setup:mail"), data)

    assert response.status_code == 200
    assert "Testmail an kim@example.com verschickt" in response.text
    assert mail.outbox[0].to == ["kim@example.com"]
    # The settings are saved even though the page stays, so "Weiter" has something to continue with.
    assert MailSettings.objects.get().is_configured


def test_mail_step_shows_the_server_error(unlocked, client, monkeypatch):
    client.post(reverse("setup:account"), ACCOUNT)
    monkeypatch.setattr(outbox, "deliver", lambda config, messages: ["Connection refused"])
    data = {"host": "smtp.example.de", "port": "465", "security": "ssl", "from_address": "zeit@example.de", "test": "1"}

    response = client.post(reverse("setup:mail"), data)

    assert "nicht verschickt: Connection refused" in response.text


def test_mail_step_warns_about_port_and_encryption_that_do_not_fit(unlocked, client):
    client.post(reverse("setup:account"), ACCOUNT)
    data = {"host": "smtp.example.de", "port": "587", "security": "ssl", "from_address": "zeit@example.de", "test": "1"}

    response = client.post(reverse("setup:mail"), data)

    assert response.status_code == 200
    assert "Port 587 nutzt STARTTLS" in response.text
    assert not MailSettings.objects.get().host


def test_setup_is_closed_once_an_account_exists(client, user):
    response = client.get(reverse("setup:account"))
    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))

    client.post(reverse("setup:account"), ACCOUNT)
    assert User.objects.count() == 1


def test_later_steps_need_the_setup_account(client):
    assert client.get(reverse("setup:lexware")).url == reverse("setup:account")


def test_employee_cannot_open_setup(client):
    employee = User.objects.create_user(username="ma", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)
    assert client.get(reverse("setup:lexware")).status_code == 403


def test_account_needs_the_setup_code(client, caplog):
    response = client.get(reverse("setup:account"))
    assert "Einrichtungscode" in response.text
    # The link with the code goes to the log, never to the page.
    assert setup_code() in caplog.text
    assert setup_code() not in response.text

    client.post(reverse("setup:account"), ACCOUNT)
    assert not User.objects.exists()

    response = client.post(reverse("setup:account"), {"code": "falsch"})
    assert "Der Code stimmt nicht" in response.text

    assert client.post(reverse("setup:account"), {"code": f" {setup_code().upper()} "}).url == reverse("setup:account")
    client.post(reverse("setup:account"), ACCOUNT)
    assert User.objects.count() == 1


def test_setup_link_command(capsys, user):
    call_command("setup_link")
    assert "already set up" in capsys.readouterr().out


def test_setup_link_command_on_fresh_instance(capsys):
    call_command("setup_link")
    assert setup_path() in capsys.readouterr().out
