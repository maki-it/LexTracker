import sqlite3
from contextlib import closing
from datetime import datetime, time

import pytest
from asgiref.sync import sync_to_async
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone

from core import backup, scheduler
from core.models import AppSettings
from core.upload_limit import FORM_OVERHEAD, LimitBackupUpload
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
        "weekly_report_weekday": 0,
        "weekly_report_time": "07:00",
        "timer_reminder_hours": 10,
        "overdue_notice": "admins",
        "overdue_notice_days": 3,
    }
    assert client.post("/einstellungen/", data).status_code == 302
    app_settings = AppSettings.load()
    assert (app_settings.backup_enabled, app_settings.backup_time, app_settings.backup_keep) == (False, time(4, 30), 7)

    assert client.post("/einstellungen/", data | {"backup_keep": 0}).status_code == 200


def test_copy_made_before_a_restore_does_not_count_as_the_daily_backup():
    app_settings = AppSettings.load()
    backup._copy(local(22, 4), backup.BEFORE_RESTORE)
    assert backup.is_due(local(22, 5), app_settings)
    assert [b.before_restore for b in backup.listing()] == [True]


@pytest.fixture
def admin(client, user):
    client.force_login(user)
    return client


def test_backup_page_lists_downloads_and_deletes(admin):
    admin.post("/einstellungen/sicherungen/neu/")
    [item] = backup.listing()
    page = admin.get("/einstellungen/sicherungen/")
    assert item.name in page.text

    assert admin.post(f"/einstellungen/sicherungen/{item.name}/loeschen/").status_code == 302
    assert backup.listing() == []


async def test_backup_download(async_client, user):
    await async_client.aforce_login(user)
    path = await sync_to_async(backup.create_backup)(5)
    download = await async_client.get(f"/einstellungen/sicherungen/{path.name}/")
    assert download["Content-Disposition"] == f'attachment; filename="{path.name}"'
    assert b"".join([chunk async for chunk in download.streaming_content]) == path.read_bytes()


def test_only_backups_from_the_folder_can_be_reached(admin, settings):
    settings.BACKUP_DIR.mkdir(parents=True)
    assert admin.get("/einstellungen/sicherungen/db.sqlite3/").status_code == 404
    assert admin.get("/einstellungen/sicherungen/..%2Fdb.sqlite3/").status_code == 404
    assert admin.post("/einstellungen/sicherungen/db-2026-10-22-030000.sqlite3/loeschen/").status_code == 404


def test_restore_replaces_the_data_and_keeps_the_previous_state(admin):
    Customer.objects.create(name="ACME GmbH")
    saved = backup.create_backup(5, local(20, 3))
    Customer.objects.create(name="Neu AG")
    url = f"/einstellungen/sicherungen/{saved.name}/wiederherstellen/"

    unconfirmed = admin.post(url)
    assert "Bitte bestätige" in unconfirmed.text
    assert Customer.objects.count() == 2

    assert admin.post(url, {"bestaetigt": "1"}).status_code == 302
    assert list(Customer.objects.values_list("name", flat=True)) == ["ACME GmbH"]
    [before] = [b for b in backup.listing() if b.before_restore]
    with sqlite3.connect(before.path) as db:
        assert db.execute("select count(*) from customers_customer").fetchone() == (2,)
    # Still signed in, since the account exists in the backup.
    assert admin.get("/einstellungen/sicherungen/").status_code == 200


def test_restore_refuses_files_that_are_not_a_lextracker_database(admin, settings):
    settings.BACKUP_DIR.mkdir(parents=True)
    garbage = settings.BACKUP_DIR / "db-2026-10-20-030000.sqlite3"
    garbage.write_bytes(b"not a database" * 100)
    foreign = settings.BACKUP_DIR / "db-2026-10-21-030000.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("create table other (x)")
    Customer.objects.create(name="ACME GmbH")

    for path in (garbage, foreign):
        response = admin.post(f"/einstellungen/sicherungen/{path.name}/wiederherstellen/", {"bestaetigt": "1"})
        assert response.status_code == 200
        assert 'role="alert"' in response.text
    assert Customer.objects.count() == 1
    assert not any(b.before_restore for b in backup.listing())


