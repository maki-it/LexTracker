import asyncio
from datetime import datetime, time, timedelta

import pytest
from django.utils import timezone

from accounts.models import User
from core.jobs_overview import next_backup, overview
from core.models import AppSettings, JobStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def employee(db):
    return User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)


def local(hour: int, minute: int = 0, day: int = 22) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.get_current_timezone())


def test_only_admins_see_the_jobs(client, employee):
    client.force_login(employee)
    assert client.get("/einstellungen/aufgaben/").status_code == 403


def test_page_without_scheduler(client, user):
    client.force_login(user)
    page = client.get("/einstellungen/aufgaben/")
    assert page.status_code == 200
    assert "noch nie gemeldet" in page.text
    assert "Kundenimport" in page.text and "noch nicht gelaufen" in page.text
    # A scheduler that never reported is no reason for a warning on the dashboard.
    assert "meldet sich nicht mehr" not in client.get("/").text


def test_page_shows_results_and_errors(client, user):
    now = timezone.now()
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(scheduler_seen_at=now - timedelta(seconds=30), scheduler_started_at=now)
    JobStatus.objects.create(key="customers", last_run_at=now, last_success_at=now, last_result="12 Kunden, 2 neu")
    JobStatus.objects.create(
        key="invoices",
        last_run_at=now,
        last_ok=False,
        failures=3,
        last_error="LexwareError: Zeitüberschreitung",
        last_error_at=now,
    )

    client.force_login(user)
    page = client.get("/einstellungen/aufgaben/")
    assert "läuft" in page.text
    assert "12 Kunden, 2 neu" in page.text
    assert "LexwareError: Zeitüberschreitung" in page.text
    assert "3× in Folge" in page.text


def test_stopped_scheduler_is_flagged(client, user):
    client.force_login(user)
    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(scheduler_seen_at=timezone.now() - timedelta(hours=1))
    assert "meldet sich nicht" in client.get("/einstellungen/aufgaben/").text
    assert "meldet sich nicht mehr" in client.get("/").text


def test_overview_lists_every_job_with_its_schedule():
    app_settings = AppSettings.load()
    app_settings.lexware_sync_interval = 60
    app_settings.lexware_sync_from, app_settings.lexware_sync_until = time(8), time(18)
    app_settings.invoice_sync_interval = 0

    rows = {row.key: row for row in asyncio.run(overview(local(9), app_settings))}

    assert rows["customers"].schedule == "stündlich, 08:00 – 18:00 Uhr"
    assert rows["customers"].next_run == local(9)
    assert rows["invoices"].schedule == "aus" and rows["invoices"].next_run is None
    assert not rows["mail-queue"].scheduled


def test_next_backup(settings, tmp_path):
    settings.BACKUP_DIR = tmp_path
    app_settings = AppSettings.load()
    app_settings.backup_time = time(3)
    assert next_backup(local(1), app_settings) == local(3)
    assert next_backup(local(5), app_settings) == local(5)  # today's is missing: due now
    (tmp_path / "db-2026-10-22-020000.sqlite3").touch()  # a copy from earlier today: the next one is tomorrow's
    assert next_backup(local(1), app_settings) == local(3, day=23)
    app_settings.backup_enabled = False
    assert next_backup(local(1), app_settings) is None
