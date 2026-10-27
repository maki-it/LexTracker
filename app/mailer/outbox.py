"""The outgoing mail queue.

Views and jobs only put e-mails into the database (``aqueue``), so a request never waits for the SMTP
server. The scheduler sends what is due every few seconds (``send_due``) and retries failures later.
"""

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend as SmtpBackend
from django.template.loader import render_to_string
from django.utils import timezone, translation
from django.utils.module_loading import import_string
from django.utils.translation import gettext as _

from core import branding
from mailer.models import SSL_PORT, MailSettings, OutgoingMail

logger = logging.getLogger(__name__)

# Seconds to wait for the SMTP server.
SMTP_TIMEOUT = 15
# How many e-mails one run sends over one connection.
BATCH = 20
# Wait before the next attempt after the first, second, ... failure. After the last one the mail fails for good.
RETRY_DELAYS = [timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=15), timedelta(hours=1)]


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str = ""


class MailNotConfigured(Exception):
    pass


def render(template: str, context: dict) -> tuple[str, str]:
    """Text and HTML version of ``mail/<template>.txt`` and ``.html``."""
    return render_to_string(f"mail/{template}.txt", context), render_to_string(f"mail/{template}.html", context)


async def aqueue(
    kind: str,
    to: str,
    subject: str,
    template: str,
    context: dict,
    *,
    user=None,
    dedupe_key: str = "",
    expires_at: datetime | None = None,
    language: str | None = None,
) -> OutgoingMail:
    """Queue an e-mail, written in the language of the user it is for (or ``language``).

    ``subject`` can be a lazy translation. Without a user, e-mails are written in the default language.
    """
    brand = await branding.aload()
    with translation.override(language or (user.ui_language if user else settings.LANGUAGE_CODE)):
        subject = str(subject)
        text, html = render(template, {"subject": subject, "brand": brand, **context})
    return await OutgoingMail.objects.acreate(
        kind=kind,
        user=user,
        to=to,
        subject=subject[:200],
        text=text,
        html=html,
        dedupe_key=dedupe_key,
        expires_at=expires_at,
    )


def deliver(config: MailSettings, messages: list[Message]) -> list[str]:
    """Send over one SMTP connection. Returns an error text per message, empty if it was sent.

    Runs in a thread and does not touch the database.
    """
    password = config.password
    if password is None:
        return [_("Das SMTP-Passwort lässt sich nicht entschlüsseln. Bitte trag es neu ein.")] * len(messages)
    connection = _connection(config, password)
    try:
        connection.open()
    except Exception as exc:
        return [_describe(exc, config)] * len(messages)
    errors = []
    try:
        for message in messages:
            mail = EmailMultiAlternatives(message.subject, message.text, config.sender, [message.to])
            if message.html:
                mail.attach_alternative(message.html, "text/html")
            try:
                connection.send_messages([mail])
            except Exception as exc:
                errors.append(_describe(exc, config))
            else:
                errors.append("")
    finally:
        try:
            connection.close()
        except Exception:
            logger.debug("Closing the SMTP connection failed", exc_info=True)
    return errors


def _connection(config: MailSettings, password: str):
    """The backend from settings.MAILERS, pointed at the SMTP server from the settings page."""
    mailer = settings.MAILERS["default"]
    backend = import_string(mailer.get("BACKEND", "django.core.mail.backends.smtp.EmailBackend"))
    options = dict(mailer.get("OPTIONS", {}))
    # Other backends (e.g. the in-memory one in tests) take no server options.
    if issubclass(backend, SmtpBackend):
        options |= {
            "host": config.host,
            "port": config.port,
            "username": config.username or None,
            "password": password or None,
            "use_tls": config.security == MailSettings.Security.STARTTLS,
            "use_ssl": config.security == MailSettings.Security.SSL,
            "timeout": SMTP_TIMEOUT,
        }
    return backend(alias="default", **options)


def _describe(exc: Exception, config: MailSettings) -> str:
    """The error as text. Port and encryption that do not fit together get a hint instead of the raw TLS error."""
    if hint := _security_hint(exc, config):
        return hint
    return (f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__)[:500]


