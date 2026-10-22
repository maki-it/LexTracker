"""Copies of the SQLite database, made daily by the scheduler or on demand by ``manage.py backup_database``."""

import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone


def _backups() -> list[Path]:
    # The names start with the date and time, so sorting by name sorts by age.
    return sorted(settings.BACKUP_DIR.glob("db-*.sqlite3"))


def create_backup(now: datetime | None = None) -> Path:
    """Copy the database with SQLite's backup API, which is safe while the app writes to it."""
    local = timezone.localtime(now)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = settings.BACKUP_DIR / f"db-{local:%Y-%m-%d-%H%M%S}.sqlite3"
    # Write to a temporary name first, so a half-written copy never looks like a backup.
    partial = target.with_suffix(".partial")
    connection.ensure_connection()
    copy = sqlite3.connect(partial)
    try:
        connection.connection.backup(copy)
    finally:
        copy.close()
    partial.rename(target)
    prune()
    return target


def prune(keep: int | None = None) -> list[Path]:
    """Delete all but the newest ``keep`` backups (BACKUP_KEEP by default). Returns the deleted files."""
    keep = settings.BACKUP_KEEP if keep is None else keep
    old = _backups()[:-keep] if keep else []
    for path in old:
        path.unlink()
    return old


def is_due(now: datetime) -> bool:
    """Whether today's backup is missing and its time has come."""
    if not settings.BACKUP_KEEP:
        return False
    local = timezone.localtime(now)
    if local.time() < settings.BACKUP_TIME:
        return False
    return not any(settings.BACKUP_DIR.glob(f"db-{local:%Y-%m-%d}-*.sqlite3"))
