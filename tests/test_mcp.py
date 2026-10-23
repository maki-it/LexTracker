import json
from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import ApiToken
from core.models import AppSettings
from projects.models import Task
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

URL = "/mcp/"


@pytest.fixture
def key(user):
    _, key = ApiToken.issue(user, "Claude Code")
    return key


@pytest.fixture
def rpc(client, key):
    """Send one JSON-RPC request and return its result."""
    counter = iter(range(1, 1000))

    def call(method, params=None, **headers):
        message = {"jsonrpc": "2.0", "id": next(counter), "method": method, "params": params or {}}
        response = client.post(
            URL, json.dumps(message), content_type="application/json", headers={"Authorization": f"Bearer {key}"}
        )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["id"] == message["id"]
        return body.get("result", body.get("error"))

    return call


@pytest.fixture
def tool(rpc):
    """Call a tool and return its decoded result, or the error text."""

    def call(tool_name, /, **arguments):
        result = rpc("tools/call", {"name": tool_name, "arguments": arguments})
        text = result["content"][0]["text"]
        return text if result["isError"] else json.loads(text)

    return call


def test_requires_a_valid_token(client, key):
    assert client.post(URL, "{}", content_type="application/json").status_code == 401
    response = client.post(URL, "{}", content_type="application/json", headers={"Authorization": "Bearer lxt_falsch"})
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")


def test_revoked_token_no_longer_works(client, key):
    ApiToken.objects.all().delete()
    headers = {"Authorization": f"Bearer {key}"}
    assert client.post(URL, "{}", content_type="application/json", headers=headers).status_code == 401


