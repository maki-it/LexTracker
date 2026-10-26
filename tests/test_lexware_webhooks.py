import json
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from django.utils import timezone

from core import scheduler
from core.models import AppSettings
from lexware import views, webhooks
from lexware.client import LexwareError
from lexware.models import LexwareConnection, WebhookEvent, WebhookSubscription
from tests.lexware_fakes import fake_client

pytestmark = pytest.mark.django_db

BASE_URL = "https://zeit.example.de"


@pytest.fixture
def token() -> str:
    return async_to_sync(webhooks.aensure_token)()


def call(client, token, payload=None, **extra):
    body = json.dumps(
        payload if payload is not None else {"eventType": "contact.changed", "resourceId": str(uuid.uuid4())}
    )
    return client.post(reverse("webhooks:lexware", args=[token]), body, content_type="application/json", **extra)


def test_call_is_noted_without_a_login(client, token):
    resource = uuid.uuid4()
    response = call(client, token, {"eventType": "contact.changed", "resourceId": str(resource), "other": "ignored"})

    assert response.status_code == 200
    event = WebhookEvent.objects.get()
    assert (event.event_type, event.resource_id, event.processed_at) == ("contact.changed", resource, None)


def test_lexware_checks_the_address_with_head(client, token):
    assert client.head(reverse("webhooks:lexware", args=[token])).status_code == 200
    assert not WebhookEvent.objects.exists()


def test_wrong_or_missing_secret_is_not_found(client, token):
    assert call(client, "falsch").status_code == 404
    assert client.head(reverse("webhooks:lexware", args=["falsch"])).status_code == 404

    # Without webhooks there is no secret, so no address works.
    LexwareConnection.objects.filter(pk=1).update(webhook_token="")
    assert call(client, token).status_code == 404
    assert call(client, "x").status_code == 404
    assert not WebhookEvent.objects.exists()


def test_bad_calls_are_refused(client, token):
    url = reverse("webhooks:lexware", args=[token])
    assert client.post(url, "kein json", content_type="application/json").status_code == 400
    assert client.post(url, "[1]", content_type="application/json").status_code == 400
    assert client.post(url, "x" * (views.WEBHOOK_MAX_BYTES + 1), content_type="application/json").status_code == 413
    assert client.put(url).status_code == 405
    assert not WebhookEvent.objects.exists()


def test_same_change_is_noted_once_until_it_is_taken_up(client, token):
    payload = {"eventType": "contact.changed", "resourceId": str(uuid.uuid4())}
    call(client, token, payload)
    call(client, token, payload)
    assert WebhookEvent.objects.count() == 1

    async_to_sync(webhooks.aclaim)("customers")
    call(client, token, payload)
    assert WebhookEvent.objects.count() == 2


def test_other_events_are_kept_as_done(client, token):
    call(client, token, {"eventType": "token.revoked"})
    call(client, token, {"eventType": "x" * 500})

    assert WebhookEvent.objects.filter(processed_at__isnull=False).count() == 2
    assert async_to_sync(webhooks.aclaim)("customers") == []


def test_claim_takes_only_the_calls_for_that_sync(client, token):
    call(client, token, {"eventType": "contact.created", "resourceId": str(uuid.uuid4())})
    call(client, token, {"eventType": "invoice.status.changed", "resourceId": str(uuid.uuid4())})

    assert len(async_to_sync(webhooks.aclaim)("customers")) == 1
    assert async_to_sync(webhooks.aclaim)("customers") == []
    claimed = async_to_sync(webhooks.aclaim)("invoices")
    assert len(claimed) == 1

    async_to_sync(webhooks.arelease)(claimed)
    assert len(async_to_sync(webhooks.aclaim)("invoices")) == 1


def test_old_calls_are_deleted(client, token):
    now = timezone.now()
    call(client, token, {"eventType": "token.revoked"})
    WebhookEvent.objects.update(processed_at=now - webhooks.KEEP_PROCESSED - timedelta(hours=1))
    call(client, token, {"eventType": "contact.changed", "resourceId": str(uuid.uuid4())})
    WebhookEvent.objects.filter(processed_at=None).update(received_at=now - webhooks.KEEP_PENDING - timedelta(hours=1))
    call(client, token, {"eventType": "invoice.deleted", "resourceId": str(uuid.uuid4())})

    assert async_to_sync(webhooks.aprune)(now) == 2
    assert WebhookEvent.objects.count() == 1


