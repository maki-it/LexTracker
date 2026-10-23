"""Where the app gets its Lexware Office API key from.

A key entered in the app is stored encrypted (see ``core.crypto``), so a copy of the database
(e.g. a backup) does not reveal it. ``APP_LEXWARE_API_KEY`` still works as a fallback for
setups that have not moved the key into the app yet.

Never log the key or put it into an exception message.
"""

from dataclasses import dataclass
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from core import crypto
from lexware.client import LexwareClient
from lexware.models import LexwareConnection
from lexware.schemas import Profile

SUFFIX_LENGTH = 4
PURPOSE = "lexware-api-key"


def encrypt(api_key: str) -> str:
    return crypto.encrypt(api_key, PURPOSE)


def decrypt(token: str) -> str | None:
    """The key, or None if it was encrypted with a different secret key."""
    return crypto.decrypt(token, PURPOSE)


def mask(suffix: str) -> str:
    return f"••••••••{suffix}"


@dataclass(frozen=True)
class KeyStatus:
    # "app" (entered in the app), "env" (APP_LEXWARE_API_KEY) or "" (none).
    source: str
    masked: str = ""
    company_name: str = ""
    verified_at: datetime | None = None
    updated_at: datetime | None = None
    # Stored, but APP_SECRET_KEY changed since, so it cannot be decrypted.
    unreadable: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.source)


async def aget_api_key() -> str:
    """The key entered in the app, otherwise APP_LEXWARE_API_KEY, otherwise an empty string."""
    connection = await LexwareConnection.aload()
    if connection.encrypted_api_key and (api_key := decrypt(connection.encrypted_api_key)):
        return api_key
    return settings.LEXWARE_API_KEY


async def ais_configured() -> bool:
    return bool(await aget_api_key())


async def astatus() -> KeyStatus:
    connection = await LexwareConnection.aload()
    details = {
        "company_name": connection.company_name,
        "verified_at": connection.verified_at,
        "updated_at": connection.updated_at,
    }
    if connection.encrypted_api_key:
        if decrypt(connection.encrypted_api_key) is not None:
            return KeyStatus("app", mask(connection.key_suffix), **details)
        if not settings.LEXWARE_API_KEY:
            return KeyStatus("", unreadable=True)
    if settings.LEXWARE_API_KEY:
        return KeyStatus("env", mask(settings.LEXWARE_API_KEY[-SUFFIX_LENGTH:]))
    return KeyStatus("")


async def astore(api_key: str, *, company_name: str = "") -> None:
    """Save a key that was just checked against Lexware, replacing any previous one."""
    now = timezone.now()
    await LexwareConnection.aload()
    await LexwareConnection.objects.filter(pk=1).aupdate(
        encrypted_api_key=encrypt(api_key),
        key_suffix=api_key[-SUFFIX_LENGTH:],
        company_name=company_name[:200],
        verified_at=now,
        updated_at=now,
    )


async def amark_verified(company_name: str) -> None:
    await LexwareConnection.objects.filter(pk=1).aupdate(company_name=company_name[:200], verified_at=timezone.now())


async def aremove() -> None:
    await LexwareConnection.objects.filter(pk=1).aupdate(
        encrypted_api_key="", key_suffix="", company_name="", verified_at=None, updated_at=timezone.now()
    )


async def acheck(api_key: str) -> Profile:
    """Ask Lexware for the profile behind the key. Raises LexwareError if the key does not work."""
    async with LexwareClient(api_key, base_url=settings.LEXWARE_BASE_URL) as client:
        return await client.get_profile()
