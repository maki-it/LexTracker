import sqlite3
from datetime import datetime, time

import pytest
from django.core.management import call_command
from django.utils import timezone

from core import backup, scheduler
from core.models import AppSettings
from customers.models import Customer

# Outside a test transaction: the in-memory test database cannot be copied while one is open.
pytestmark = pytest.mark.django_db(transaction=True)


def local(day: int, hour: int) -> datetime:
    return datetime(2026, 10, day, hour, tzinfo=timezone.get_current_timezone())


@pytest.fixture(autouse=True)
def backup_dir(tmp_path, settings):
    settings.BACKUP_DIR = tmp_path / "backups"


def test_backup_copies_the_database_and_keeps_the_newest(settings):
    Customer.objects.create(name="ACME GmbH")
    first = backup.create_backup(2, local(20, 3))
    with sqlite3.connect(first) as db:
        assert db.execute("select name from customers_customer").fetchall() == [("ACME GmbH",)]

    backup.create_backup(2, local(21, 3))
    newest = backup.create_backup(2, local(22, 3))
    assert sorted(p.name for p in settings.BACKUP_DIR.iterdir()) == ["db-2026-10-21-030000.sqlite3", newest.name]


def test_backup_is_due_once_a_day_from_its_time():
    app_settings = AppSettings.load()
    app_settings.backup_time = time(3)
    assert not backup.is_due(local(22, 2), app_settings)
    assert backup.is_due(local(22, 3), app_settings)
    backup.create_backup(2, local(22, 3))
    assert not backup.is_due(local(22, 23), app_settings)
    assert backup.is_due(local(23, 4), app_settings)

    app_settings.backup_time = time(5)
    assert not backup.is_due(local(23, 4), app_settings)
    app_settings.backup_enabled = False
    assert not backup.is_due(local(23, 6), app_settings)


async def test_scheduler_reads_the_backup_settings_from_the_database(settings):
    await AppSettings.aload()
    await AppSettings.objects.filter(pk=1).aupdate(backup_enabled=False)

    # One pass of the loop: with backups off nothing is written.
    stop = scheduler.asyncio.Event()
    scheduler.asyncio.get_running_loop().call_soon(stop.set)
    await scheduler.run(stop)
    assert not settings.BACKUP_DIR.exists()

    await AppSettings.objects.filter(pk=1).aupdate(backup_enabled=True, backup_time=time(0), backup_keep=1)
    stop = scheduler.asyncio.Event()
    scheduler.asyncio.get_running_loop().call_soon(stop.set)
    await scheduler.run(stop)
    assert len(backup.backups()) == 1
    app_settings = await AppSettings.aload()
    assert app_settings.backup_at and not app_settings.backup_failed
    assert app_settings.backup_status == backup.backups()[0].name


def test_failed_backup_is_recorded(settings, monkeypatch):
    def broken(keep, now=None):
        raise OSError("Read-only file system")

    monkeypatch.setattr(backup, "create_backup", broken)
    with pytest.raises(OSError):
        backup.backup_and_record()
    app_settings = AppSettings.load()
    assert app_settings.backup_failed
    assert "Read-only file system" in app_settings.backup_status


def test_backup_command_keeps_the_configured_number(settings, capsys):
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(backup_keep=1)
    backup.create_backup(5, local(20, 3))
    call_command("backup_database")
    assert "Backup written" in capsys.readouterr().out
    assert len(backup.backups()) == 1


def test_settings_page_saves_the_backup_settings(client, settings, user):
    client.force_login(user)
    page = client.get("/einstellungen/")
    assert "Datensicherung" in page.content.decode()
    assert str(settings.BACKUP_DIR) in page.content.decode()

    data = {
        "time_rounding": 0,
        "login_max_attempts": 5,
        "login_lockout_minutes": 15,
        "lexware_sync_interval": 60,
        "invoice_sync_interval": 60,
        "backup_time": "04:30",
        "backup_keep": 7,
    }
    assert client.post("/einstellungen/", data).status_code == 302
    app_settings = AppSettings.load()
    assert (app_settings.backup_enabled, app_settings.backup_time, app_settings.backup_keep) == (False, time(4, 30), 7)

    assert client.post("/einstellungen/", data | {"backup_keep": 0}).status_code == 200
