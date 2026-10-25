"""The messages the app sends on its own: what happened in the background jobs and when something went wrong.

Each function says what to tell whom and how important it is, so the jobs only report the outcome.
Storing a message never raises: a message that cannot be stored must not stop the job that reports it.
"""

import functools
import logging
from collections.abc import Awaitable, Callable

from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from core.i18n import fmt
from inbox.levels import Level
from inbox.service import Text, anotify, aresolve
from lexware.client import LexwareUnauthorized
from mailer.models import OutgoingMail

logger = logging.getLogger(__name__)

# A job that fails this often in a row is critical, not just a warning.
CRITICAL_AFTER = 3


def safely[**P](function: Callable[P, Awaitable[None]]) -> Callable[P, Awaitable[None]]:
    @functools.wraps(function)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> None:
        try:
            await function(*args, **kwargs)
        except Exception:
            logger.exception("Could not store a message")

    return wrapper


@safely
async def job_done(key: str, label: Text, summary: Text, *, changed: bool) -> None:
    """An import or sync ran through. Changes are news (info); a run without any is just noted (debug)."""
    await aresolve(f"job:{key}")
    await aresolve("lexware.key")
    url = f"{reverse('core:settings')}?tab=lexware"
    title = fmt(_("%(label)s abgeschlossen"), label=label)
    if changed:
        await anotify(Level.INFO, f"{key}.done", title, summary, url=url)
    else:
        # One line that counts the runs, instead of one per run.
        await anotify(Level.DEBUG, f"{key}.done", title, summary, url=url, dedupe_key=f"{key}.done")


@safely
async def job_failed(key: str, label: Text, error: Exception) -> None:
    url = f"{reverse('core:settings')}?tab=lexware"
    if isinstance(error, LexwareUnauthorized):
        await anotify(
            Level.CRITICAL,
            "lexware.key",
            _("Lexware lehnt den API-Schlüssel ab"),
            fmt(
                _("%(label)s ist fehlgeschlagen. Bitte prüfe oder ersetze den Schlüssel in den Einstellungen."),
                label=label,
            ),
            url=url,
            dedupe_key="lexware.key",
        )
        return
    await anotify(
        Level.WARNING,
        f"{key}.failed",
        fmt(_("%(label)s fehlgeschlagen"), label=label),
        str(error),
        url=url,
        dedupe_key=f"job:{key}",
        escalate_after=CRITICAL_AFTER,
    )


@safely
async def backup_done(name: str) -> None:
    await aresolve("backup")
    await anotify(
        Level.DEBUG,
        "backup.done",
        _("Datensicherung erstellt"),
        name,
        url=reverse("core:backups"),
        dedupe_key="backup.done",
    )


@safely
async def backup_failed(error: Exception) -> None:
    await anotify(
        Level.CRITICAL,
        "backup.failed",
        _("Datensicherung fehlgeschlagen"),
        f"{type(error).__name__}: {error}"[:500],
        url=reverse("core:backups"),
        dedupe_key="backup",
    )


@safely
async def backup_restored(name: str, by: str) -> None:
    await anotify(
        Level.INFO,
        "backup.restored",
        _("Datensicherung wiederhergestellt"),
        fmt(_("%(name)s, durch %(user)s."), name=name, user=by),
        url=reverse("core:backups"),
    )


@safely
async def backup_uploaded(name: str, by: str) -> None:
    await anotify(
        Level.INFO,
        "backup.uploaded",
        _("Datensicherung hochgeladen"),
        fmt(_("%(name)s, durch %(user)s."), name=name, user=by),
        url=reverse("core:backups"),
    )


@safely
async def mail_failed(mail: OutgoingMail) -> None:
    """An e-mail gave up after its last attempt. Several of them are counted in one message."""
    await anotify(
        Level.WARNING,
        "mail.failed",
        _("E-Mail konnte nicht zugestellt werden"),
        fmt(_("%(subject)s an %(to)s: %(error)s"), subject=mail.subject, to=mail.to, error=mail.last_error),
        url=reverse("mailer:settings"),
        dedupe_key="mail.failed",
    )
