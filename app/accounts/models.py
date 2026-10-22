import hashlib
import secrets

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        EMPLOYEE = "employee", "Mitarbeiter"
        CUSTOMER = "customer", "Kunde"

    class Theme(models.TextChoices):
        SYSTEM = "system", "wie das System"
        LIGHT = "light", "hell"
        DARK = "dark", "dunkel"

    class DateFormat(models.TextChoices):
        # Django date format strings, shown with an example.
        NUMERIC = "d.m.Y", "31.12.2026"
        SHORT = "d.m.y", "31.12.26"
        LONG = "j. F Y", "31. Dezember 2026"
        ISO = "Y-m-d", "2026-12-31"

    class DurationFormat(models.TextChoices):
        CLOCK = "clock", "Stunden und Minuten (2:45)"
        DECIMAL = "decimal", "Dezimalstunden (2,75)"

    role = models.CharField("Rolle", max_length=20, choices=Role, default=Role.ADMIN)
    theme = models.CharField("Darstellung", max_length=10, choices=Theme, default=Theme.SYSTEM)
    date_format = models.CharField("Datumsformat", max_length=10, choices=DateFormat, default=DateFormat.NUMERIC)
    duration_format = models.CharField(
        "Zeitdauern anzeigen als", max_length=10, choices=DurationFormat, default=DurationFormat.CLOCK
    )
    # Only set for customer logins: the customer whose data this user may see.
    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name="Kunde",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
    )
    # Only for employees: what they may book time on. A customer stands for all of its projects.
    bookable_customers = models.ManyToManyField(
        "customers.Customer",
        verbose_name="bucht auf alle Projekte dieser Kunden",
        blank=True,
        related_name="bookable_by",
    )
    bookable_projects = models.ManyToManyField(
        "projects.Project", verbose_name="bucht auf diese Projekte", blank=True, related_name="bookable_by"
    )
    # What a customer login may see besides the customer's projects.
    portal_budget = models.BooleanField("sieht Budgets", default=True)
    portal_entries = models.BooleanField("sieht Zeiteinträge", default=True)
    portal_descriptions = models.BooleanField(
        "sieht Beschreibungen der Zeiteinträge", default=True, help_text="Nur wirksam, wenn Zeiteinträge sichtbar sind."
    )
    portal_invoices = models.BooleanField("sieht Rechnungen", default=True)

    @property
    def is_admin(self) -> bool:
        return self.role == self.Role.ADMIN

    @property
    def is_employee(self) -> bool:
        return self.role == self.Role.EMPLOYEE

    @property
    def is_customer(self) -> bool:
        return self.role == self.Role.CUSTOMER

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role="customer", customer__isnull=False) | ~models.Q(role="customer"),
                name="customer_user_has_customer",
            ),
        ]


class ApiToken(models.Model):
    """A token for programs acting as a user, e.g. an AI agent using the MCP server.

    Only a hash is stored; the token itself is shown once when it is created.
    """

    PREFIX = "lxt_"

    user = models.ForeignKey(User, verbose_name="Benutzer", on_delete=models.CASCADE, related_name="api_tokens")
    name = models.CharField("Name", max_length=100, help_text="Wofür du den Token nutzt, z. B. „Claude Code Laptop“.")
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    # The first characters, so the token can be recognised in the list.
    hint = models.CharField(max_length=12, editable=False)
    created_at = models.DateTimeField("erstellt", auto_now_add=True)
    last_used_at = models.DateTimeField("zuletzt benutzt", null=True, blank=True, editable=False)

    class Meta:
        verbose_name = "API-Token"
        verbose_name_plural = "API-Tokens"
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
