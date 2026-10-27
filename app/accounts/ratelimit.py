"""Login rate limit: too many wrong passwords or codes from one IP address lock the login from there for a while.

Failures are kept in the database, so the limit holds across all uvicorn workers. Locked requests are
turned away before the password is checked, which also spares the CPU the expensive password hash.
"""

import math
from datetime import timedelta

from django.http import HttpRequest
from django.utils import timezone

from accounts.models import LoginFailure
from core.models import AppSettings


def client_ip(request: HttpRequest) -> str:
    # uvicorn sets this from X-Forwarded-For when the request comes from a trusted proxy (FORWARDED_ALLOW_IPS).
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


async def locked_minutes(request: HttpRequest) -> int:
    """Minutes until the login is open again for this client; 0 if it is not locked."""
    settings = await AppSettings.aload()
    if not settings.login_max_attempts:
        return 0
    window = timedelta(minutes=settings.login_lockout_minutes)
    failures = LoginFailure.objects.filter(ip_address=client_ip(request), at__gte=timezone.now() - window)
    if await failures.acount() < settings.login_max_attempts:
        return 0
    # Open again once the oldest failure that still counts falls out of the window.
    newest_first = failures.order_by("-at").values_list("at", flat=True)
    oldest = await newest_first[settings.login_max_attempts - 1 :].afirst()
    return max(1, math.ceil((oldest + window - timezone.now()).total_seconds() / 60))


async def record_failure(request: HttpRequest, username: str = "") -> None:
    settings = await AppSettings.aload()
    if not settings.login_max_attempts:
        return
    await LoginFailure.objects.acreate(ip_address=client_ip(request), username=username[:150])
    # Old failures no longer count; keep the table small.
    keep = timedelta(minutes=settings.login_lockout_minutes)
    await LoginFailure.objects.filter(at__lt=timezone.now() - keep).adelete()


async def clear_failures(request: HttpRequest, username: str) -> None:
    """Forget the failures of one account after it signed in.

    Only that account's, not all from this address: anyone with a login of their own (an employee, a customer)
    could otherwise sign in between guesses at another account's password and start counting from zero.
    """
    await LoginFailure.objects.filter(ip_address=client_ip(request), username__iexact=username).adelete()
