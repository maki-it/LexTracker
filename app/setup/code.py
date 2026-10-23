"""The setup code that guards the creation of the first account.

Whoever opens a fresh instance first could otherwise claim it. The code is derived from
APP_SECRET_KEY, so every worker and ``manage.py setup_link`` know it without storing anything,
and it is worthless once the first account exists. The app writes it to its log, which only
someone with access to the server can read.
"""

import logging
import secrets

from django.http import HttpRequest
from django.urls import reverse
from django.utils.crypto import salted_hmac

logger = logging.getLogger(__name__)

SESSION_KEY = "setup_code_ok"


def setup_code() -> str:
    return salted_hmac("lextracker.setup", "first-administrator", algorithm="sha256").hexdigest()[:24]


def setup_path() -> str:
    return f"{reverse('setup:account')}?code={setup_code()}"


def matches(code: str) -> bool:
    return secrets.compare_digest(code.strip().lower(), setup_code())


def log_setup_link(request: HttpRequest) -> None:
    logger.warning(
        "LexTracker is not set up yet. Open %s to create the first account.", request.build_absolute_uri(setup_path())
    )
