"""What a device can subscribe to. Each device picks its own, so the phone can show the running timer and the
desktop browser only the reminders."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from inbox.levels import Level


class Topic(models.TextChoices):
    REMINDER = "reminder", _("Fällige Erinnerungen")
    CRITICAL = "critical", _("Kritische Meldungen")
    WARNING = "warning", _("Warnungen")
    OVERDUE_INVOICE = "overdue_invoice", _("Überfällige Rechnungen")
    TIMER_LONG = "timer_long", _("Timer läuft schon lange")
    TIMER_LIVE = "timer_live", _("Laufenden Timer anzeigen")


# What a new device gets: what needs an answer. Everything else is opt-in.
DEFAULT = [Topic.REMINDER, Topic.CRITICAL]

HELP = {
    Topic.REMINDER: _("Wenn eine deiner Erinnerungen fällig wird."),
    Topic.CRITICAL: _("Fehler, die dringend Aufmerksamkeit brauchen, z. B. eine fehlgeschlagene Datensicherung."),
    Topic.WARNING: _("Weniger dringende Probleme, z. B. ein fehlgeschlagener Abgleich mit Lexware."),
    Topic.OVERDUE_INVOICE: _("Sobald eine Rechnung überfällig wird."),
    Topic.TIMER_LONG: _("Wenn dein Timer länger läuft als in den Einstellungen festgelegt."),
    Topic.TIMER_LIVE: _(
        "Zeigt den laufenden Timer als Benachrichtigung, solange er läuft, und nach dem Stoppen kurz die Dauer."
    ),
}

# Only administrators see invoices.
ADMIN_ONLY = {Topic.OVERDUE_INVOICE}

# The topic of a message by what it is about. Messages of other kinds are sorted by their level.
KIND_TOPICS = {
    "reminder.due": Topic.REMINDER,
    "timer.long": Topic.TIMER_LONG,
    "invoice.overdue": Topic.OVERDUE_INVOICE,
}
LEVEL_TOPICS = {Level.CRITICAL: Topic.CRITICAL, Level.WARNING: Topic.WARNING}


def topic_of(kind: str, level: int) -> Topic | None:
    """The topic a message belongs to, None for those that are never pushed (info and debug)."""
    return KIND_TOPICS.get(kind) or LEVEL_TOPICS.get(level)


def available(user) -> list[Topic]:
    return [topic for topic in Topic if user.is_admin or topic not in ADMIN_ONLY]


def default_topics() -> list[str]:
    return [str(topic.value) for topic in DEFAULT]


def choices(user) -> list[tuple[Topic, str, str]]:
    """What the user can pick, with the words for the settings page. Nothing for customers: they get no push."""
    if user.is_customer:
        return []
    return [(topic, str(topic.label), str(HELP[topic])) for topic in available(user)]