def test_backups_are_for_admins_only(client, user):
    user.role = user.Role.EMPLOYEE
    user.save()
    client.force_login(user)
    assert client.get("/einstellungen/sicherungen/").status_code == 403
    assert client.post("/einstellungen/sicherungen/neu/").status_code == 403


def upload(admin, content: bytes, name: str = "db.sqlite3"):
    return admin.post("/einstellungen/sicherungen/hochladen/", {"datei": SimpleUploadedFile(name, content)})


def test_upload_stores_a_backup_from_elsewhere_and_it_can_be_restored(admin):
    Customer.objects.create(name="ACME GmbH")
    exported = backup.create_backup(5, local(20, 3))
    content = exported.read_bytes()
    exported.unlink()
    Customer.objects.create(name="Neu AG")

    response = upload(admin, content)
    assert response.status_code == 302
    [item] = backup.listing()
    assert item.uploaded and not item.before_restore
    assert item.name.endswith("-hochgeladen.sqlite3")
    assert "Hochgeladen" in admin.get("/einstellungen/sicherungen/").text
    # Uploading does not touch the data yet.
    assert Customer.objects.count() == 2

    admin.post(f"/einstellungen/sicherungen/{item.name}/wiederherstellen/", {"bestaetigt": "1"})
    assert list(Customer.objects.values_list("name", flat=True)) == ["ACME GmbH"]


def test_upload_accepts_a_database_in_wal_mode(admin, tmp_path):
    exported = backup.create_backup(5, local(20, 3))
    copy = tmp_path / "db.sqlite3"
    copy.write_bytes(exported.read_bytes())
    exported.unlink()
    with closing(sqlite3.connect(copy)) as db:
        db.execute("PRAGMA journal_mode=WAL")

    assert upload(admin, copy.read_bytes()).status_code == 302
    [item] = backup.listing()
    with closing(sqlite3.connect(item.path)) as db:
        assert db.execute("PRAGMA journal_mode").fetchone() == ("delete",)
    assert sorted(p.name for p in item.path.parent.iterdir()) == [item.name]


def foreign_database(tmp_path) -> bytes:
    path = tmp_path / "other.sqlite3"
    with closing(sqlite3.connect(path)) as db:
        db.execute("create table other (x)")
        db.commit()
    return path.read_bytes()


def newer_database(tmp_path) -> bytes:
    path = backup.create_backup(5, local(20, 3))
    with closing(sqlite3.connect(path)) as db:
        db.execute("insert into django_migrations (app, name, applied) values ('core', '9999_future', '2030-01-01')")
        db.commit()
    content = path.read_bytes()
    path.unlink()
    return content


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (lambda tmp_path: b"not a database" * 100, "Keine lesbare Datenbank"),
        (foreign_database, "keine Datenbank von LexTracker"),
        (newer_database, "neueren Version"),
    ],
)
def test_upload_refuses_files_it_could_not_restore(admin, settings, tmp_path, make, message):
    response = upload(admin, make(tmp_path))
    assert response.status_code == 200
    assert message in response.text
    # Nothing is left in the folder, not even a partial file.
    assert list(settings.BACKUP_DIR.iterdir()) == []


def test_upload_refuses_large_files_and_missing_ones(admin, settings):
    settings.BACKUP_UPLOAD_MAX_SIZE = 10
    assert "größer als" in upload(admin, b"x" * 11).text
    assert "Bitte wähle" in admin.post("/einstellungen/sicherungen/hochladen/").text
    assert not settings.BACKUP_DIR.exists() or list(settings.BACKUP_DIR.iterdir()) == []


def test_upload_name_cannot_choose_the_target(admin, settings):
    content = backup.create_backup(5, local(20, 3)).read_bytes()
    for path in settings.BACKUP_DIR.iterdir():
        path.unlink()
    assert upload(admin, content, name="../../evil.sqlite3").status_code == 302
    [path] = settings.BACKUP_DIR.iterdir()
    assert backup.NAME.fullmatch(path.name)


def test_upload_is_for_admins_only(client, user):
    user.role = user.Role.EMPLOYEE
    user.save()
    client.force_login(user)
    assert client.get("/einstellungen/sicherungen/hochladen/").status_code == 403
    assert upload(client, b"x").status_code == 403


