import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from core.models import AppSettings

pytestmark = pytest.mark.django_db

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def manifest(client, **headers) -> dict:
    response = client.get(reverse("core:manifest"), **headers)
    assert response.status_code == 200
    assert response["Content-Type"] == "application/manifest+json"
    return json.loads(response.content)


def test_the_manifest_is_public_and_makes_an_installable_app(client, user):
    data = manifest(client)

    assert data["name"] == "LexTracker"
    assert (data["display"], data["start_url"], data["scope"]) == ("standalone", "/", "/")
    # Dark, so the splash screen does not flash white.
    assert data["background_color"] == "#0f0f12"
    assert data["lang"] == "de"


def test_the_manifest_has_icons_including_a_maskable_one(client, user):
    icons = manifest(client)["icons"]

    assert {(i["sizes"], i.get("purpose", "any")) for i in icons} == {
        ("192x192", "any"),
        ("512x512", "any"),
        ("512x512", "maskable"),
    }
    assert all(i["src"].endswith(".png") for i in icons)


def test_the_manifest_offers_shortcuts_for_the_timer_and_late_entries(client, user):
    shortcuts = manifest(client)["shortcuts"]

    assert [(s["name"], s["url"]) for s in shortcuts] == [
        ("Timer starten", reverse("tracking:timer_start")),
        ("Zeit nachtragen", reverse("tracking:create")),
    ]


def test_the_manifest_is_in_the_language_of_the_visitor(client, user, english):
    data = manifest(client, headers={"Accept-Language": "en"})

    assert data["lang"] == "en"
    assert [s["name"] for s in data["shortcuts"]] == ["Start timer", "Add time"]


def test_the_manifest_follows_the_branding(client, user):
    app_settings = AppSettings.load()
    app_settings.app_name = "Acme Zeit"
    app_settings.save()

    data = manifest(client)

    assert (data["name"], data["short_name"]) == ("Acme Zeit", "Acme Zeit")
    assert data["description"].startswith("Acme Zeit:")


def test_an_uploaded_logo_is_the_icon_of_the_manifest(client, user):
    client.force_login(user)
    user.email = "kim@example.de"
    user.save()
    from tests.test_branding import SETTINGS

    client.post(reverse("core:settings"), SETTINGS | {"logo": SimpleUploadedFile("logo.png", PNG)})

    icons = manifest(client.__class__())["icons"]

    assert len(icons) == 1
    assert icons[0]["src"].startswith(reverse("core:logo"))
    assert icons[0]["type"] == "image/png"


def test_pages_link_the_manifest_with_credentials(client, user):
    client.force_login(user)

    page = client.get(reverse("core:dashboard")).text

    assert f'<link rel="manifest" href="{reverse("core:manifest")}" crossorigin="use-credentials">' in page
