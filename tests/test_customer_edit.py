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
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "80", "notes": ""},
    )

    customer.refresh_from_db()
    assert customer.default_hourly_rate == Decimal("80")


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
            "invoice_detail": "summary",
            "lexware_sync_interval": "30",
            "lexware_sync_from": "07:00",
            "lexware_sync_until": "19:00",
            "invoice_sync_interval": "1440",
            "invoice_sync_from": "06:00",
            "login_max_attempts": "5",
            "login_lockout_minutes": "15",
            "backup_enabled": "on",
            "backup_time": "03:00",
            "backup_keep": "14",
            "weekly_report_weekday": "0",
            "weekly_report_time": "07:00",
            "timer_reminder_hours": "10",
            "overdue_notice": "admins",
            "overdue_notice_days": "3",
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


# Notes


def test_apply_to_contact_sends_a_note_changed_here():
    raw = contact("ACME GmbH", note="alt")
    customer = Customer(name="ACME GmbH", notes=" neu \n", lexware_note="alt")

    assert apply_to_contact(raw, customer)["note"] == "neu"


def test_apply_to_contact_removes_a_deleted_note():
    raw = contact("ACME GmbH", note="alt")

    assert "note" not in apply_to_contact(raw, Customer(name="ACME GmbH", notes="", lexware_note="alt"))


def test_apply_to_contact_keeps_a_note_changed_in_lexware():
    raw = contact("ACME GmbH", note="in Lexware geändert")
    customer = Customer(name="ACME GmbH", notes="alt", lexware_note="alt")

    assert apply_to_contact(raw, customer)["note"] == "in Lexware geändert"


def test_saving_a_note_sends_it_to_lexware(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", version=4)
    customer = Customer.objects.create(
        name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4, lexware_note=""
    )
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "Zahlt pünktlich"},
    )

    assert response.status_code == 302
    assert json.loads(requests[1].content)["note"] == "Zahlt pünktlich"
    customer.refresh_from_db()
    assert (customer.notes, customer.lexware_note) == ("Zahlt pünktlich", "Zahlt pünktlich")


def test_note_that_lexware_does_not_have_yet_goes_out_with_any_save(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", version=4)
    customer = Customer.objects.create(
        name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4, notes="vom Anfang", lexware_note="x"
    )
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "80", "notes": "vom Anfang"},
    )

    assert json.loads(requests[1].content)["note"] == "vom Anfang"


def test_first_save_keeps_the_note_that_is_in_lexware(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", version=4, note="aus Lexware")
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4)
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "lokal"},
    )

    assert json.loads(requests[1].content)["note"] == "lokal\n\naus Lexware"
    customer.refresh_from_db()
    assert customer.notes == "lokal\n\naus Lexware"


def test_note_for_lexware_may_not_be_too_long(logged_in, monkeypatch):
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.uuid4(), lexware_version=1)
    monkeypatch.setattr("customers.views.client_from_settings", lambda: pytest.fail("Lexware called"))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "x" * 1001},
    )

    assert response.status_code == 200
    assert "1000" in response.text


def test_customer_without_lexware_may_have_long_notes(logged_in):
    customer = Customer.objects.create(name="Lokal")

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "Lokal", "email": "", "phone": "", "default_hourly_rate": "", "notes": "x" * 2000},
    )

    assert response.status_code == 302
    customer.refresh_from_db()
    assert len(customer.notes) == 2000


def two_business_emails() -> dict:
    return contact("ACME GmbH", version=4, emailAddresses={"business": ["test@mail-tester.com", "kontakt@acme.de"]})


def test_contact_with_two_entries_is_read_only_for_the_api():
    from customers.lexware import ReadOnlyContact, ensure_writable

    ensure_writable(contact("ACME GmbH", emailAddresses={"business": ["a@acme.de"], "private": ["b@acme.de"]}))
    with pytest.raises(ReadOnlyContact) as error:
        ensure_writable(
            contact(
                "ACME GmbH",
                emailAddresses={"business": ["a@acme.de", "b@acme.de"]},
                company={"name": "ACME GmbH", "contactPersons": [{"lastName": "A"}, {"lastName": "B"}]},
            )
        )
    assert error.value.paths == ["company.contactPersons", "emailAddresses.business"]
    assert "Ansprechpartner, E-Mail-Adressen (geschäftlich)" in str(error.value)


def test_note_of_a_read_only_contact_stays_in_lextracker(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = two_business_emails()
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4)
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "Nur hier"},
        follow=True,
    )

    # Lexware was only asked, not changed.
    assert [r.method for r in requests] == ["GET"]
    customer.refresh_from_db()
    assert customer.notes == "Nur hier"
    page = response.content.decode()
    assert "gespeichert" in page
    assert "Die Notiz bleibt nur in LexTracker" in page
    assert "E-Mail-Adressen (geschäftlich)" in page


def test_other_lexware_fields_of_a_read_only_contact_are_refused(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = two_business_emails()
    customer = Customer.objects.create(name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4)
    requests = []
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, requests)))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "Neu GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": "Nur hier"},
    )

    assert response.status_code == 200
    assert "ändere bitte in Lexware" in response.content.decode()
    assert [r.method for r in requests] == ["GET"]
    customer.refresh_from_db()
    assert (customer.name, customer.notes) == ("ACME GmbH", "")


def test_local_fields_of_a_read_only_contact_can_still_be_saved(logged_in, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = two_business_emails()
    customer = Customer.objects.create(
        name="ACME GmbH", lexware_id=uuid.UUID(raw["id"]), lexware_version=4, notes="Nur hier", lexware_note=""
    )
    monkeypatch.setattr("customers.views.client_from_settings", lambda: fake_client(lexware_contact_api(raw, [])))

    response = logged_in.post(
        reverse("customers:edit", args=[customer.pk]),
        {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "95", "notes": "Nur hier"},
    )

    assert response.status_code == 302
    customer.refresh_from_db()
    assert customer.default_hourly_rate == Decimal("95")