@pytest.fixture
def fake_jobs(monkeypatch, settings):
    """The scheduler's syncs, replaced by ones that note their calls and can be made to fail."""
    settings.LEXWARE_API_KEY = "test-key"
    state = SimpleNamespace(calls=[], fail=False)

    def recorder(key):
        async def run():
            state.calls.append(key)
            if state.fail:
                raise LexwareError("Lexware nicht erreichbar")
            return SimpleNamespace(summary="ok")

        return run

    monkeypatch.setattr(scheduler, "JOBS", [replace(job, run=recorder(job.key)) for job in scheduler.JOBS])
    return state


@pytest.mark.django_db(transaction=True)
async def test_a_call_runs_only_its_sync(fake_jobs):
    await webhooks.aensure_token()
    await webhooks.arecord("invoice.status.changed", uuid.uuid4())
    await webhooks.arecord("invoice.status.changed", uuid.uuid4())
    now = timezone.now()

    assert await scheduler.run_webhook_syncs({}, now) == ["invoice sync"]
    assert fake_jobs.calls == ["invoices"]
    # Nothing is left to do.
    assert await scheduler.run_webhook_syncs({}, now) == []


@pytest.mark.django_db(transaction=True)
async def test_failed_sync_is_tried_again_after_a_pause(fake_jobs):
    fake_jobs.fail = True
    await webhooks.arecord("contact.changed", uuid.uuid4())
    retry_at = {}
    now = timezone.now()

    assert await scheduler.run_webhook_syncs(retry_at, now) == ["customer import"]
    assert await WebhookEvent.objects.filter(processed_at__isnull=True).acount() == 1

    # Not before the pause is over.
    assert await scheduler.run_webhook_syncs(retry_at, now + timedelta(seconds=10)) == []
    assert fake_jobs.calls == ["customers"]

    fake_jobs.fail = False
    later = now + timedelta(seconds=scheduler.WEBHOOK_RETRY_AFTER + 1)
    assert await scheduler.run_webhook_syncs(retry_at, later) == ["customer import"]
    assert not await WebhookEvent.objects.filter(processed_at__isnull=True).aexists()
    assert retry_at == {}


@pytest.mark.django_db(transaction=True)
async def test_nothing_runs_without_api_key(settings):
    settings.LEXWARE_API_KEY = ""
    await webhooks.arecord("contact.changed", uuid.uuid4())
    assert await scheduler.run_webhook_syncs({}, timezone.now()) == []
    assert await WebhookEvent.objects.filter(processed_at__isnull=True).acount() == 1


def lexware_handler(requests, *, refuse=(), existing=()):
    """Lexware's event subscription endpoints: remembers what was asked and lists ``existing`` subscriptions."""

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            event_type = json.loads(request.content)["eventType"]
            if event_type in refuse:
                return httpx.Response(406, json={"message": "Callback URL not reachable"})
            return httpx.Response(201, json={"subscriptionId": str(uuid.uuid4()), "eventType": event_type})
        if request.method == "GET":
            return httpx.Response(200, json={"content": list(existing)})
        return httpx.Response(204)

    return handler


def subscribe(base_url=BASE_URL, **kwargs):
    requests = []
    client = fake_client(lexware_handler(requests, **kwargs))
    result = async_to_sync(webhooks.aenable)(client, base_url)
    return result, requests


def test_enable_subscribes_to_every_event_with_a_secret_address():
    result, requests = subscribe()

    assert result.subscribed == list(webhooks.EVENT_AREAS) and not result.failed
    token = LexwareConnection.objects.get().webhook_token
    posts = [json.loads(r.content) for r in requests if r.method == "POST"]
    assert {p["eventType"] for p in posts} == set(webhooks.EVENT_AREAS)
    assert {p["callbackUrl"] for p in posts} == {f"{BASE_URL}/webhooks/lexware/{token}/"}
    assert WebhookSubscription.objects.count() == len(webhooks.EVENT_AREAS)
    assert not WebhookSubscription.objects.filter(subscription_id=None).exists()


def test_refused_events_are_reported_but_do_not_stop_the_rest():
    result, _ = subscribe(refuse={"payment.changed"})

    assert "payment.changed" in result.failed and "payment.changed" not in result.subscribed
    assert len(result.subscribed) == len(webhooks.EVENT_AREAS) - 1
    assert LexwareConnection.objects.get().webhook_token


def test_nothing_accepted_leaves_no_address_behind():
    result, _ = subscribe(refuse=set(webhooks.EVENT_AREAS))

    assert not result.subscribed
    assert LexwareConnection.objects.get().webhook_token == ""
    assert not WebhookSubscription.objects.exists()


