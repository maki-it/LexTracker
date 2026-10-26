import logging
from functools import partial

import httpx
import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse

from accounts.models import User
from lexware import credentials
from lexware.client import LexwareClient, LexwareError, LexwareUnauthorized
from lexware.models import LexwareConnection
from lexware.schemas import Profile

pytestmark = pytest.mark.django_db

API_KEY = "lx-secret-key-0123456789abcdef"


@pytest.fixture
def admin(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def accept_key(monkeypatch):
    checked = []

    async def check(api_key):
        checked.append(api_key)
        return Profile(companyName="Maki IT")

    monkeypatch.setattr(credentials, "acheck", check)
    return checked


def stored_key() -> str:
    return async_to_sync(credentials.aget_api_key)()


def test_key_is_stored_encrypted(settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY, company_name="Maki IT")

    row = LexwareConnection.objects.get()
    assert API_KEY not in row.encrypted_api_key
    assert row.key_suffix == "cdef"
    assert stored_key() == API_KEY


def test_other_secret_key_cannot_decrypt(settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY)

    settings.SECRET_KEY = "a-different-secret"
    assert stored_key() == ""
    assert async_to_sync(credentials.astatus)().unreadable


def test_secret_key_fallback_decrypts(settings):
    settings.LEXWARE_API_KEY = ""
    old_secret = settings.SECRET_KEY
    async_to_sync(credentials.astore)(API_KEY)

    settings.SECRET_KEY = "a-new-secret"
    settings.SECRET_KEY_FALLBACKS = [old_secret]
    assert stored_key() == API_KEY


def test_environment_variable_is_the_fallback(settings):
    settings.LEXWARE_API_KEY = "env-key-9999"
    status = async_to_sync(credentials.astatus)()
    assert status.source == "env" and status.masked.endswith("9999")
    assert stored_key() == "env-key-9999"

    # A key entered in the app wins.
    async_to_sync(credentials.astore)(API_KEY)
    assert stored_key() == API_KEY
    assert async_to_sync(credentials.astatus)().source == "app"


def test_settings_page_saves_key_after_check(admin, accept_key, settings):
    settings.LEXWARE_API_KEY = ""
    response = admin.post(reverse("lexware:save_key"), {"api_key": f"  {API_KEY} "}, follow=True)

    assert accept_key == [API_KEY]
    assert stored_key() == API_KEY
    assert "geprüft und gespeichert (Maki IT)" in response.text
    # Only the masked key is shown, never the key itself.
    assert API_KEY not in response.text
    assert "••••••••cdef" in response.text


def test_key_can_be_replaced_without_the_old_one(admin, accept_key, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)("old-key-aaaa")

    admin.post(reverse("lexware:save_key"), {"api_key": API_KEY})

    assert stored_key() == API_KEY


def test_rejected_key_is_not_stored(admin, monkeypatch, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)("old-key-aaaa")

    async def reject(api_key):
        raise LexwareError("Lexware hat den API-Schlüssel abgelehnt.")

    monkeypatch.setattr(credentials, "acheck", reject)
    response = admin.post(reverse("lexware:save_key"), {"api_key": API_KEY}, follow=True)

    assert "abgelehnt" in response.text
    assert stored_key() == "old-key-aaaa"


def test_remove_key(admin, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY)

    admin.post(reverse("lexware:remove_key"))

    assert stored_key() == ""
    assert "Noch kein API-Schlüssel" in admin.get(reverse("core:settings")).text


def test_test_connection(admin, accept_key, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY)

    response = admin.post(reverse("lexware:test_key"), follow=True)

    assert accept_key == [API_KEY]
    assert "Verbindung zu Lexware Office klappt (Maki IT)" in response.text


def test_rejected_key_is_not_shown_as_connected(admin, accept_key, monkeypatch, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY, company_name="Maki IT")
    assert "verbunden" in admin.get(reverse("core:settings")).text

    async def reject(api_key):
        raise LexwareUnauthorized("Lexware hat den API-Schlüssel abgelehnt.")

    monkeypatch.setattr(credentials, "acheck", reject)
    response = admin.post(reverse("lexware:test_key"), follow=True)

    assert "Verbindung fehlgeschlagen" in response.text
    assert "Schlüssel ungültig" in response.text
    assert "von Lexware abgelehnt" in response.text
    assert 'badge badge-success">verbunden' not in response.text
    assert async_to_sync(credentials.astatus)().rejected_at is not None
    # The stored key stays, so it can be tested again once the key works.
    assert stored_key() == API_KEY


def test_working_connection_clears_rejection(admin, accept_key, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY)
    async_to_sync(credentials.amark_rejected)()

    response = admin.post(reverse("lexware:test_key"), follow=True)

    assert async_to_sync(credentials.astatus)().rejected_at is None
    assert 'badge badge-success">verbunden' in response.text
    assert "Schlüssel ungültig" not in response.text


def test_saving_a_new_key_clears_rejection(admin, accept_key, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)("old-key-aaaa")
    async_to_sync(credentials.amark_rejected)()

    admin.post(reverse("lexware:save_key"), {"api_key": API_KEY})

    assert async_to_sync(credentials.astatus)().rejected_at is None


def test_unreachable_lexware_does_not_mark_the_key_as_rejected(admin, monkeypatch, settings):
    settings.LEXWARE_API_KEY = ""
    async_to_sync(credentials.astore)(API_KEY)

    async def unreachable(api_key):
        raise LexwareError("Lexware ist nicht erreichbar: timeout")

    monkeypatch.setattr(credentials, "acheck", unreachable)
    response = admin.post(reverse("lexware:test_key"), follow=True)

    assert "Verbindung fehlgeschlagen" in response.text
    assert async_to_sync(credentials.astatus)().rejected_at is None


def test_employees_cannot_set_the_key(client, accept_key):
    employee = User.objects.create_user(username="ma", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)

    assert client.post(reverse("lexware:save_key"), {"api_key": API_KEY}).status_code == 403
    assert accept_key == []


def test_key_never_appears_in_logs(admin, monkeypatch, caplog, settings):
    """The real check against a fake Lexware, which rejects the key, logged at DEBUG level."""
    settings.LEXWARE_API_KEY = ""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["Authorization"])
        return httpx.Response(401)

    fake = partial(LexwareClient, requests_per_second=0, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(credentials, "LexwareClient", fake)
    caplog.set_level(logging.DEBUG)

    response = admin.post(reverse("lexware:save_key"), {"api_key": API_KEY}, follow=True)

    assert seen == [f"Bearer {API_KEY}"]
    assert "abgelehnt" in response.text
    assert API_KEY not in caplog.text
    assert API_KEY not in response.text


def test_dashboard_hints_missing_key(admin, settings):
    settings.LEXWARE_API_KEY = ""
    assert "noch nicht verbunden" in admin.get(reverse("core:dashboard")).text

    async_to_sync(credentials.astore)(API_KEY)
    assert "noch nicht verbunden" not in admin.get(reverse("core:dashboard")).text
