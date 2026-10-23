from django.contrib.auth.forms import BaseUserCreationForm
from django.db import transaction

from accounts.models import User
from core.forms import StyledFormMixin


class AdminAccountForm(StyledFormMixin, BaseUserCreationForm):
    """The first account of a fresh instance: an administrator with access to the Django admin."""

    class Meta(BaseUserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "email")

    def save(self, commit: bool = True) -> User:
        user = super().save(commit=False)
        user.role = User.Role.ADMIN
        user.is_staff = user.is_superuser = True
        if commit:
            with transaction.atomic():
                # Two browsers on a fresh instance at once: only the first one gets the account.
                if User.objects.exists():
                    raise AlreadySetUp
                user.save()
        return user


class AlreadySetUp(Exception):
    """Someone else created the first account in the meantime."""