def test_enabling_again_replaces_the_subscriptions_and_the_secret():
    subscribe()
    old = LexwareConnection.objects.get().webhook_token
    old_ids = set(WebhookSubscription.objects.values_list("subscription_id", flat=True))

    _, requests = subscribe()

    assert LexwareConnection.objects.get().webhook_token != old
    deleted = {r.url.path.rsplit("/", 1)[1] for r in requests if r.method == "DELETE"}
    assert deleted == {str(i) for i in old_ids}
    assert WebhookSubscription.objects.count() == len(webhooks.EVENT_AREAS)


def test_disable_also_removes_subscriptions_that_lost_their_record(client):
    subscribe()
    token = LexwareConnection.objects.get().webhook_token
    lost, foreign = uuid.uuid4(), uuid.uuid4()
    existing = [
        {"subscriptionId": str(lost), "callbackUrl": f"{BASE_URL}/webhooks/lexware/{token}/"},
        {"subscriptionId": str(foreign), "callbackUrl": "https://other.example.de/hook/"},
    ]
    requests = []
    async_to_sync(webhooks.adisable)(fake_client(lexware_handler(requests, existing=existing)))

    deleted = {r.url.path.rsplit("/", 1)[1] for r in requests if r.method == "DELETE"}
    assert str(lost) in deleted and str(foreign) not in deleted
    assert not WebhookSubscription.objects.exists()
    assert LexwareConnection.objects.get().webhook_token == ""
    assert call(client, token).status_code == 404


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def lexware_api(monkeypatch, settings):
    """The settings page talks to this fake instead of Lexware."""
    settings.LEXWARE_API_KEY = "test-key"
    requests = []

    @asynccontextmanager
    async def connect():
        yield fake_client(lexware_handler(requests))

    monkeypatch.setattr(views, "client_from_settings", connect)
    return requests


def test_enable_from_the_settings_page(logged_in, lexware_api):
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": BASE_URL})

    response = logged_in.post(reverse("lexware:enable_webhooks"), follow=True)

    assert WebhookSubscription.objects.count() == len(webhooks.EVENT_AREAS)
    page = response.content.decode()
    assert "Lexware meldet Änderungen jetzt direkt" in page
    token = LexwareConnection.objects.get().webhook_token
    assert f"{BASE_URL}/webhooks/lexware/{token}/" in page
    assert "Webhooks entfernen" in page


def test_enable_needs_a_public_https_address(logged_in, lexware_api):
    response = logged_in.post(reverse("lexware:enable_webhooks"), follow=True)

    page = response.content.decode()
    assert "Lexware ruft nur Adressen mit HTTPS auf" in page
    assert "Adresse der App" in page and f"{reverse('core:settings')}?tab=general" in page
    assert not WebhookSubscription.objects.exists()
    assert not lexware_api


def test_disable_from_the_settings_page(logged_in, lexware_api):
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": BASE_URL})
    logged_in.post(reverse("lexware:enable_webhooks"))

    response = logged_in.post(reverse("lexware:disable_webhooks"), follow=True)

    assert not WebhookSubscription.objects.exists()
    page = response.content.decode()
    assert "Webhooks entfernt" in page
    assert "Webhooks einrichten" in page


def test_webhook_settings_are_for_admins(client, lexware_api):
    from accounts.models import User

    employee = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)

    assert client.post(reverse("lexware:enable_webhooks")).status_code == 403
    assert not lexware_api


def test_jobs_page_lists_the_webhook_check():
    from django.utils import timezone

    from core.jobs_overview import overview
    from core.models import AppSettings

    rows = async_to_sync(overview)(timezone.now(), AppSettings.objects.create(pk=1))
    assert "webhooks" in {row.key for row in rows}


@pytest.fixture(scope="module")
def signing():
    """A key pair that stands in for Lexware's: the public PEM and a function that signs like Lexware."""
    import base64

    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa

    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = (
        private.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )

    def sign(body: bytes) -> str:
        return base64.b64encode(private.sign(body, padding.PKCS1v15(), hashes.SHA512())).decode()

    return SimpleNamespace(pem=pem, sign=sign)


def signed_call(client, token, signing, payload, *, signature=None, body=None):
    body = body if body is not None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"HTTP_X_LXO_SIGNATURE": signing.sign(body) if signature is None else signature}
    return client.post(reverse("webhooks:lexware", args=[token]), body, content_type="application/json", **headers)


PAYLOAD = {"eventType": "contact.changed", "resourceId": "4d43ad14-671d-4e0c-fd4b-2fd8cc117eff"}


def test_with_a_key_only_signed_calls_are_accepted(client, token, signing):
    async_to_sync(webhooks.astore_public_key)(signing.pem)

    assert signed_call(client, token, signing, PAYLOAD).status_code == 200
    assert WebhookEvent.objects.count() == 1

    # Whitespace in the body: Lexware signs the compact form.
    spaced = json.dumps(PAYLOAD, indent=2).encode()
    compact = json.dumps(PAYLOAD, separators=(",", ":")).encode()
    assert signed_call(client, token, signing, PAYLOAD, body=spaced, signature=signing.sign(compact)).status_code == 200


