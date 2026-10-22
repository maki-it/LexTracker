import asyncio

from django.core.management.base import BaseCommand, CommandError

from customers.sync import sync_and_record
from lexware.client import LexwareError


class Command(BaseCommand):
    help = "Import new customers from Lexware Office and update changed ones."

    def handle(self, *args, **options):
        try:
            result = asyncio.run(sync_and_record())
        except LexwareError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(result.summary))
