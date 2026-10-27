import hashlib
import secrets

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.models import UUIDModel
from inbox.levels import EMAIL_CHOICES, Level


class User(UUIDModel, AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", _("Administrator")
        EMPLOYEE = "employee", _("Mitarbeiter")
        CUSTOMER = "customer", _("Kunde")

    class Theme(models.TextChoices):
        SYSTEM = "system", _("wie das System")
        LIGHT = "light", _("hell")
        DARK = "dark", _("dunkel")

    class DateFormat(models.TextChoices):
        # Django date format strings, shown with an example.
        NUMERIC = "d.m.Y", "31.12.2026"
        SHORT = "d.m.y", "31.12.26"
        LONG = "j. F Y", _("31. Dezember 2026")
        ISO = "Y-m-d", "2026-12-31"

    class DurationFormat(models.TextChoices):
        CLOCK = "clock", _("Stunden und Minuten (2:45)")
        DECIMAL = "decimal", _("Dezimalstunden (2,75)")

    class PageSize(models.IntegerChoices):
        SMALL = 25, "25"
        MEDIUM = 50, "50"
        LARGE = 100, "100"
        XLARGE = 200, "200"

    # Empty until the first request after signing in: then the language of the login page is adopted.
    language = models.CharField(
        _("Sprache"),
        max_length=10,
        choices=[("", _("Automatisch")), *settings.LANGUAGES],
        blank=True,
        default="",
        help_text=_("Gilt für die Oberfläche und die E-Mails an dich."),
    )
    role = models.CharField(_("Rolle"), max_length=20, choices=Role, default=Role.ADMIN)
    theme = models.CharField(_("Darstellung"), max_length=10, choices=Theme, default=Theme.SYSTEM)
    date_format = models.CharField(_("Datumsformat"), max_length=10, choices=DateFormat, default=DateFormat.NUMERIC)
    duration_format = models.CharField(
        _("Zeitdauern anzeigen als"), max_length=10, choices=DurationFormat, default=DurationFormat.CLOCK
    )
    list_page_size = models.PositiveSmallIntegerField(
        _("Einträge pro Seite"),
        choices=PageSize,
        default=PageSize.MEDIUM,
        help_text=_("Wie viele Kunden oder Projekte eine Liste auf einmal lädt. Beim Scrollen kommen weitere dazu."),
    )
    weekly_report = models.BooleanField(
        _("Wochenbericht per E-Mail"), default=True, help_text=_("Deine Stunden der letzten sieben Tage.")
    )
    timer_reminder = models.BooleanField(
        _("Erinnerung, wenn mein Timer sehr lange läuft"),
        default=True,
        help_text=_("Falls du vergessen hast, ihn zu stoppen."),
    )
    message_level = models.SmallIntegerField(
        _("Nachrichten anzeigen ab"),
        choices=Level,
        default=Level.INFO,
        help_text=_("Welche Nachrichten in der Glocke stehen. Kritische siehst du immer."),
    )
    message_email_level = models.SmallIntegerField(
        _("Nachrichten auch per E-Mail ab"),
        choices=EMAIL_CHOICES,
        default=Level.CRITICAL,
        help_text=_(
            "Gilt nur, wenn der E-Mail-Versand eingerichtet ist. "
            "Eine Meldung, die sich wiederholt, schickt nur eine E-Mail."
        ),
    )
    # Only set for customer logins: the customer whose data this user may see.
    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name=_("Kunde"),
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
    )
    # Only for employees: what they may book time on. A customer stands for all of its projects.
    bookable_customers = models.ManyToManyField(
        "customers.Customer",
        verbose_name=_("bucht auf alle Projekte dieser Kunden"),
        blank=True,
        related_name="bookable_by",
    )
    bookable_projects = models.ManyToManyField(
        "projects.Project", verbose_name=_("bucht auf diese Projekte"), blank=True, related_name="bookable_by"
    )
    # What a customer login may see besides the customer's projects.
    portal_budget = models.BooleanField(_("sieht Budgets"), default=True)
    portal_entries = models.BooleanField(_("sieht Zeiteinträge"), default=True)
    portal_descriptions = models.BooleanField(
        _("sieht Beschreibungen der Zeiteinträge"),
        default=True,
        help_text=_("Nur wirksam, wenn Zeiteinträge sichtbar sind."),
    )
    portal_invoices = models.BooleanField(_("sieht Rechnungen"), default=True)
    # Off by default: changes go straight to the contact in Lexware Office.
    portal_contact = models.BooleanField(_("darf Kontaktdaten und Rechnungsadresse ändern"), default=False)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == self.Role.EMPLOYEE

    @property
    def is_customer(self) -> bool:
        return self.role == self.Role.CUSTOMER

    @property
    def ui_language(self) -> str:
        """The language for this user's interface and e-mails, the default one until they have signed in."""
        return self.language or settings.LANGUAGE_CODE

    class Meta:
        verbose_name = _("Benutzer")
        verbose_name_plural = _("Benutzer")
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role="customer", customer__isnull=False) | ~models.Q(role="customer"),
                name="customer_user_has_customer",
            ),
        ]


