from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from core import crypto
from core.models import UUIDModel

PASSWORD_PURPOSE = "smtp-password"
# The usual ports: SSL/TLS from the first byte (SMTPS) and STARTTLS (submission). They are not interchangeable.
SSL_PORT = 465
STARTTLS_PORT = 587


class MailSettings(models.Model):
    """The SMTP server the app sends its e-mails through, set on the settings page. There is only one row.

    The password is stored encrypted (see ``core.crypto``) and never shown again.
    """

    class Security(models.TextChoices):
        STARTTLS = "starttls", _("STARTTLS (meist Port 587)")
        SSL = "ssl", _("SSL/TLS (meist Port 465)")
        NONE = "none", _("keine (nur im eigenen Netz)")

    host = models.CharField(_("SMTP-Server"), max_length=200, blank=True, help_text=_("z. B. smtp.example.de"))
    port = models.PositiveIntegerField(_("Port"), default=587)
    security = models.CharField(_("Verschlüsselung"), max_length=10, choices=Security, default=Security.STARTTLS)
    username = models.CharField(_("Benutzername"), max_length=200, blank=True)
    encrypted_password = models.TextField(blank=True, editable=False)
    from_address = models.EmailField(
        _("Absenderadresse"), blank=True, help_text=_("Muss der SMTP-Server für dein Konto erlauben.")
    )
    from_name = models.CharField(_("Absendername"), max_length=100, default="LexTracker", blank=True)
    updated_at = models.DateTimeField(_("geändert"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = verbose_name_plural = _("E-Mail-Versand")

    def __str__(self) -> str:
        return "E-Mail-Versand"

    @classmethod
    async def aload(cls) -> MailSettings:
        return (await cls.objects.aget_or_create(pk=1))[0]

    @property
    def is_configured(self) -> bool:
        return bool(self.host and self.from_address)

    @property
    def sender(self) -> str:
        return f'"{self.from_name}" <{self.from_address}>' if self.from_name else self.from_address

    @property
    def password(self) -> str | None:
        """The SMTP password, "" if none is set, or None if it cannot be decrypted anymore."""
        if not self.encrypted_password:
            return ""
        return crypto.decrypt(self.encrypted_password, PASSWORD_PURPOSE)

    def set_password(self, password: str) -> None:
        self.encrypted_password = crypto.encrypt(password, PASSWORD_PURPOSE) if password else ""


class OutgoingMail(UUIDModel):
    """An e-mail waiting to be sent, or sent already. The scheduler sends what is due (see ``mailer.outbox``)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("wartet")
        SENT = "sent", _("verschickt")
        FAILED = "failed", _("fehlgeschlagen")
        EXPIRED = "expired", _("verfallen")

    class Kind(models.TextChoices):
        PASSWORD_RESET = "password_reset", _("Passwort zurücksetzen")
        LOGIN_LINK = "login_link", _("Anmeldelink")
        WEEKLY_REPORT = "weekly_report", _("Wochenbericht")
        TIMER_REMINDER = "timer_reminder", _("Erinnerung an laufenden Timer")
        INVITATION = "invitation", _("Einladung")
        INVOICE_OVERDUE = "invoice_overdue", _("Hinweis auf überfällige Rechnung")
        NOTIFICATION = "notification", _("Nachricht")
        REMINDER = "reminder", _("Erinnerung")

    # Their links sign in or set a password, so their text is not kept once it no longer needs sending.
    SECRET_KINDS = (Kind.PASSWORD_RESET, Kind.LOGIN_LINK, Kind.INVITATION)

    kind = models.CharField(_("Art"), max_length=30, choices=Kind)
    user = models.ForeignKey(
        "accounts.User", verbose_name=_("Benutzer"), on_delete=models.CASCADE, null=True, blank=True, related_name="+"
    )
    to = models.EmailField(_("an"))
    subject = models.CharField(_("Betreff"), max_length=200)
    text = models.TextField(_("Text"))
    html = models.TextField(_("HTML"), blank=True)
    # Sent only once per key, e.g. one reminder per running timer.
    dedupe_key = models.CharField(max_length=200, blank=True, db_index=True)
    status = models.CharField(_("Status"), max_length=10, choices=Status, default=Status.PENDING)
    created_at = models.DateTimeField(_("erstellt"), auto_now_add=True)
    next_attempt_at = models.DateTimeField(_("nächster Versuch"), default=timezone.now)
    # Not sent after this, e.g. once the link in it has expired.
    expires_at = models.DateTimeField(_("verfällt"), null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(_("Versuche"), default=0)
    sent_at = models.DateTimeField(_("verschickt"), null=True, blank=True)
    last_error = models.CharField(_("letzter Fehler"), max_length=500, blank=True)

    class Meta:
        verbose_name = _("E-Mail")
        verbose_name_plural = _("E-Mails")
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]

    def __str__(self) -> str:
        return f"{self.subject} → {self.to}"

    @property
    def can_retry(self) -> bool:
        return self.status == self.Status.FAILED and self.kind not in self.SECRET_KINDS
