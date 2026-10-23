"""Encryption for secrets stored in the database, such as the Lexware API key or the SMTP password.

The key is derived from ``APP_SECRET_KEY``, so a copy of the database (e.g. a backup) does not reveal
them. Each kind of secret uses its own derived key.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings


def _fernet(purpose: str) -> MultiFernet:
    # The first secret encrypts; SECRET_KEY_FALLBACKS still decrypt after the secret key was rotated.
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    keys = [
        base64.urlsafe_b64encode(hashlib.sha256(f"lextracker.{purpose}:{secret}".encode()).digest())
        for secret in secrets
    ]
    return MultiFernet([Fernet(key) for key in keys])


def encrypt(value: str, purpose: str) -> str:
    return _fernet(purpose).encrypt(value.encode()).decode()


def decrypt(token: str, purpose: str) -> str | None:
    """The value, or None if it was encrypted with a different secret key."""
    try:
        return _fernet(purpose).decrypt(token.encode()).decode()
    except InvalidToken:
        return None
