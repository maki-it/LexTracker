import json
import uuid

import httpx
import pytest
from django.urls import reverse

from accounts.models import User
from customers.lexware import apply_billing_address, billing_address
from customers.models import Customer
from tests.lexware_fakes import contact, fake_client

pytestmark = pytest.mark.django_db

ADDRESS = {"street": "Hauptstr. 1", "zip": "10115", "city": "Berlin", "countryCode": "DE"}


@pytest.fixture
def lexware_contact():
    return contact(
        "ACME GmbH",
        version=3,
        addresses={"billing": [{**ADDRESS, "supplement": "Etage 2"}], "shipping": [{"street": "Lager 5"}]},
        emailAddresses={"business": ["info@acme.de"]},
        note="bleibt",
    )


@pytest.fixture
def customer(lexware_contact):
    return Customer.objects.create(
        name="ACME GmbH", email="info@acme.de", lexware_id=uuid.UUID(lexware_contact["id"]), lexware_version=3
    )


@pytest.fixture
def customer_user(customer):
    return User.objects.create_user(
        username="acme", password="geheim-123", role=User.Role.CUSTOMER, customer=customer, portal_contact=True
    )


@pytest.fixture
def lexware(monkeypatch, settings, lexware_contact):
    """A fake Lexware that serves the contact and records what is sent."""
    settings.LEXWARE_API_KEY = "test-key"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "PUT":
            return httpx.Response(200, json={"id": lexware_contact["id"], "version": lexware_contact["version"] + 1})
        return httpx.Response(200, json=lexware_contact)

    monkeypatch.setattr("portal.views.client_from_settings", lambda: fake_client(handler))
    return requests


def form_data(**changes) -> dict:
    return {
        "name": "ACME GmbH",
        "supplement": "Etage 2",
        **ADDRESS,
        "email": "info@acme.de",
        "phone": "",
        "version": "3",
        **changes,
    }


def test_billing_address_helpers_keep_unknown_fields():
    raw = {"addresses": {"billing": [{"street": "Alt 1", "zip": "1", "city": "X", "countryCode": "AT", "extra": 1}]}}

    apply_billing_address(raw, {"street": "Neu 2", "zip": "2", "city": "Y", "countryCode": "DE", "supplement": ""})

    expected = {"street": "Neu 2", "zip": "2", "city": "Y", "countryCode": "DE", "extra": 1}
    assert raw["addresses"]["billing"] == [expected]
    assert billing_address({})["street"] == ""
    assert apply_billing_address({}, ADDRESS)["addresses"]["billing"] == [ADDRESS]


def test_contact_page_is_off_by_default(client, customer):
    user = User.objects.create_user(username="acme", password="x-123456", role=User.Role.CUSTOMER, customer=customer)
    client.force_login(user)

    assert not user.portal_contact
    assert client.get(reverse("portal:contact")).status_code == 403
    assert "Kontaktdaten" not in client.get(reverse("portal:overview")).text


def test_contact_page_shows_the_contact_from_lexware(client, customer_user, lexware):
    client.force_login(customer_user)

    response = client.get(reverse("portal:contact"))

    assert response.status_code == 200
    assert 'value="Hauptstr. 1"' in response.text
    assert 'value="Etage 2"' in response.text
    assert 'name="version" value="3"' in response.text
    assert [r.method for r in lexware] == ["GET"]


def test_saving_writes_the_contact_back_to_lexware(client, customer_user, customer, lexware):
    client.force_login(customer_user)

    response = client.post(
        reverse("portal:contact"),
        form_data(name="ACME Holding GmbH", street="Neue Str. 9", supplement="", email="buchhaltung@acme.de"),
    )

    assert response.status_code == 302
    assert [r.method for r in lexware] == ["GET", "PUT"]
    assert lexware[1].url.path.endswith(f"contacts/{customer.lexware_id}")
    sent = json.loads(lexware[1].content)
    assert sent["version"] == 3
    assert sent["company"]["name"] == "ACME Holding GmbH"
    assert sent["addresses"]["billing"] == [{**ADDRESS, "street": "Neue Str. 9"}]
    # What the form does not cover is sent back unchanged.
    assert sent["addresses"]["shipping"] == [{"street": "Lager 5"}]
    assert sent["note"] == "bleibt"
    assert sent["emailAddresses"] == {"business": ["buchhaltung@acme.de"]}
    customer.refresh_from_db()
    assert customer.name == "ACME Holding GmbH"
    assert customer.email == "buchhaltung@acme.de"
    assert customer.lexware_version == 4


def test_a_change_in_the_meantime_is_not_overwritten(client, customer_user, customer, lexware):
    client.force_login(customer_user)

    response = client.post(reverse("portal:contact"), form_data(street="Neue Str. 9", version="2"))

    assert response.status_code == 200
    assert "in der Zwischenzeit geändert" in response.text
    # The typed address stays, and the form now carries the current version.
    assert 'value="Neue Str. 9"' in response.text
    assert 'name="version" value="3"' in response.text
    assert [r.method for r in lexware] == ["GET"]
    customer.refresh_from_db()
    assert customer.lexware_version == 3


def test_lexware_rejecting_the_change_keeps_the_form(client, customer_user, customer, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    raw = contact("ACME GmbH", id=customer.lexware_id, version=3)

    def handler(request):
        if request.method == "PUT":
            return httpx.Response(409, json={"message": "Version veraltet"})
        return httpx.Response(200, json=raw)

    monkeypatch.setattr("portal.views.client_from_settings", lambda: fake_client(handler))
    client.force_login(customer_user)

    response = client.post(reverse("portal:contact"), form_data(name="Neu GmbH"))

    assert "konnte gerade nicht gespeichert werden" in response.text
    assert 'value="Neu GmbH"' in response.text
    customer.refresh_from_db()
    assert customer.name == "ACME GmbH"


def test_only_the_own_contact_is_read(client, customer_user, customer, lexware):
    other = Customer.objects.create(name="Fremd AG", lexware_id=uuid.uuid4())
    client.force_login(customer_user)

    # There is no way to name another customer: the page always uses the login's customer.
    client.post(reverse("portal:contact"), {**form_data(), "customer": other.pk, "lexware_id": str(other.lexware_id)})

    assert all(str(customer.lexware_id) in str(r.url) for r in lexware)


def test_customer_without_lexware_contact_sees_a_note(client, customer_user, customer, monkeypatch):
    customer.lexware_id = None
    customer.save()
    monkeypatch.setattr("portal.views.client_from_settings", lambda: pytest.fail("Lexware called"))
    client.force_login(customer_user)

    response = client.get(reverse("portal:contact"))

    assert "keine Kontaktdaten hinterlegt" in response.text


def test_admin_can_allow_contact_changes(client, user, customer_user):
    client.force_login(user)
    form = client.get(reverse("users:edit", args=[customer_user.pk])).text
    assert 'name="portal_contact"' in form
