from dataclasses import replace
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from core import jobs, scheduler
from core.jobs_overview import next_sync
from core.models import AppSettings, JobStatus
from core.scheduler import in_window, is_due, run_due_jobs
from lexware.client import LexwareError


def local(hour: int, minute: int = 0, day: int = 22) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.get_current_timezone())


def test_in_window():
    assert in_window(time(3), None, None)
    assert in_window(time(7), time(7), time(19))
    assert not in_window(time(19), time(7), time(19))
    assert not in_window(time(6, 59), time(7), None)
    assert in_window(time(23), time(7), None)
    assert in_window(time(6), None, time(7))
    # Over midnight.
    assert in_window(time(23), time(22), time(6))
    assert in_window(time(2), time(22), time(6))
    assert not in_window(time(12), time(22), time(6))


def test_is_due_interval_and_window():
    assert not is_due(local(12), 0, None, None, None)
    assert is_due(local(12), 60, None, None, None)
    assert not is_due(local(12), 60, None, None, local(11, 30))
    assert is_due(local(12), 60, None, None, local(11))
    # Outside the window nothing runs, however long ago the last run was.
    assert not is_due(local(20), 60, time(7), time(19), local(8))


def test_daily_job_runs_once_from_its_start_time():
    start = time(6)
    assert not is_due(local(5, 59), 1440, start, None, local(6, 0, day=21))
    assert is_due(local(6, 0), 1440, start, None, local(6, 1, day=21))  # one check of slack
    assert not is_due(local(12), 1440, start, None, local(6, 1))
    # Missed the morning (e.g. the server was down): runs as soon as it can that day.
    assert is_due(local(15), 1440, start, None, local(6, 0, day=20))


@pytest.mark.django_db(transaction=True)
async def test_jobs_have_their_own_schedule(monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"
    calls = []

    def recorder(name):
        async def run():
            calls.append(name)
            return SimpleNamespace(summary="ok")

        return run

    monkeypatch.setattr(scheduler, "JOBS", [replace(job, run=recorder(job.name)) for job in scheduler.JOBS])
    await AppSettings.aload()
    await AppSettings.objects.filter(pk=1).aupdate(
        lexware_sync_interval=AppSettings.SyncInterval.OFF,
        invoice_sync_interval=AppSettings.SyncInterval.HOUR,
        invoice_sync_from=time(8),
        invoice_sync_until=time(18),
    )

    assert await run_due_jobs(local(7)) == []
    assert await run_due_jobs(local(9)) == ["invoice sync"]
    assert calls == ["invoice sync"]


@pytest.mark.django_db(transaction=True)
async def test_nothing_runs_without_api_key(settings):
    settings.LEXWARE_API_KEY = ""
    assert await run_due_jobs(timezone.now() + timedelta(days=1)) == []


@pytest.mark.django_db(transaction=True)
async def test_tracked_notes_runs_failures_and_recovery():
    async with jobs.tracked("demo") as run:
        run.result = "3 Kunden"
    status = await JobStatus.objects.aget(key="demo")
    assert (status.last_ok, status.last_result, status.failures) == (True, "3 Kunden", 0)
    assert status.last_success_at == status.last_run_at

    for _ in range(2):
        with pytest.raises(ValueError):
            async with jobs.tracked("demo"):
                raise ValueError("kaputt")
    status = await JobStatus.objects.aget(key="demo")
    assert (status.last_ok, status.failures, status.last_error) == (False, 2, "ValueError: kaputt")
    assert status.last_success_at is not None

    # Nothing to do after a failure still counts: the job works again.
    async with jobs.tracked("demo") as run:
        run.idle = True
    status = await JobStatus.objects.aget(key="demo")
    assert (status.last_ok, status.failures, status.last_error) == (True, 0, "ValueError: kaputt")


@pytest.mark.django_db(transaction=True)
async def test_idle_checks_leave_no_trace():
    async with jobs.tracked("quiet") as run:
        run.idle = True
    assert not await JobStatus.objects.filter(key="quiet").aexists()


@pytest.mark.django_db(transaction=True)
async def test_run_due_jobs_notes_each_job(monkeypatch, settings):
    settings.LEXWARE_API_KEY = "test-key"

    async def good():
        return SimpleNamespace(summary="5 Kunden")

    async def bad():
        raise LexwareError("Lexware nicht erreichbar")

    monkeypatch.setattr(
        scheduler,
        "JOBS",
        [replace(scheduler.JOBS[0], run=good), replace(scheduler.JOBS[1], run=bad)],
    )
    await AppSettings.aload()
    await AppSettings.objects.filter(pk=1).aupdate(
        lexware_sync_interval=AppSettings.SyncInterval.HOUR, invoice_sync_interval=AppSettings.SyncInterval.HOUR
    )

    await run_due_jobs(local(9))

    customers = await JobStatus.objects.aget(key="customers")
    invoices = await JobStatus.objects.aget(key="invoices")
    assert (customers.last_ok, customers.last_result) == (True, "5 Kunden")
    assert (invoices.last_ok, invoices.last_error) == (False, "LexwareError: Lexware nicht erreichbar")


@pytest.mark.django_db(transaction=True)
async def test_heartbeat():
    await jobs.beat(local(9), started=True)
    await jobs.beat(local(9, 1))
    app_settings = await AppSettings.aload()
    assert app_settings.scheduler_started_at == local(9)
    assert app_settings.scheduler_seen_at == local(9, 1)
    assert jobs.is_alive(app_settings, local(9, 4)) is True
    assert jobs.is_alive(app_settings, local(9, 7)) is False
    assert jobs.is_alive(AppSettings(), local(9)) is None


def test_next_sync():
    hour = 60
    # Never ran: right away inside the window, at its start outside.
    assert next_sync(local(9), hour, time(8), time(18), None) == local(9)
    assert next_sync(local(6), hour, time(8), time(18), None) == local(8)
    assert next_sync(local(20), hour, time(8), time(18), None) == local(8, day=23)
    # Inside: an interval after the last run, less one check of slack.
    assert next_sync(local(9, 10), hour, None, None, local(9)) == local(9, 59)
    # Overdue: at the next check.
    assert next_sync(local(12), hour, None, None, local(9)) == local(12)
    # The interval ends in the evening: the next morning.
    assert next_sync(local(17, 30), hour, time(8), time(18), local(17, 20)) == local(8, day=23)
    # A window over midnight.
    assert next_sync(local(12), hour, time(22), time(6), None) == local(22)
    assert next_sync(local(12), 0, None, None, None) is None
