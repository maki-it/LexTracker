from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tracking.models import TimeEntry
from tracking.services import start_timer, stop_timer

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_starting_a_timer_stops_the_running_one(user, task):
    first = start_timer(user, task)
    TimeEntry.objects.filter(pk=first.pk).update(started_at=timezone.now() - timedelta(minutes=10))

    second = start_timer(user, task)

    first.refresh_from_db()
    assert first.ended_at is not None
    assert second.is_running


def test_very_short_timer_is_discarded(user, task):
    start_timer(user, task)

    assert stop_timer(user) is None
    assert not TimeEntry.objects.exists()


def test_timer_start_and_stop_via_htmx(logged_in, user, task):
    response = logged_in.post(reverse("tracking:timer_start"), {"task": task.pk}, headers={"HX-Request": "true"})
    assert response["HX-Trigger"] == "timer-changed"
    assert "Entwicklung" in response.text

    TimeEntry.objects.update(started_at=timezone.now() - timedelta(minutes=5))
    logged_in.post(reverse("tracking:timer_stop"), headers={"HX-Request": "true"})

    entry = TimeEntry.objects.get()
    assert entry.ended_at is not None


def test_create_entry_manually(logged_in, user, task):
    response = logged_in.post(
        reverse("tracking:create"),
        {
            "task": task.pk,
            "started_at": "2026-10-20T09:00",
            "ended_at": "2026-10-20T11:30",
            "description": "Workshop",
            "is_billable": "on",
        },
    )

    entry = TimeEntry.objects.get()
    assert response.url == reverse("tracking:list") + "?week=2026-W43"
    assert entry.duration == timedelta(hours=2, minutes=30)
    assert entry.user == user


def test_entry_must_end_after_start(logged_in, task):
    response = logged_in.post(
        reverse("tracking:create"),
        {"task": task.pk, "started_at": "2026-10-20T11:00", "ended_at": "2026-10-20T10:00"},
    )

    assert "Das Ende muss nach dem Beginn liegen." in response.text
    assert not TimeEntry.objects.exists()


def test_week_view_groups_entries_and_sums(logged_in, user, task):
    for day, hours in [("2026-10-19", 2), ("2026-10-19", 1), ("2026-10-21", 4)]:
        logged_in.post(
            reverse("tracking:create"),
            {
                "task": task.pk,
                "started_at": f"{day}T08:00",
                "ended_at": f"{day}T{8 + hours:02d}:00",
                "is_billable": "on",
            },
        )

    response = logged_in.get(reverse("tracking:list"), {"week": "2026-W43"})

    assert "7:00 h" in response.text  # week
    assert "3:00 h" in response.text  # Monday
    assert "Montag" in response.text


def test_cannot_edit_other_users_entries(logged_in, task):
    other = User.objects.create_user(username="andere", password="x")
    start = timezone.now() - timedelta(hours=1)
    entry = TimeEntry.objects.create(user=other, task=task, started_at=start, ended_at=start + timedelta(minutes=30))

    assert logged_in.get(reverse("tracking:edit", args=[entry.pk])).status_code == 404
    assert logged_in.post(reverse("tracking:delete", args=[entry.pk])).status_code == 404
