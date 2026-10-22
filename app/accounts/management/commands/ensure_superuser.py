import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Create an admin account from DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD and "
        "DJANGO_SUPERUSER_EMAIL. Does nothing if the variables are unset or the account exists."
    )

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME/PASSWORD not set, skipping.")
            return

        user_model = get_user_model()
        if user_model.objects.filter(username=username).exists():
            self.stdout.write(f"Admin account '{username}' already exists.")
            return

        user_model.objects.create_superuser(
            username=username, email=os.environ.get("DJANGO_SUPERUSER_EMAIL", ""), password=password
        )
        self.stdout.write(self.style.SUCCESS(f"Admin account '{username}' created."))
