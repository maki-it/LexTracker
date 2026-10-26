import re
import uuid
from decimal import Decimal
from urllib.parse import unquote

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AppSettings
from customers.models import Customer
from customers.sync import sync_customers
from tests.lexware_fakes import contact, fake_client, page, serve_pages

pytestmark = pytest.mark.django_db(transaction=True)


async def run_sync(*contacts):
    async with fake_client(serve_pages(page(list(contacts)))) as client:
        return await sync_customers(client)


async def test_creates_new_customers():
    result = await run_sync(contact("ACME GmbH", number=10001), contact("Beta AG", number=10002))

    assert (result.created, result.updated, result.unchanged) == (2, 0, 0)
    names = [c.name async for c in Customer.objects.order_by("name")]
    assert names == ["ACME GmbH", "Beta AG"]


async def test_updates_changed_customers_and_keeps_local_fields():
    lexware_id = uuid.uuid4()
    await Customer.objects.acreate(
        name="Alt", lexware_id=lexware_id, lexware_version=1, default_hourly_rate=Decimal("95.00"), notes="wichtig"
    )

    result = await run_sync(contact("Neu GmbH", id=lexware_id, version=2, archived=True))

    customer = await Customer.objects.aget(lexware_id=lexware_id)
    assert (result.created, result.updated) == (0, 1)
    assert customer.name == "Neu GmbH"
    assert customer.is_archived
    assert customer.default_hourly_rate == Decimal("95.00")
    assert customer.notes == "wichtig"


async def test_skips_unchanged_customers():
    lexware_id = uuid.uuid4()
    await Customer.objects.acreate(name="Lokal geändert", lexware_id=lexware_id, lexware_version=3)

    result = await run_sync(contact("ACME GmbH", id=lexware_id, version=3))

    customer = await Customer.objects.aget(lexware_id=lexware_id)
    assert result.unchanged == 1
    assert customer.name == "Lokal geändert"
    assert customer.lexware_synced_at is not None


@pytest.mark.django_db
def test_import_view_shows_result(client, user, monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    monkeypatch.setattr(
        "customers.sync.client_from_settings", lambda: fake_client(serve_pages(page([contact("ACME GmbH")])))
    )
    client.force_login(user)

    response = client.post(reverse("customers:import"))

    assert response.status_code == 200
    assert "1 neu" in response.text
    assert "ACME GmbH" in response.text
    # The filter counts are part of the swapped list, so they change with the import.
    assert 'id="customer-list"' in response.text
    assert re.search(r"Aktiv<span[^>]*>1</span>", response.text)


@pytest.mark.django_db
def test_customer_list_reloads_only_after_an_import(client, user):
    client.force_login(user)
    url = reverse("customers:list")
    marker = re.search(r"since=([^\"]*)\"", client.get(url).text).group(1)

    assert client.get(url, {"since": unquote(marker)}).status_code == 204

    app_settings = AppSettings.load()
    app_settings.lexware_synced_at = timezone.now()
    app_settings.save()
    response = client.get(url, {"since": unquote(marker)})
    assert response.status_code == 200 and 'id="customer-list"' in response.text


@pytest.mark.django_db
def test_customer_list_hints_missing_api_key(client, user, settings):
    settings.LEXWARE_API_KEY = ""
    client.force_login(user)

    response = client.get(reverse("customers:list"))

    assert "fehlt der API-Schlüssel" in response.text
    assert "Aus Lexware importieren" not in response.text


# Notes


async def test_new_customer_takes_the_note_from_lexware():
    await run_sync(contact("ACME GmbH", note="Zahlt immer pünktlich"))

    customer = await Customer.objects.aget(name="ACME GmbH")
    assert customer.notes == "Zahlt immer pünktlich"
    assert customer.lexware_note == "Zahlt immer pünktlich"


async def test_note_changed_in_lexware_replaces_the_synced_note():
    lexware_id = uuid.uuid4()
    await Customer.objects.acreate(
        name="ACME GmbH", lexware_id=lexware_id, lexware_version=1, notes="alt", lexware_note="alt"
    )

    await run_sync(contact("ACME GmbH", id=lexware_id, version=2, note="neu"))

    customer = await Customer.objects.aget(lexware_id=lexware_id)
    assert (customer.notes, customer.lexware_note) == ("neu", "neu")


async def test_unsent_note_is_not_overwritten():
    lexware_id = uuid.uuid4()
    await Customer.objects.acreate(
        name="ACME GmbH", lexware_id=lexware_id, lexware_version=1, notes="nur hier", lexware_note="alt"
    )

    await run_sync(contact("ACME GmbH", id=lexware_id, version=2, note="anders"))

    customer = await Customer.objects.aget(lexware_id=lexware_id)
    assert customer.notes == "nur hier"
    assert customer.lexware_note == "anders"


async def test_customers_from_before_the_note_sync_keep_their_note_and_get_lexware_s():
    keeps = await Customer.objects.acreate(name="Hat Notiz", lexware_id=uuid.uuid4(), lexware_version=1, notes="lokal")
    takes = await Customer.objects.acreate(name="Ohne Notiz", lexware_id=uuid.uuid4(), lexware_version=1)
    both = await Customer.objects.acreate(name="Beides", lexware_id=uuid.uuid4(), lexware_version=1, notes="lokal")

    result = await run_sync(
        contact("Hat Notiz", id=keeps.lexware_id, version=1),
        contact("Ohne Notiz", id=takes.lexware_id, version=1, note="aus Lexware"),
        contact("Beides", id=both.lexware_id, version=1, note="aus Lexware"),
    )

    assert (result.updated, result.unchanged) == (0, 3)
    keeps, takes, both = [await Customer.objects.aget(pk=c.pk) for c in (keeps, takes, both)]
    assert (keeps.notes, keeps.lexware_note) == ("lokal", "")
    assert (takes.notes, takes.lexware_note) == ("aus Lexware", "aus Lexware")
    # Neither note is lost; the local one goes to Lexware with the next save.
    assert both.notes == "lokal\n\naus Lexware"
    assert both.lexware_note == "aus Lexware"
