"""Recurring jobs, run by ``manage.py run_scheduler`` in its own process (its own container in Docker)."""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from core.models import AppSettings
from customers.sync import sync_and_record
from lexware.client import LexwareError

logger = logging.getLogger(__name__)

# How often the scheduler looks for due jobs. Settings changes apply within this time.
CHECK_INTERVAL = 60


async def import_customers_if_due(now: datetime) -> bool:
    """Import customers from Lexware if the interval set on the settings page has passed."""
    app_settings = await AppSettings.aload()
    interval = app_settings.lexware_sync_interval
    if not interval or not settings.LEXWARE_API_KEY:
        return False
    last = app_settings.lexware_synced_at
    if last and now - last < timedelta(minutes=interval):
        return False
    try:
        result = await sync_and_record()
    except LexwareError as exc:
        logger.warning("Automatic customer import failed: %s", exc)
    else:
        logger.info("Automatic customer import: %s", result.summary)
    return True


async def run(stop: asyncio.Event) -> None:
    logger.info("Scheduler started")
    while not stop.is_set():
        try:
            await import_customers_if_due(timezone.now())
        except Exception:
            # Keep running: a broken job must not stop the others or the next attempt.
            logger.exception("Scheduled job failed")
        with suppress(TimeoutError):
            await asyncio.wait_for(stop.wait(), CHECK_INTERVAL)
    logger.info("Scheduler stopped")
