"""Links sent by e-mail: one to set a new password, one to sign in without a password, and the invitation.

The first two are requested with a username or an e-mail address. The answer is the same whether an account
exists or not, so nobody can find out which accounts exist. Requests count against the login rate
limit (``accounts.ratelimit``), and one account gets only a few links in a row.
"""

import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.tokens import PasswordResetTokenGenerator, default_token_generator
from django.db.models import Q
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import base36_to_int, urlsafe_base64_decode, urlsafe_base64_encode

from accounts.models import LoginLink, User
from core.ids import parse_uuid
from core.models import AppSettings
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail

RESET_MINUTES = 60
LOGIN_LINK_MINUTES = 15
# Links per account within the lockout window of the login rate limit.
MAX_LINKS_PER_ACCOUNT = 3


class PasswordResetLinkGenerator(PasswordResetTokenGenerator):
    """Like Django's password reset token, but valid for an hour instead of the week an invitation has.

    The token stops working as soon as the password changes or the user signs in.
    """

    key_salt = "lextracker.accounts.links.PasswordResetLinkGenerator"
    max_age = RESET_MINUTES * 60

    def check_token(self, user, token) -> bool:
        if not super().check_token(user, token):
            return False
        try:
            timestamp = base36_to_int(token.split("-")[0])
        except ValueError:
            return False
        return self._num_seconds(self._now()) - timestamp <= self.max_age


reset_tokens = PasswordResetLinkGenerator()


async def _accounts(identifier: str) -> list[User]:
    """Active accounts with an e-mail address whose username or e-mail address is ``identifier``."""
    identifier = identifier.strip()
    if not identifier:
        return []
    users = User.objects.filter(Q(username__iexact=identifier) | Q(email__iexact=identifier), is_active=True)
    return [user async for user in users.exclude(email="")]


async def _too_many(user: User, kind: str) -> bool:
    window = timedelta(minutes=(await AppSettings.aload()).login_lockout_minutes)
    recent = OutgoingMail.objects.filter(user=user, kind=kind, created_at__gte=timezone.now() - window)
    return await recent.acount() >= MAX_LINKS_PER_ACCOUNT


async def _absolute(request: HttpRequest, path: str) -> str:
    base_url = (await MailSettings.aload()).base_url.rstrip("/")
    return f"{base_url}{path}" if base_url else request.build_absolute_uri(path)


async def send_password_reset(request: HttpRequest, identifier: str) -> None:
    for user in await _accounts(identifier):
        if await _too_many(user, OutgoingMail.Kind.PASSWORD_RESET):
            continue
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        url = await _absolute(request, reverse("accounts:password_reset", args=[uid, reset_tokens.make_token(user)]))
        await outbox.aqueue(
            OutgoingMail.Kind.PASSWORD_RESET,
            user.email,
            "Neues Passwort für LexTracker",
            "password_reset",
            {"user": user, "url": url, "minutes": RESET_MINUTES},
            user=user,
            expires_at=timezone.now() + timedelta(minutes=RESET_MINUTES),
        )


async def user_from_uid(uidb64: str) -> User | None:
    """The active user a link's ``uidb64`` names, or None."""
    try:
        user_id = parse_uuid(urlsafe_base64_decode(uidb64).decode())
    except ValueError:  # Not base64 or not text; UnicodeDecodeError is a ValueError, too.
        return None
    return await User.objects.filter(pk=user_id, is_active=True).afirst() if user_id else None


async def reset_user(uidb64: str, token: str) -> User | None:
    """The user a password reset link is for, or None if the link is invalid or expired."""
    user = await user_from_uid(uidb64)
    return user if user and reset_tokens.check_token(user, token) else None


async def send_login_link(request: HttpRequest, identifier: str) -> None:
    for user in await _accounts(identifier):
        if await _too_many(user, OutgoingMail.Kind.LOGIN_LINK):
            continue
        key = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timedelta(minutes=LOGIN_LINK_MINUTES)
        await LoginLink.objects.acreate(user=user, key_hash=LoginLink.hash(key), expires_at=expires_at)
        url = await _absolute(request, reverse("accounts:login_link", args=[key]))
        await outbox.aqueue(
            OutgoingMail.Kind.LOGIN_LINK,
            user.email,
            "Dein Anmeldelink für LexTracker",
            "login_link",
            {"user": user, "url": url, "minutes": LOGIN_LINK_MINUTES},
            user=user,
            expires_at=expires_at,
        )
    # Expired links are useless; keep the table small.
    await LoginLink.objects.filter(expires_at__lt=timezone.now() - timedelta(days=1)).adelete()


async def login_link_valid(key: str) -> bool:
    return await LoginLink.objects.filter(
        key_hash=LoginLink.hash(key), used_at__isnull=True, expires_at__gt=timezone.now(), user__is_active=True
    ).aexists()


async def redeem_login_link(key: str) -> User | None:
    """The user the link signs in, or None. Marks the link as used, so it works only once."""
    now = timezone.now()
    links = LoginLink.objects.filter(
        key_hash=LoginLink.hash(key), used_at__isnull=True, expires_at__gt=now, user__is_active=True
    )
    link = await links.select_related("user").afirst()
    # The update only succeeds once, even if two requests use the link at the same time.
    if link is None or not await LoginLink.objects.filter(pk=link.pk, used_at__isnull=True).aupdate(used_at=now):
        return None
    return link.user


def invite_path(user: User) -> str:
    """The path to set a first password. It stops working once a password is set, or after a week."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return reverse("accounts:invite", args=[uid, default_token_generator.make_token(user)])


async def invite_url(request: HttpRequest, user: User) -> str:
    return await _absolute(request, invite_path(user))


async def can_send_invitation(user: User) -> bool:
    return bool(user.is_active and user.email) and await outbox.ais_configured()


async def send_invitation(request: HttpRequest, user: User) -> None:
    """Queue the invitation e-mail for ``user``, sent by the administrator signed in."""
    inviter = request.user.get_full_name() or request.user.get_username()
    await outbox.aqueue(
        OutgoingMail.Kind.INVITATION,
        user.email,
        "Dein Zugang zu LexTracker",
        "invitation",
        {
            "invited": user,
            "inviter": "" if inviter == user.get_username() else inviter,
            "url": await invite_url(request, user),
            "days": settings.PASSWORD_RESET_TIMEOUT // 86400,
        },
        user=user,
        expires_at=timezone.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
    )


async def available() -> dict:
    """Which e-mail links the login page offers."""
    if not await outbox.ais_configured():
        return {"password_reset": False, "login_link": False}
    return {"password_reset": True, "login_link": (await AppSettings.aload()).login_link_enabled}
