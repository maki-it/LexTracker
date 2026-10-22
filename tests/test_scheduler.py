from dataclasses import replace
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from core import scheduler
from core.models import AppSettings
from core.scheduler import in_window, is_due, run_due_jobs


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


async def test_nothing_runs_without_api_key(settings):
    settings.LEXWARE_API_KEY = ""
    assert await run_due_jobs(timezone.now() + timedelta(days=1)) == []
