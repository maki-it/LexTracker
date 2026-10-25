from django.db import models
from django.utils.translation import gettext_lazy as _


class Level(models.IntegerChoices):
    """How important a message is. The numbers are those of ``logging``, so "from warning up" is a comparison."""

    DEBUG = 10, _("Debug")
    INFO = 20, _("Info")
    WARNING = 30, _("Warnung")
    CRITICAL = 40, _("Kritisch")


# What a user can choose as the level from which messages are also sent by e-mail. 0 turns it off.
NEVER = 0
EMAIL_CHOICES = [
    (NEVER, "nie"),
    (Level.CRITICAL, Level.CRITICAL.label),
    (Level.WARNING, Level.WARNING.label),
    (Level.INFO, Level.INFO.label),
]

# The badge class for each level, see ``badge-*`` in assets/tailwind.css.
BADGES = {
    Level.DEBUG: "",
    Level.INFO: "badge-primary",
    Level.WARNING: "badge-warning",
    Level.CRITICAL: "badge-danger",
}
