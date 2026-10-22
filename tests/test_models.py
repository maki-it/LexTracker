from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError
from django.utils import timezone

from accounts.models import User
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def test_hourly_rate_falls_back_from_task_to_project_to_customer(task):
    task.project.customer.default_hourly_rate = Decimal("90.00")
    assert task.effective_hourly_rate == Decimal("90.00")

    task.project.hourly_rate = Decimal("100.00")
    assert task.effective_hourly_rate == Decimal("100.00")

    task.hourly_rate = Decimal("0.00")
    assert task.effective_hourly_rate == Decimal("0.00")


def test_only_one_running_timer_per_user(user, task):
    TimeEntry.objects.create(user=user, task=task)
    with pytest.raises(IntegrityError):
        TimeEntry.objects.create(user=user, task=task)


def test_time_entry_must_end_after_start(user, task):
    now = timezone.now()
    with pytest.raises(IntegrityError):
        TimeEntry.objects.create(user=user, task=task, started_at=now, ended_at=now - timedelta(minutes=1))


def test_duration_of_finished_entry(user, task):
    start = timezone.now() - timedelta(hours=2)
    entry = TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=90))
    assert entry.duration == timedelta(minutes=90)
    assert not entry.is_running


def test_customer_login_needs_customer():
    with pytest.raises(IntegrityError):
        User.objects.create_user(username="kunde", password="x", role=User.Role.CUSTOMER)
