from django.core.management.base import BaseCommand

from core import backup


class Command(BaseCommand):
    help = "Copy the database into the backup folder and delete backups beyond APP_BACKUP_KEEP."

    def handle(self, *args, **options):
        path = backup.create_backup()
        self.stdout.write(self.style.SUCCESS(f"Backup written to {path}"))
