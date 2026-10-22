import sqlite3
from datetime import datetime, time

import pytest
from django.core.management import call_command
from django.utils import timezone

from core import backup
from customers.models import Customer

# Outside a test transaction: the in-memory test database cannot be copied while one is open.
pytestmark = pytest.mark.django_db(transaction=True)


def local(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=timezone.get_current_timezone())


@pytest.fixture(autouse=True)
def backup_settings(tmp_path, settings):
    settings.BACKUP_DIR = tmp_path / "backups"
    settings.BACKUP_KEEP = 2
    settings.BACKUP_TIME = time(3)


def test_backup_copies_the_database_and_keeps_the_newest(settings):
    Customer.objects.create(name="ACME GmbH")
    first = backup.create_backup(local(20, 3))
    with sqlite3.connect(first) as db:
        assert db.execute("select name from customers_customer").fetchall() == [("ACME GmbH",)]

    backup.create_backup(local(21, 3))
    newest = backup.create_backup(local(22, 3))
    assert sorted(p.name for p in settings.BACKUP_DIR.iterdir()) == ["db-2026-10-21-030000.sqlite3", newest.name]


def test_backup_is_due_once_a_day_from_its_time(settings):
    assert not backup.is_due(local(22, 2))
    assert backup.is_due(local(22, 3))
    backup.create_backup(local(22, 3))
    assert not backup.is_due(local(22, 23))
    assert backup.is_due(local(23, 4))

    settings.BACKUP_KEEP = 0
    assert not backup.is_due(local(23, 4))


def test_backup_command(settings, capsys):
    call_command("backup_database")
    assert "Backup written" in capsys.readouterr().out
    assert len(list(settings.BACKUP_DIR.glob("db-*.sqlite3"))) == 1
