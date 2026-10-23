"""Copies of the SQLite database, made daily by the scheduler or on demand by ``manage.py backup_database``.

When and how many copies is set on the settings page; the folder is set by APP_BACKUP_DIR, since in
Docker only the mounted /backups is writable.
"""

import sqlite3
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from core.models import AppSettings


def backups() -> list[Path]:
    # The names start with the date and time, so sorting by name sorts by age.
    return sorted(settings.BACKUP_DIR.glob("db-*.sqlite3"))


def create_backup(keep: int, now: datetime | None = None) -> Path:
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
    prune(keep)
    return target


def prune(keep: int) -> list[Path]:
    """Delete all but the newest ``keep`` backups. Returns the deleted files."""
    old = backups()[:-keep] if keep else []
    for path in old:
        path.unlink()
    return old


def is_due(now: datetime, app_settings: AppSettings) -> bool:
    """Whether today's backup is missing and its time has come."""
    if not app_settings.backup_enabled:
        return False
    local = timezone.localtime(now)
    if local.time() < app_settings.backup_time:
        return False
    return not any(settings.BACKUP_DIR.glob(f"db-{local:%Y-%m-%d}-*.sqlite3"))


def backup_and_record(now: datetime | None = None) -> Path:
    """Make a backup with the configured number of copies and note the outcome on the settings page."""
    app_settings = AppSettings.load()
    try:
        path = create_backup(app_settings.backup_keep, now)
    except Exception as exc:
        _record(now, f"{type(exc).__name__}: {exc}"[:500], failed=True)
        raise
    _record(now, path.name, failed=False)
    return path


def _record(now: datetime | None, status: str, failed: bool) -> None:
    # Only these columns, so a settings change saved at the same moment is not overwritten.
    AppSettings.objects.filter(pk=1).update(backup_at=now or timezone.now(), backup_status=status, backup_failed=failed)