class ApiToken(UUIDModel):
    """A token for programs acting as a user, e.g. an AI agent using the MCP server.

    Only a hash is stored; the token itself is shown once when it is created.
    """

    PREFIX = "lxt_"

    user = models.ForeignKey(User, verbose_name=_("Benutzer"), on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField(
        _("Name"), max_length=100, help_text=_("Wofür du den Token nutzt, z. B. „Claude Code Laptop“.")
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    # The first characters, so the token can be recognised in the list.
    hint = models.CharField(max_length=12, editable=False)
    created_at = models.DateTimeField(_("erstellt"), auto_now_add=True)
    last_used_at = models.DateTimeField(_("zuletzt benutzt"), null=True, blank=True, editable=False)

    class Meta:
        verbose_name = _("API-Token")
        verbose_name_plural = _("API-Tokens")
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name

    @staticmethod
    def hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    @classmethod
    def issue(cls, user: User, name: str) -> tuple[ApiToken, str]:
        """Create a token and return it with its key, which is not stored."""
        key = cls.PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(user=user, name=name, key_hash=cls.hash(key), hint=key[:10])
        return token, key


class LoginFailure(UUIDModel):
    """A wrong password or code, for the login rate limit (see accounts.ratelimit)."""

    ip_address = models.GenericIPAddressField(_("IP-Adresse"))
    username = models.CharField(_("Benutzername"), max_length=150, blank=True)
    at = models.DateTimeField(_("Zeitpunkt"), auto_now_add=True)

    class Meta:
        verbose_name = _("Fehlgeschlagene Anmeldung")
        verbose_name_plural = _("Fehlgeschlagene Anmeldungen")
        indexes = [models.Index(fields=["ip_address", "at"])]

    def __str__(self) -> str:
        return f"{self.ip_address} {self.at:%d.%m.%Y %H:%M}"


class LoginLink(UUIDModel):
    """A link that signs a user in without a password, sent by e-mail (see ``accounts.links``).

    Only a hash is stored. A link works once and only until it expires.
    """

    user = models.ForeignKey(User, verbose_name=_("Benutzer"), on_delete=models.CASCADE, related_name="login_links")
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    created_at = models.DateTimeField(_("erstellt"), auto_now_add=True)
    expires_at = models.DateTimeField(_("gültig bis"))
    used_at = models.DateTimeField(_("benutzt"), null=True, blank=True)

    class Meta:
        verbose_name = _("Anmeldelink")
        verbose_name_plural = _("Anmeldelinks")

    def __str__(self) -> str:
        return f"{self.user} {self.created_at:%d.%m.%Y %H:%M}"

    @staticmethod
    def hash(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()
