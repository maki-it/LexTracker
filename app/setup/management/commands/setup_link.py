from django.core.management.base import BaseCommand

from accounts.models import User
from setup.code import setup_path


class Command(BaseCommand):
    help = "Print the link that opens the setup of a fresh instance (only works while no account exists)."

    def handle(self, *args, **options):
        if User.objects.exists():
            self.stdout.write("The app is already set up; the setup link no longer works.")
            return
        self.stdout.write(f"Open this path on your LexTracker address: {setup_path()}")
