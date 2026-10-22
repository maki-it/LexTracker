from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        EMPLOYEE = "employee", "Mitarbeiter"
        CUSTOMER = "customer", "Kunde"

    role = models.CharField("Rolle", max_length=20, choices=Role, default=Role.ADMIN)
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
