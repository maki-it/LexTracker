import pytest
from django.core.management import call_command

from accounts.models import User

pytestmark = pytest.mark.django_db


def test_ensure_superuser_creates_admin_once(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_USERNAME", "kim")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "geheim-123")

    call_command("ensure_superuser")
    call_command("ensure_superuser")

    user = User.objects.get(username="kim")
    assert user.is_superuser
    assert user.check_password("geheim-123")


def test_ensure_superuser_skips_without_variables(monkeypatch):
    monkeypatch.delenv("DJANGO_SUPERUSER_USERNAME", raising=False)
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)

    call_command("ensure_superuser")

    assert not User.objects.exists()
