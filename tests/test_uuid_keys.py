import json
import uuid

import pytest
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from accounts.models import ApiToken, User
from core.ids import parse_uuid
from customers.models import Customer
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def test_rows_get_time_ordered_uuids(user):
    customers = [Customer.objects.create(name=f"Kunde {i}") for i in range(50)]

    assert all(isinstance(c.pk, uuid.UUID) and c.pk.version == 7 for c in customers)
    # Version 7 starts with the time, so the key sorts like the creation order, even within a millisecond.
    assert [c.pk for c in customers] == sorted(c.pk for c in customers)
    assert [c.name for c in Customer.objects.order_by("pk")] == [c.name for c in customers]
    assert user.pk.version == 7


def test_a_new_instance_is_not_saved_although_it_has_a_key():
    new = User(username="neu")
    assert new.pk is not None and new._state.adding


@pytest.mark.parametrize("path", ["/projects/1/", "/customers/1/", "/tasks/1/", "/users/1/", "/billing/customer/1/"])
def test_old_numeric_urls_are_not_found(client, user, path):
    client.force_login(user)
    assert client.get(path).status_code == 404


def test_a_valid_uuid_of_nothing_is_not_found(client, user):
    client.force_login(user)
    assert client.get(reverse("projects:detail", args=[uuid.uuid4()])).status_code == 404


def test_filters_ignore_ids_that_are_not_uuids(client, user, task):
    client.force_login(user)
    for url in ("tracking:list", "billing:invoices", "reports:overview", "customers:list"):
        for query in ({"customer": "5"}, {"project": "5"}, {"category": "5"}, {"customer": "x" * 40}):
            assert client.get(reverse(url), query).status_code == 200


def test_filter_by_customer_and_project(client, user, task):
    client.force_login(user)
    customer, project = task.project.customer, task.project
    TimeEntry.objects.create(user=user, task=task)

    assert customer.name in client.get(reverse("tracking:list"), {"customer": customer.pk}).text
    assert project.name in client.get(reverse("tracking:list"), {"project": project.pk}).text


@pytest.mark.parametrize(
    "uid", ["!!!", "MQ", urlsafe_base64_encode(force_bytes("kein-uuid")), urlsafe_base64_encode(b"\xff")]
)
def test_links_with_a_broken_user_id_are_invalid(client, user, uid):
    assert client.get(reverse("accounts:invite", args=[uid, "abc-def"])).status_code == 400
    assert client.get(reverse("accounts:password_reset", args=[uid, "abc-def"])).status_code == 400


def test_mcp_ids_are_uuids_as_text(client, user, task):
    _, key = ApiToken.issue(user, "Agent")

    def call(tool, **arguments):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        response = client.post(
            "/mcp/", json.dumps(message), content_type="application/json", headers={"Authorization": f"Bearer {key}"}
        )
        return response.json()["result"]["content"][0]["text"]

    found = json.loads(call("find_tasks", query="Entwicklung"))
    assert found[0]["id"] == str(task.pk) and found[0]["project_id"] == str(task.project_id)
    assert "ID aus find_tasks" in call("list_time_entries", task_id=5)


def test_parse_uuid():
    value = uuid.uuid7()
    assert parse_uuid(str(value)) == parse_uuid(value.hex) == parse_uuid(value) == value
    assert [parse_uuid(v) for v in ("", "5", None, "x" * 36, 5)] == [None] * 5
