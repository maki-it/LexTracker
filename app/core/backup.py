"""Copies of the SQLite database, made daily by the scheduler or on demand by ``manage.py backup_database``.

When and how many copies is set on the settings page; the folder is set by APP_BACKUP_DIR, since in
Docker only the mounted /backups is writable.
"""

import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone

from core.models import AppSettings

# A copy made just before a restore, so the restore can be undone. Pruned like the daily ones.
BEFORE_RESTORE = "-vorher"
# A copy made by a migration that rewrites the data (see core.migrations.0010), so it can be undone.
BEFORE_UPGRADE = "-vor-umstellung"
# A file uploaded on the backups page, e.g. from another server. Never pruned before it is the oldest.
UPLOADED = "-hochgeladen"
NAME = re.compile(rf"db-(\d{{4}}-\d{{2}}-\d{{2}}-\d{{6}})({BEFORE_RESTORE}|{BEFORE_UPGRADE}|{UPLOADED})?\.sqlite3")


class InvalidBackup(Exception):
    """The file is not a database this app can restore."""


@dataclass(frozen=True)
class Backup:
    path: Path
    created: datetime
    size: int
    before_restore: bool
    before_upgrade: bool
    uploaded: bool

    @property
    def name(self) -> str:
        return self.path.name


def backups() -> list[Path]:
    # The names start with the date and time, so sorting by name sorts by age.
    return sorted(p for p in settings.BACKUP_DIR.glob("db-*.sqlite3") if NAME.fullmatch(p.name))


def listing() -> list[Backup]:
    """The backups in the folder, newest first."""
    result = []
    for path in reversed(backups()):
        match = NAME.fullmatch(path.name)
        created = timezone.make_aware(datetime.strptime(match[1], "%Y-%m-%d-%H%M%S"))
        result.append(
            Backup(
                path,
                created,
                path.stat().st_size,
                match[2] == BEFORE_RESTORE,
                match[2] == BEFORE_UPGRADE,
                match[2] == UPLOADED,
            )
        )
    return result


def get(name: str) -> Path | None:
    """The backup with this file name, or None. Only names from the folder, so no path can escape it."""
    return next((path for path in backups() if path.name == name), None)


def _copy(now: datetime | None, suffix: str = "", source: sqlite3.Connection | None = None) -> Path:
    """Copy the database with SQLite's backup API, which is safe while the app writes to it."""
    local = timezone.localtime(now)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = settings.BACKUP_DIR / f"db-{local:%Y-%m-%d-%H%M%S}{suffix}.sqlite3"
    # Write to a temporary name first, so a half-written copy never looks like a backup.
    partial = target.with_suffix(".partial")
    connection.ensure_connection()
    copy = sqlite3.connect(partial)
    try:
        (source or connection.connection).backup(copy)
        # A single self-contained file, so a downloaded copy opens anywhere.
        copy.execute("PRAGMA journal_mode=DELETE")
    finally:
        copy.close()
    partial.rename(target)
    return target


def backup_before_upgrade(now: datetime | None = None, database: Path | str | None = None) -> Path:
    """The copy a migration makes before it rewrites the data. Pruned later like the daily copies.

    A migration holds a write transaction, and SQLite cannot copy through the connection that holds it (the
    copy waits for a lock the same connection keeps). So the copy is read through a second connection, which
    sees the state before the migration began.
    """
    connection.ensure_connection()
    database = database or connection.settings_dict["NAME"]
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as source:
        return _copy(now, BEFORE_UPGRADE, source)


def create_backup(keep: int, now: datetime | None = None) -> Path:
    target = _copy(now)
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
    # Only the daily copies have no suffix; one made before a restore or uploaded does not count.
    today = settings.BACKUP_DIR.glob(f"db-{local:%Y-%m-%d}-*.sqlite3")
    return not any((match := NAME.fullmatch(path.name)) and not match[2] for path in today)


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


def check(path: Path) -> None:
    """Raise InvalidBackup unless the file is an intact database of this app."""
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise InvalidBackup("Die Datei ist beschädigt.")
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            if not {"django_migrations", "core_appsettings"} <= tables:
                raise InvalidBackup("Die Datei ist keine Datenbank von LexTracker.")
            applied = set(db.execute("SELECT app, name FROM django_migrations"))
    except sqlite3.DatabaseError as exc:
        raise InvalidBackup(f"Keine lesbare Datenbank ({exc}).") from exc
    # A backup from a newer version has tables this code does not know; migrate cannot undo that.
    unknown = applied - set(MigrationLoader(None, ignore_no_migrations=True).disk_migrations)
    if unknown:
        raise InvalidBackup("Die Sicherung stammt aus einer neueren Version der App.")


def save_upload(chunks: Iterable[bytes], now: datetime | None = None) -> Path:
    """Store an uploaded file in the backup folder, if check() accepts it. Returns its path there.

    The name is made here from the time of the upload, so nothing from the upload decides where it lands.
    """
    local = timezone.localtime(now)
    settings.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    target = settings.BACKUP_DIR / f"db-{local:%Y-%m-%d-%H%M%S}{UPLOADED}.sqlite3"
    partial = target.with_suffix(".partial")
    try:
        with partial.open("wb") as file:
            for chunk in chunks:
                file.write(chunk)
        check(partial)
        # A database copied straight from a running server may be in WAL mode; like our own copies it
        # becomes a single self-contained file.
        with closing(sqlite3.connect(partial)) as db:
            db.execute("PRAGMA journal_mode=DELETE")
    except BaseException:
        for leftover in (partial, Path(f"{partial}-wal"), Path(f"{partial}-shm")):
            leftover.unlink(missing_ok=True)
        raise
    partial.rename(target)
    return target


def restore(path: Path, now: datetime | None = None) -> Path:
    """Replace the database's content with the backup. Returns the copy of the state before.

    SQLite's backup API writes into the open database, so the app and the scheduler keep running and
    see the restored data with their next query. Migrations run afterwards, in case the backup is older
    than the code.
    """
    check(path)
    before = _copy(now, BEFORE_RESTORE)
    connection.ensure_connection()
    with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as source:
        source.backup(connection.connection)
    call_command("migrate", interactive=False, verbosity=0)
    return before
