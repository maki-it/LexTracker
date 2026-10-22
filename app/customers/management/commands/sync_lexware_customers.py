import asyncio

from django.core.management.base import BaseCommand, CommandError

from customers.sync import sync_customers
from lexware.client import LexwareError, client_from_settings


class Command(BaseCommand):
    help = "Import new customers from Lexware Office and update changed ones."

    def handle(self, *args, **options):
        try:
            result = asyncio.run(self._sync())
        except LexwareError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(f"{result.created} neu, {result.updated} aktualisiert, {result.unchanged} unverändert.")
        )

    async def _sync(self):
        async with client_from_settings() as client:
            return await sync_customers(client)