def test_unsigned_or_wrongly_signed_calls_are_refused(client, token, signing):
    async_to_sync(webhooks.astore_public_key)(signing.pem)

    assert call(client, token, PAYLOAD).status_code == 401
    assert signed_call(client, token, signing, PAYLOAD, signature="kein base64!").status_code == 401
    assert signed_call(client, token, signing, PAYLOAD, signature=signing.sign(b"{}")).status_code == 401
    assert not WebhookEvent.objects.exists()
    # Lexware's check of a new address does not carry a signature.
    assert client.head(reverse("webhooks:lexware", args=[token])).status_code == 200


def test_public_key_must_be_an_rsa_key():
    for pem in ("irgendwas", "-----BEGIN PUBLIC KEY-----\nabc\n-----END PUBLIC KEY-----"):
        with pytest.raises(ValueError):
            async_to_sync(webhooks.astore_public_key)(pem)
    assert LexwareConnection.objects.filter(webhook_public_key="").count() == LexwareConnection.objects.count()


def test_public_key_from_the_settings_page(logged_in, lexware_api, signing):
    page = logged_in.post(reverse("lexware:save_webhook_key"), {"public_key": "kein Schlüssel"}, follow=True)
    assert "kein öffentlicher Schlüssel" in page.content.decode()

    logged_in.post(reverse("lexware:save_webhook_key"), {"public_key": signing.pem})
    assert LexwareConnection.objects.get().webhook_public_key == signing.pem.strip()
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": BASE_URL})
    logged_in.post(reverse("lexware:enable_webhooks"))
    assert "Signatur wird geprüft" in logged_in.get(reverse("core:settings") + "?tab=lexware").content.decode()

    logged_in.post(reverse("lexware:remove_webhook_key"))
    assert LexwareConnection.objects.get().webhook_public_key == ""


def test_removing_the_api_key_forgets_the_subscriptions(logged_in, lexware_api):
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": BASE_URL})
    logged_in.post(reverse("lexware:enable_webhooks"))
    assert WebhookSubscription.objects.exists()

    logged_in.post(reverse("lexware:remove_key"))

    # Lexware removes them together with the key.
    assert not WebhookSubscription.objects.exists()
    assert LexwareConnection.objects.get().webhook_token == ""


def test_a_new_api_key_subscribes_again(logged_in, lexware_api, monkeypatch):
    from lexware import credentials
    from lexware.schemas import Profile

    async def check(api_key):
        return Profile(companyName="Maki IT")

    monkeypatch.setattr(credentials, "acheck", check)
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": BASE_URL})
    logged_in.post(reverse("lexware:enable_webhooks"))
    old_token = LexwareConnection.objects.get().webhook_token
    lexware_api.clear()

    logged_in.post(reverse("lexware:save_key"), {"api_key": "neuer-schluessel-1234"})

    assert LexwareConnection.objects.get().webhook_token not in ("", old_token)
    assert len([r for r in lexware_api if r.method == "POST"]) == len(webhooks.EVENT_AREAS)


def test_address_of_the_app_is_a_general_setting(logged_in):
    from tests.test_branding import SETTINGS

    page = logged_in.get(reverse("core:settings") + "?tab=general").content.decode()
    assert 'name="app_url"' in page

    logged_in.post(reverse("core:settings"), SETTINGS | {"app_url": "https://zeit.example.de/"})
    assert async_to_sync(AppSettings.aurl)() == "https://zeit.example.de"


def test_address_moves_from_the_mail_settings():
    """The migration takes over what was entered with the e-mail settings."""
    import importlib

    copy_address = importlib.import_module("core.migrations.0015_app_url").copy_address

    class Rows:
        def __init__(self, address):
            self.objects = self
            self._address = address
            self.saved = None

        def using(self, alias):
            return self

        def values_list(self, *args, **kwargs):
            return self

        def first(self):
            return self._address

        def update_or_create(self, **kwargs):
            self.saved = kwargs

    class Apps:
        def __init__(self, address):
            self.mail, self.app = Rows(address), Rows(None)

        def get_model(self, app, name):
            return self.mail if name == "MailSettings" else self.app

    apps = Apps("https://zeit.example.de")
    copy_address(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    assert apps.app.saved == {"pk": 1, "defaults": {"app_url": "https://zeit.example.de"}}

    apps = Apps("")
    copy_address(apps, SimpleNamespace(connection=SimpleNamespace(alias="default")))
    assert apps.app.saved is None
