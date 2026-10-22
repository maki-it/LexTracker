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

    role = models.CharField("Rolle", max_length=20, choices=Role, default=Role.ADMIN)
    theme = models.CharField("Darstellung", max_length=10, choices=Theme, default=Theme.SYSTEM)
    date_format = models.CharField("Datumsformat", max_length=10, choices=DateFormat, default=DateFormat.NUMERIC)
    # Only set for customer logins: the customer whose data this user may see.
    customer = models.ForeignKey(
        "customers.Customer",
        verbose_name="Kunde",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="users",
    )

    class Meta:
        verbose_name = "Benutzer"
        verbose_name_plural = "Benutzer"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role="customer", customer__isnull=False) | ~models.Q(role="customer"),
                name="customer_user_has_customer",
            ),
        ]
