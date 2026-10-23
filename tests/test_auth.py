import pytest
from django.urls import reverse

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
