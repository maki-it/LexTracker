import json
import uuid
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AppSettings
from core.scheduler import run_due_jobs
from customers.lexware import apply_to_contact
from customers.models import Customer
from tests.lexware_fakes import contact, fake_client, page, serve_pages

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_apply_to_contact_changes_only_what_differs():
    raw = contact(
        "ACME GmbH",
        emailAddresses={"office": ["info@acme.de"], "private": ["chef@acme.de"]},
        phoneNumbers={"mobile": ["0170 1"]},
    )
    customer = Customer(name="ACME Holding GmbH", email="buero@acme.de", phone="0170 1")

    result = apply_to_contact(raw, customer)

    assert result["company"]["name"] == "ACME Holding GmbH"
    assert result["emailAddresses"] == {"office": ["buero@acme.de"], "private": ["chef@acme.de"]}
    assert result["phoneNumbers"] == {"mobile": ["0170 1"]}


def test_apply_to_contact_for_a_person_adds_missing_email():
    raw = contact(company=None, person={"firstName": "Max", "lastName": "Muster"})
    raw.pop("company")
    customer = Customer(name="Max Mustermann", email="max@example.de", phone="")

    result = apply_to_contact(raw, customer)

    assert result["person"] == {"firstName": "Max", "lastName": "Mustermann"}
    assert result["emailAddresses"] == {"business": ["max@example.de"]}


def lexware_contact_api(raw: dict, requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": raw["id"], "version": raw["version"] + 1})
        return httpx.Response(200, json=raw)

    return handler


def test_edit_pushes_lexware_fields_and_saves(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", version=4)
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4)
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME Holding GmbH", "email": "", "phone": "", "default_hourly_rate": "95", "notes": ""},
    )

    assert response.status_code == 302
    assert [r.method for r in requests] == ["GET", "PUT"]
    sent = json.loads(requests[1].content)
    assert sent["company"]["name"] == "ACME Holding GmbH"
    assert sent["version"] == 4
    customer.refresh_from_db()
    assert customer.name == "ACME Holding GmbH"
    assert customer.default_hourly_rate == Decimal("95")
    assert customer.lexware_version == 5


def test_edit_of_local_fields_does_not_call_lexware(logged_in, monkeypatch):
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.uuid4(), lexware_version=1)
    monkeypatch.setattr("customers.views.client_from_settings", lambda: pytest.fail("Lexware called"))

    logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "Wichtig"},
    )

    customer.refresh_from_db()
    assert customer.notes == "Wichtig"


def test_edit_keeps_data_when_lexware_fails(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.uuid4(), lexware_version=1)
    monkeypatch.setattr(
        "customers.views.client_from_settings",
        lambda: fake_client(lambda request: httpx.Response(409, json={"message": "Version veraltet"})),
    )

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "Neu GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": ""},
    )

    assert "konnte nicht in Lexware gespeichert werden" in response.text
    customer.refresh_from_db()
    assert customer.name == "ACME GmbH"


def test_settings_page_saves_settings(logged_in):
    response = logged_in.post(
        reverse("core:settings"),
        {
            "default_hourly_rate": "85",
            "time_rounding": "15",
            "lexware_sync_interval": "30",
            "lexware_sync_from": "07:00",
            "lexware_sync_until": "19:00",
            "invoice_sync_interval": "1440",
            "invoice_sync_from": "06:00",
        },
    )

    assert response.status_code == 302
    app_settings = AppSettings.load()
    assert app_settings.default_hourly_rate == Decimal("85")
    assert app_settings.lexware_sync_interval == 30
    assert app_settings.time_rounding == 15
    assert str(app_settings.lexware_sync_from) == "07:00:00"
    assert app_settings.invoice_sync_interval == 1440
    assert app_settings.invoice_sync_until is None


def test_settings_page_is_for_admins_only(client, user):
    user.role = user.Role.EMPLOYEE
    user.save()
    client.force_login(user)

    assert client.get(reverse("core:settings")).status_code == 403


@pytest.mark.django_db(transaction=True)
async def test_scheduler_imports_when_due(monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    handler = serve_pages(page([contact("ACME GmbH")]))
    monkeypatch.setattr("customers.sync.client_from_settings", lambda: fake_client(handler))
    now = timezone.now()

    assert "customer import" in await run_due_jobs(now)
    assert await Customer.objects.acount() == 1
    app_settings = await AppSettings.aload()
    assert app_settings.lexware_sync_status == "1 neu, 0 aktualisiert, 0 unverändert."

    # Not again before the interval (60 minutes by default) has passed.
    assert "customer import" not in await run_due_jobs(now + timedelta(minutes=30))
    assert "customer import" in await run_due_jobs(now + timedelta(minutes=61))

    await AppSettings.objects.filter(pk=1).aupdate(lexware_sync_interval=0)
    assert "customer import" not in await run_due_jobs(now + timedelta(days=1))
    assert len(handler.requests) == 2


@pytest.mark.django_db(transaction=True)
async def test_scheduler_records_failures(monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    monkeypatch.setattr("customers.sync.client_from_settings", lambda: fake_client(lambda request: httpx.Response(401)))

    assert "customer import" in await run_due_jobs(timezone.now())

    app_settings = await AppSettings.aload()
    assert app_settings.lexware_sync_failed
    assert "API-Schlüssel" in app_settings.lexware_sync_status
