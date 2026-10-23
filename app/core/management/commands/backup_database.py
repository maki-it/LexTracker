from django.core.management.base import BaseCommand

from core import backup


class Command(BaseCommand):
    help = "Copy the database into the backup folder and delete the copies beyond the number set on the settings page."

    def handle(self, *args, **options):
        path = backup.backup_and_record()
        self.stdout.write(self.style.SUCCESS(f"Backup written to {path}"))