def test_initialize_and_list_tools(rpc, client, key):
    result = rpc("initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "t"}})
    assert result["protocolVersion"] == "2025-03-26"
    assert result["capabilities"] == {"tools": {}}
    assert ApiToken.objects.get().last_used_at

    # Unknown versions get the newest one.
    assert rpc("initialize", {"protocolVersion": "1999-01-01"})["protocolVersion"] == "2025-11-25"

    notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    response = client.post(
        URL, json.dumps(notification), content_type="application/json", headers={"Authorization": f"Bearer {key}"}
    )
    assert response.status_code == 202

    names = {t["name"] for t in rpc("tools/list")["tools"]}
    assert {"find_tasks", "start_timer", "stop_timer", "add_time_entry", "list_time_entries"} <= names
    assert rpc("nope")["code"] == -32601


def test_get_is_not_allowed(client, key):
    assert client.get(URL, headers={"Authorization": f"Bearer {key}"}).status_code == 405


def test_find_tasks_and_create_task(tool, task):
    assert [t["id"] for t in tool("find_tasks", query="acme entw")] == [str(task.pk)]
    assert tool("find_tasks", query="gibt es nicht") == []

    created = tool("create_task", project_id=str(task.project_id), name="MCP-Server")
    assert created["project"] == "Website" and created["customer"] == "ACME GmbH"
    assert Task.objects.filter(name="MCP-Server").exists()

    projects = tool("list_projects", query="ACME")
    assert {t["name"] for t in projects[0]["tasks"]} == {"Entwicklung", "MCP-Server"}


def test_timer(tool, task, user):
    assert tool("get_running_timer") == {"running": False}

    started = tool("start_timer", task_id=str(task.pk), description="Bug suchen")["started"]
    assert started["running"] and started["task"]["id"] == str(task.pk)
    assert tool("get_running_timer")["id"] == started["id"]

    # Make it long enough to be kept.
    TimeEntry.objects.filter(pk=started["id"]).update(started_at=timezone.now() - timedelta(minutes=20))
    stopped = tool("stop_timer", description="Bug gefunden und behoben")
    assert stopped["stopped"] and stopped["entry"]["minutes"] >= 20
    entry = TimeEntry.objects.get()
    assert entry.description == "Bug gefunden und behoben" and entry.user == user

    assert tool("stop_timer") == {"stopped": False, "reason": "Kein Timer lief."}


def test_starting_a_timer_stops_the_running_one(tool, task):
    first = tool("start_timer", task_id=str(task.pk))["started"]
    TimeEntry.objects.filter(pk=first["id"]).update(started_at=timezone.now() - timedelta(minutes=5))

    result = tool("start_timer", task_id=str(task.pk), description="Weiter")
    assert result["stopped"]["id"] == first["id"]
    assert TimeEntry.objects.filter(ended_at__isnull=True).count() == 1


def test_unknown_task_is_reported_to_the_agent(tool):
    assert "Keine offene Aufgabe" in tool("start_timer", task_id=999)
    assert "Keine offene Aufgabe" in tool("start_timer", task_id="kein-uuid")


def test_add_time_entry_rounds_start_and_end(tool, task):
    settings = AppSettings.load()
    settings.time_rounding = 15
    settings.save()

    entry = tool(
        "add_time_entry", task_id=str(task.pk), start="2026-10-01T09:07", duration_minutes=50, description="Doku"
    )
    assert entry["minutes"] == 60
    assert entry["start"].startswith("2026-10-01T09:00")

    assert "entweder end oder duration_minutes" in tool(
        "add_time_entry", task_id=str(task.pk), start="2026-10-01T09:00"
    )
    assert "nach dem Beginn" in tool(
        "add_time_entry", task_id=str(task.pk), start="2026-10-01T09:00", end="2026-10-01T08:00"
    )
    assert "ISO 8601" in tool("add_time_entry", task_id=str(task.pk), start="gestern", duration_minutes=10)
    assert "Unbekannte Argumente" in tool("add_time_entry", task_id=str(task.pk), start="x", foo=1)

    listed = tool("list_time_entries", date_from="2026-10-01", date_to="2026-10-01")
    assert listed["total_minutes"] == 60 and listed["entries"][0]["description"] == "Doku"


def test_other_users_entries_are_not_listed(tool, task):
    from accounts.models import User

    other = User.objects.create_user(username="anna", password="geheim-123")
    TimeEntry.objects.create(
        user=other, task=task, started_at=timezone.now() - timedelta(hours=1), ended_at=timezone.now()
    )
    assert tool("list_time_entries")["entries"] == []


# Account page


def test_create_and_revoke_token(client, user):
    client.force_login(user)

    response = client.post(reverse("account:token_create"), {"name": "Laptop"})
    token = ApiToken.objects.get()
    key = response.context["new_key"]
    assert key.startswith("lxt_") and key in response.text
    assert ApiToken.hash(key) == token.key_hash and token.name == "Laptop"
    assert "/mcp/" in response.text
    assert "Beispiel-Prompts" in response.text and "start_timer" in response.text

    # The key is shown only once.
    assert key not in client.get(reverse("account:settings")).text

    client.post(reverse("account:token_revoke", args=[token.pk]))
    assert not ApiToken.objects.exists()


def test_account_page_shows_client_setups_with_placeholder(client, user):
    client.force_login(user)

    response = client.get(reverse("account:settings"))
    names = [c.name for c in response.context["mcp_clients"]]
    assert names == ["Claude Code", "Claude Desktop und Web", "VS Code", "Cursor", "Codex"]
    assert "Agent verbinden" in response.text and 'data-copy="mcp-claude-code-1"' in response.text
    assert "claude mcp add --transport http --scope user lextracker http://testserver/mcp/" in response.text
    assert "Bearer DEIN_TOKEN" in response.text


def test_client_setups_contain_new_token_and_valid_json(client, user):
    client.force_login(user)

    response = client.post(reverse("account:token_create"), {"name": "Laptop"})
    key = response.context["new_key"]
    setups = {c.slug: c for c in response.context["mcp_clients"]}
    assert "DEIN_TOKEN" not in response.text
    assert f"Bearer {key}" in setups["claude-code"].snippets[0].text

    project_file = json.loads(setups["claude-code"].snippets[1].text)["mcpServers"]["lextracker"]
    assert project_file["url"] == "http://testserver/mcp/" and key not in setups["claude-code"].snippets[1].text
    assert project_file["headers"]["Authorization"] == "Bearer ${LEXTRACKER_TOKEN}"
    vscode = json.loads(setups["vscode"].snippets[0].text)["servers"]["lextracker"]
    assert vscode["type"] == "http" and vscode["headers"]["Authorization"] == "Bearer ${input:lextracker-token}"
    cursor = json.loads(setups["cursor"].snippets[0].text)["mcpServers"]["lextracker"]
    assert cursor["headers"]["Authorization"] == f"Bearer {key}"
    assert setups["claude"].snippets[1].text == f"Bearer {key}"
    assert f'export LEXTRACKER_TOKEN="{key}"' in setups["codex"].snippets[1].text
