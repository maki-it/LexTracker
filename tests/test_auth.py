import pytest
from django.urls import reverse
from pydantic import ValidationError

from config.env import Env

pytestmark = pytest.mark.django_db


def test_pages_require_login(client, user):
    response = client.get(reverse("core:dashboard"))
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next=/"


def test_health_is_public(client):
    response = client.get(reverse("core:health"))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_favicon_is_public(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 301
    assert response.url.endswith("img/favicon.ico")


def test_robots_txt_is_public_and_blocks_crawlers(client, user):
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/plain")
    assert response.text == "User-agent: *\nDisallow: /\n"


def test_robots_txt_does_not_lock_out_login_or_mcp(client, user):
    # Crawlers are only asked to stay away; the login page and the MCP endpoint still answer.
    assert client.get(reverse("accounts:login")).status_code == 200
    assert client.get("/mcp/").status_code != 302


def test_login_with_valid_credentials(client, user):
    response = client.post(reverse("accounts:login"), {"username": "kim", "password": "geheim-123", "next": "/"})
    assert response.status_code == 302
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_login_with_wrong_password(client, user):
    response = client.post(reverse("accounts:login"), {"username": "kim", "password": "falsch"})
    assert response.status_code == 200
    assert "Benutzername oder Passwort ist falsch." in response.text


def test_login_ignores_external_next_url(client, user):
    response = client.post(
        reverse("accounts:login"), {"username": "kim", "password": "geheim-123", "next": "https://evil.example/"}
    )
    assert response.url == reverse("core:dashboard")


def test_logout(client, user):
    client.force_login(user)
    response = client.post(reverse("accounts:logout"))
    assert response.url == reverse("accounts:login")
    assert client.get(reverse("core:dashboard")).status_code == 302


def test_hsts_is_off_by_default_and_read_from_the_environment(monkeypatch):
    monkeypatch.delenv("APP_HSTS_SECONDS", raising=False)
    assert Env(_env_file=None).hsts_seconds == 0
    monkeypatch.setenv("APP_HSTS_SECONDS", "31536000")
    assert Env(_env_file=None).hsts_seconds == 31536000
    monkeypatch.setenv("APP_HSTS_SECONDS", "-1")
    with pytest.raises(ValidationError):
        Env(_env_file=None)
