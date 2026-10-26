import re
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from django.urls import reverse

from accounts.models import User
from config.env import Env
from core import version

ROOT = Path(__file__).parent.parent
SHA = "0123456789abcdef0123456789abcdef01234567"


@pytest.fixture
def running(monkeypatch):
    """Run as if the app was started with the given ``APP_VERSION``, ``APP_COMMIT`` and ``APP_BUILD_DATE``."""

    def run(**env) -> version.Info:
        monkeypatch.setattr(version, "get_env", lambda: Env(**env))
        version.load.cache_clear()
        return version.load()

    yield run
    version.load.cache_clear()


def test_a_release_image_reports_what_it_was_built_from(running):
    info = running(version="0.7.0", commit=SHA, build_date="2026-10-26T17:30:00Z")
    assert info.released
    assert info.version == "0.7.0"
    assert info.short_commit == "0123456"
    assert info.built_at == datetime(2026, 10, 26, 17, 30, tzinfo=UTC)
    assert info.release_url == "https://github.com/maki-it/LexTracker/releases/tag/lextracker-v0.7.0"
    assert info.commit_url == f"https://github.com/maki-it/LexTracker/commit/{SHA}"


def test_running_from_source_uses_the_version_of_pyproject(running):
    info = running()
    assert not info.released
    assert info.version == tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert info.commit == "" and info.commit_url == ""
    assert info.built_at is None
    assert info.release_url == ""


def test_an_image_built_by_hand_is_not_a_release(running):
    # The default of the Docker build argument, and the image has no pyproject.toml to read.
    info = running(version=version.UNRELEASED)
    assert not info.released
    assert info.release_url == ""


def test_an_unreadable_build_date_is_left_out(running):
    assert running(version="0.7.0", build_date="gestern").built_at is None


def test_the_release_tag_matches_what_release_please_writes():
    config = (ROOT / "release-please-config.json").read_text()
    assert '"package-name": "lextracker"' in config
    assert version.TAG_PREFIX == "lextracker-v"


@pytest.mark.django_db
def test_info_tab_shows_version_and_repository(client, user, running):
    running(version="0.7.0", commit=SHA, build_date="2026-10-26T17:30:00Z")
    client.force_login(user)
    page = client.get(reverse("core:settings"), {"tab": "info"}).text
    assert "0.7.0" in page
    assert "0123456" in page
    assert "https://github.com/maki-it/LexTracker/releases/tag/lextracker-v0.7.0" in page
    assert "https://github.com/maki-it/LexTracker/issues" in page
    assert 'href="https://github.com/maki-it/LexTracker"' in page
    assert "Entwicklungsstand" not in page
    # No form to save on this tab.
    assert re.search(r'<div hidden>\s*<button type="submit"', page)


@pytest.mark.django_db
def test_info_tab_marks_a_build_from_source(client, user, running):
    running()
    client.force_login(user)
    page = client.get(reverse("core:settings"), {"tab": "info"}).text
    assert "Entwicklungsstand" in page
    assert "releases/tag" not in page


@pytest.mark.django_db
def test_sidebar_shows_the_version_to_admins_only(client, user, running):
    running(version="0.7.0")
    employee = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(user)
    page = client.get(reverse("core:dashboard")).text
    assert ">v0.7.0</a>" in page
    assert f'href="{reverse("core:settings")}?tab=info"' in page
    client.force_login(employee)
    assert "v0.7.0" not in client.get(reverse("core:dashboard")).text


@pytest.mark.django_db
def test_info_tab_in_english(client, user, running, english):
    running(version="0.7.0", commit=SHA, build_date="2026-10-26T17:30:00Z")
    user.language = "en"
    user.save()
    client.force_login(user)
    page = client.get(reverse("core:settings"), {"tab": "info"}).text
    assert "Source code" in page and "Report a problem" in page and "Built on" in page
