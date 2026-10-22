"""Two-factor login with an authenticator app (TOTP) and one-time recovery codes, via django-otp.

All functions here query the database synchronously; call them with ``sync_to_async``.
"""

from base64 import b32encode

import segno
from django.db import transaction
from django_otp import match_token
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from accounts.models import User

RECOVERY_CODE_COUNT = 10


def has_mfa(user: User) -> bool:
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def pending_device(user: User) -> TOTPDevice:
    """The authenticator being set up: created on first visit, kept until it is confirmed."""
    device = TOTPDevice.objects.filter(user=user, confirmed=False).first()
    return device or TOTPDevice.objects.create(user=user, name="Authenticator-App", confirmed=False)


def qr_code_svg(device: TOTPDevice) -> str:
    return segno.make(device.config_url, error="m").svg_inline(border=2, omitsize=True, dark="#000", light="#fff")


def secret_for_manual_entry(device: TOTPDevice) -> str:
    """The secret in base32, grouped in fours like authenticator apps show it."""
    secret = b32encode(device.bin_key).decode().rstrip("=")
    return " ".join(secret[i : i + 4] for i in range(0, len(secret), 4))


@transaction.atomic
def new_recovery_codes(user: User) -> list[str]:
    """Replace the user's recovery codes. Each code works once."""
    StaticDevice.objects.filter(user=user).delete()
    device = StaticDevice.objects.create(user=user, name="Wiederherstellungscodes")
    codes = [StaticToken.random_token() for _ in range(RECOVERY_CODE_COUNT)]
    StaticToken.objects.bulk_create(StaticToken(device=device, token=code) for code in codes)
    return codes


def confirm(device: TOTPDevice, token: str) -> list[str] | None:
    """Turn on two-factor login if ``token`` is valid. Returns the new recovery codes."""
    if not device.verify_token(token.replace(" ", "")):
        return None
    with transaction.atomic():
        TOTPDevice.objects.filter(user=device.user).exclude(pk=device.pk).delete()
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        return new_recovery_codes(device.user)


def verify(user: User, token: str) -> bool:
    """Check a code from the authenticator app or a recovery code."""
    return match_token(user, token.replace(" ", "").strip()) is not None


@transaction.atomic
def disable(user: User) -> None:
    TOTPDevice.objects.filter(user=user).delete()
    StaticDevice.objects.filter(user=user).delete()
