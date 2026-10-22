import pytest
from django.urls import reverse
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts import mfa

pytestmark = pytest.mark.django_db


def current_code(device: TOTPDevice) -> str:
    return f"{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}"


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def mfa_user(user):
    device = mfa.pending_device(user)
    device.confirmed = True
    device.save()
    codes = mfa.new_recovery_codes(user)
    return user, device, codes


def test_preferences_change_theme_and_date_format(logged_in, user):
    response = logged_in.post(
        reverse("account:settings"),
        {
            "first_name": "Kim",
            "last_name": "",
            "email": "",
            "theme": "dark",
            "date_format": "Y-m-d",
            "duration_format": "decimal",
        },
    )
    assert response.status_code == 302

    page = logged_in.get(reverse("account:settings")).text
    assert 'data-theme="dark"' in page
    user.refresh_from_db()
    assert user.date_format == "Y-m-d"


def test_password_change_keeps_session(logged_in, user):
    response = logged_in.post(
        reverse("account:password"),
        {
            "old_password": "geheim-123",
            "new_password1": "ein-neues-Passwort-42",
            "new_password2": "ein-neues-Passwort-42",
        },
    )
    assert response.status_code == 302
    assert logged_in.get(reverse("core:dashboard")).status_code == 200
    user.refresh_from_db()
    assert user.check_password("ein-neues-Passwort-42")


def test_mfa_setup_needs_valid_code(logged_in, user):
    page = logged_in.get(reverse("account:mfa_setup")).text
    assert "<svg" in page
    device = TOTPDevice.objects.get(user=user)

    wrong = "000000" if current_code(device) != "000000" else "111111"
    response = logged_in.post(reverse("account:mfa_setup"), {"code": wrong})
    assert "Der Code stimmt nicht" in response.text
    assert not mfa.has_mfa(user)

    response = logged_in.post(reverse("account:mfa_setup"), {"code": current_code(device)})
    assert "Wiederherstellungscodes" in response.text
    assert mfa.has_mfa(user)
    assert StaticToken.objects.filter(device__user=user).count() == mfa.RECOVERY_CODE_COUNT


def test_login_with_mfa_asks_for_code(client, mfa_user):
    _, device, _ = mfa_user
    response = client.post(reverse("accounts:login"), {"username": "kim", "password": "geheim-123", "next": "/"})
    assert response.url.startswith(reverse("accounts:login_code"))
    # The password alone does not sign in.
    assert client.get(reverse("core:dashboard")).status_code == 302

    response = client.post(reverse("accounts:login_code"), {"code": "123", "next": "/"})
    assert "Der Code ist ungültig" in response.text

    response = client.post(reverse("accounts:login_code"), {"code": current_code(device), "next": "/"})
    assert response.status_code == 302
    assert client.get(reverse("core:dashboard")).status_code == 200


def test_recovery_code_works_once(client, mfa_user):
    _, _, codes = mfa_user
    client.post(reverse("accounts:login"), {"username": "kim", "password": "geheim-123"})
    client.post(reverse("accounts:login_code"), {"code": codes[0]})
    assert client.get(reverse("core:dashboard")).status_code == 200
    client.post(reverse("accounts:logout"))

    client.post(reverse("accounts:login"), {"username": "kim", "password": "geheim-123"})
    response = client.post(reverse("accounts:login_code"), {"code": codes[0]})
    assert "Der Code ist ungültig" in response.text


def test_code_step_without_password_redirects(client):
    response = client.get(reverse("accounts:login_code"))
    assert response.status_code == 302
    assert response.url == reverse("accounts:login")


def test_disable_mfa_needs_password(logged_in, mfa_user):
    user, _, _ = mfa_user
    response = logged_in.post(reverse("account:mfa_manage"), {"password": "falsch", "action": "disable"})
    assert "Das Passwort ist falsch." in response.text
    assert mfa.has_mfa(user)

    logged_in.post(reverse("account:mfa_manage"), {"password": "geheim-123", "action": "disable"})
    assert not mfa.has_mfa(user)


def test_admin_login_goes_through_app_login(client):
    response = client.get("/admin/login/?next=/admin/")
    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next=/admin/"