def _security_hint(exc: Exception, config: MailSettings) -> str:
    """What to change when the error is the typical sign of a wrong encryption setting, "" for any other error."""
    Security = MailSettings.Security
    # A server that wants STARTTLS answers the TLS handshake of "SSL/TLS" in plain text.
    if config.security == Security.SSL and isinstance(exc, ssl.SSLError) and "WRONG_VERSION_NUMBER" in str(exc):
        return _(
            "Der Server antwortet auf Port %(port)s nicht mit SSL/TLS. Wahrscheinlich erwartet er STARTTLS "
            "(üblich auf Port 587). Wähle als Verschlüsselung „STARTTLS“."
        ) % {"port": config.port}
    if config.security == Security.STARTTLS:
        if isinstance(exc, smtplib.SMTPNotSupportedError):
            return _(
                "Der Server auf Port %(port)s bietet kein STARTTLS an. Wahrscheinlich erwartet er SSL/TLS "
                "von Anfang an (üblich auf Port 465). Wähle als Verschlüsselung „SSL/TLS“ und Port 465."
            ) % {"port": config.port}
        # An SSL/TLS port waits for the client to speak first, so it never sends the greeting STARTTLS waits for.
        if config.port == SSL_PORT and isinstance(exc, TimeoutError | smtplib.SMTPServerDisconnected):
            return _(
                "Port 465 erwartet SSL/TLS von Anfang an und antwortet nicht auf STARTTLS. "
                "Wähle als Verschlüsselung „SSL/TLS“ oder nutze Port 587."
            )
    return ""


async def asend_now(config: MailSettings, message: Message) -> str:
    """Send one e-mail right away, bypassing the queue (for the test e-mail). Returns the error, if any."""
    if not config.is_configured:
        raise MailNotConfigured
    return (await asyncio.to_thread(deliver, config, [message]))[0]


async def send_due(
    now: datetime | None = None, on_failed: Callable[[OutgoingMail], Awaitable[None]] | None = None
) -> int:
    """Send the e-mails that are due. Returns how many were sent.

    ``on_failed`` is called for each e-mail that failed for the last time.
    """
    now = now or timezone.now()
    await OutgoingMail.objects.filter(status=OutgoingMail.Status.PENDING, expires_at__lt=now).aupdate(
        status=OutgoingMail.Status.EXPIRED
    )
    await _forget_secrets()
    config = await MailSettings.aload()
    if not config.is_configured:
        return 0
    due = [
        mail
        async for mail in OutgoingMail.objects.filter(
            status=OutgoingMail.Status.PENDING, next_attempt_at__lte=now
        ).order_by("next_attempt_at", "pk")[:BATCH]
    ]
    if not due:
        return 0
    messages = [Message(m.to, m.subject, m.text, m.html) for m in due]
    errors = await asyncio.to_thread(deliver, config, messages)
    sent = 0
    for mail, error in zip(due, errors, strict=True):
        mail.attempts += 1
        if not error:
            mail.status, mail.sent_at, mail.last_error = OutgoingMail.Status.SENT, timezone.now(), ""
            sent += 1
        else:
            logger.warning("Sending e-mail %s to %s failed: %s", mail.pk, mail.to, error)
            mail.last_error = error
            if mail.attempts > len(RETRY_DELAYS):
                mail.status = OutgoingMail.Status.FAILED
            else:
                mail.next_attempt_at = now + RETRY_DELAYS[mail.attempts - 1]
        await mail.asave(update_fields=["attempts", "status", "sent_at", "last_error", "next_attempt_at"])
        if on_failed and mail.status == OutgoingMail.Status.FAILED:
            await on_failed(mail)
    await _forget_secrets()
    return sent


async def _forget_secrets() -> None:
    """Drop the text of password reset and login link e-mails that are done, so no database copy holds the links."""
    done = OutgoingMail.objects.filter(kind__in=OutgoingMail.SECRET_KINDS).exclude(status=OutgoingMail.Status.PENDING)
    await done.exclude(text="", html="").aupdate(text="", html="")


async def aretry(pk: UUID) -> bool:
    """Queue a failed e-mail again."""
    failed = OutgoingMail.objects.filter(pk=pk, status=OutgoingMail.Status.FAILED)
    updated = await failed.exclude(kind__in=OutgoingMail.SECRET_KINDS).aupdate(
        status=OutgoingMail.Status.PENDING, attempts=0, next_attempt_at=timezone.now()
    )
    return bool(updated)


async def ais_configured() -> bool:
    return (await MailSettings.aload()).is_configured
