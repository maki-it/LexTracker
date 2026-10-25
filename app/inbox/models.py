from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel
from inbox.levels import BADGES, Level


class Message(UUIDModel):
    """A message for one user, shown in the bell and on the messages page.

    A message that goes to several users is stored once per user, so each reads and deletes their own.
    Messages are created with ``inbox.service.anotify``.
    """

    user = models.ForeignKey("accounts.User", verbose_name=_("Empfänger"), on_delete=models.CASCADE, related_name="+")
    level = models.SmallIntegerField(_("Priorität"), choices=Level)
    # What it is about, e.g. "backup.failed". Lets users mute one kind later.
    kind = models.CharField(_("Art"), max_length=50)
    title = models.CharField(_("Titel"), max_length=200)
    body = models.TextField(_("Text"), blank=True)
    # A path in the app that the message links to, e.g. the page with the settings concerned.
    url = models.CharField(_("Ziel"), max_length=300, blank=True)
    # An unread message with the same key is updated instead of adding another one (see ``anotify``).
    dedupe_key = models.CharField(max_length=200, blank=True)
    count = models.PositiveIntegerField(_("Anzahl"), default=1)
    created_at = models.DateTimeField(_("erstellt"), auto_now_add=True)
    last_at = models.DateTimeField(_("zuletzt"), default=timezone.now)
    read_at = models.DateTimeField(_("gelesen"), null=True, blank=True)

    class Meta:
        verbose_name = _("Nachricht")
        verbose_name_plural = _("Nachrichten")
        ordering = ["-last_at", "-id"]
        indexes = [
            # The bell counts the unread messages of a user on every page.
            models.Index(
                fields=["user", "level"], condition=models.Q(read_at__isnull=True), name="inbox_unread_by_user"
            ),
            models.Index(fields=["user", "-last_at"], name="inbox_by_user"),
            models.Index(fields=["level", "last_at"], name="inbox_by_level"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dedupe_key"],
                condition=models.Q(read_at__isnull=True) & ~models.Q(dedupe_key=""),
                name="inbox_one_unread_per_key",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.get_level_display()}: {self.title}"

    @property
    def badge_class(self) -> str:
        return BADGES[self.level]

    @property
    def is_unread(self) -> bool:
        return self.read_at is None