async def call_limited(path: str, headers: list) -> tuple[list, bool]:
    reached = []

    async def app(scope, receive, send):
        reached.append(scope)

    sent = []

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "POST", "path": path, "headers": headers}
    await LimitBackupUpload(app)(scope, None, send)
    return [m.get("status") for m in sent if m["type"] == "http.response.start"], bool(reached)


async def test_oversized_uploads_are_refused_before_django_reads_them(settings):
    settings.BACKUP_UPLOAD_MAX_SIZE = 1000
    url = "/einstellungen/sicherungen/hochladen/"
    small = str(1000 + FORM_OVERHEAD).encode()
    big = str(1001 + FORM_OVERHEAD).encode()
    assert await call_limited(url, [(b"content-length", small)]) == ([], True)
    assert await call_limited(url, [(b"content-length", big)]) == ([413], False)
    assert await call_limited(url, []) == ([413], False)
    # Other pages are not affected.
    assert await call_limited("/kunden/", [(b"content-length", big)]) == ([], True)


def test_settings_page_highlights_the_backup_count_and_newest_copy(client, settings, user, tmp_path):
    settings.BACKUP_DIR = tmp_path
    client.force_login(user)
    html = client.get("/einstellungen/").content.decode()
    assert "Noch keine Kopie vorhanden" in html
    assert 'href="/einstellungen/sicherungen/" class="btn btn-primary"' in html

    (tmp_path / "db-2026-10-01-030000.sqlite3").write_bytes(b"x")
    (tmp_path / "db-2026-10-02-030000.sqlite3").write_bytes(b"x")
    html = client.get("/einstellungen/").content.decode()
    assert "2 Kopien vorhanden" in html
    assert "Letzte Sicherung: 02.10.2026" in html


def test_settings_page_shows_one_tab_and_keeps_it_after_saving(client, user):
    client.force_login(user)
    html = client.get("/einstellungen/", {"tab": "sicherheit"}).content.decode()
    assert 'href="?tab=sicherheit" class="tab tab-active"' in html
    # The other tabs stay in the form (so one save posts everything) and are only hidden.
    assert "backup_keep" in html
    assert 'id="e-mail" hidden>' in html

    data = {
        "tab": "datensicherung",
        "time_rounding": 0,
        "login_max_attempts": 5,
        "login_lockout_minutes": 15,
        "lexware_sync_interval": 60,
        "invoice_sync_interval": 60,
        "backup_time": "04:30",
        "backup_keep": 7,
        "weekly_report_weekday": 0,
        "weekly_report_time": "07:00",
        "timer_reminder_hours": 10,
        "overdue_notice": "admins",
        "overdue_notice_days": 3,
    }
    assert client.post("/einstellungen/", data)["Location"] == "/einstellungen/?tab=datensicherung"
    page = client.post("/einstellungen/", data | {"tab": "allgemein", "backup_keep": 0})
    assert page.status_code == 200
    assert 'href="?tab=datensicherung" class="tab tab-active"' in page.content.decode()


def test_backup_before_upgrade_is_read_while_a_migration_holds_the_write_lock(tmp_path):
    live = tmp_path / "live.sqlite3"
    with closing(sqlite3.connect(live)) as setup:
        setup.execute("PRAGMA journal_mode=WAL")
        setup.execute("CREATE TABLE django_migrations (app TEXT, name TEXT)")
        setup.execute("INSERT INTO django_migrations VALUES ('core', '0001_initial')")
        setup.execute("CREATE TABLE core_appsettings (id INTEGER)")
        setup.commit()
    # What a migration does: write inside an open transaction. The copy must not wait for it.
    migrating = sqlite3.connect(live, isolation_level=None)
    migrating.execute("BEGIN IMMEDIATE")
    migrating.execute("INSERT INTO django_migrations VALUES ('core', '0099_in_progress')")
    try:
        copy = backup.backup_before_upgrade(local(23, 12), database=live)
    finally:
        migrating.close()

    assert copy.name == "db-2026-10-23-120000-vor-umstellung.sqlite3"
    with closing(sqlite3.connect(copy)) as db:
        assert db.execute("SELECT name FROM django_migrations").fetchall() == [("0001_initial",)]
    assert [(b.name, b.before_upgrade) for b in backup.listing()] == [(copy.name, True)]
