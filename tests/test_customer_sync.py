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
    marker = re.search(r"seit=([^\"]*)\"", client.get(url).text).group(1)

    assert client.get(url, {"seit": unquote(marker)}).status_code == 204

    app_settings = AppSettings.load()
    app_settings.lexware_synced_at = timezone.now()
    app_settings.save()
    response = client.get(url, {"seit": unquote(marker)})
    assert response.status_code == 200 and 'id="customer-list"' in response.text


@pytest.mark.django_db
def test_customer_list_hints_missing_api_key(client, user, settings):
    settings.LEXWARE_API_KEY = ""
    client.force_login(user)

    response = client.get(reverse("customers:list"))

    assert "fehlt der API-Schlüssel" in response.text
    assert "Aus Lexware importieren" not in response.text
