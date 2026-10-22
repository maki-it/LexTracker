import asyncio
import signal

from django.core.management.base import BaseCommand

from core.scheduler import run


class Command(BaseCommand):
    help = "Run recurring jobs, such as the automatic customer import, until stopped."

    def handle(self, *args, **options):
        asyncio.run(self._run())

    async def _run(self):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        # As PID 1 in a container, Python ignores SIGTERM unless it handles it itself.
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await run(stop)
