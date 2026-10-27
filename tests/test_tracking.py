from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from projects.models import Task
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


def test_new_entry_starts_as_a_duration_and_an_existing_one_shows_its_times(logged_in, user, task):
    page_text = logged_in.get(reverse("tracking:create")).text

    assert 'data-mode="duration"' in page_text
    assert 'name="started_at"' in page_text and 'name="ended_at"' in page_text
    assert 'data-mode-button="range"' in page_text
    for chip in ("15 min", "30 min", "1 h", "2 h"):
        assert chip in page_text

    entry = TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=timezone.now() - timedelta(hours=2),
        ended_at=timezone.now() - timedelta(hours=1),
    )
    assert 'data-mode="range"' in logged_in.get(reverse("tracking:edit", args=[entry.pk])).text


def test_entry_that_does_not_validate_shows_its_times(logged_in, task):
    response = logged_in.post(
        reverse("tracking:create"),
        {"task": task.pk, "started_at": "2026-10-20T11:00", "ended_at": "2026-10-20T10:00"},
    )

    assert 'data-mode="range"' in response.text
    assert 'value="2026-10-20T11:00"' in response.text


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


def test_recent_tasks_are_offered_on_the_dashboard_and_in_the_timer_dialog(logged_in, user, task):
    assert "Zuletzt genutzt" not in logged_in.get(reverse("core:dashboard")).text

    TimeEntry.objects.create(user=user, task=task, started_at=timezone.now() - timedelta(hours=2))
    dashboard = logged_in.get(reverse("core:dashboard")).text
    dialog = logged_in.get(reverse("tracking:timer_start"), headers={"HX-Request": "true", "HX-Target": "dialog-body"})

    assert "Zuletzt genutzt" in dashboard
    assert f'name="task" value="{task.pk}"' in dashboard
    # Folded on the dashboard, unfolded in the dialog.
    assert '<details class="recent-tasks group">' in dashboard
    assert '<details class="recent-tasks group" open>' in dialog.text


def test_recent_tasks_are_the_last_four_used_and_start_a_timer(logged_in, user, task):
    customer = task.project.customer
    project = task.project
    tasks = [Task.objects.create(project=project, name=f"Aufgabe {i}") for i in range(5)]
    for i, other in enumerate(tasks):
        TimeEntry.objects.create(
            user=user,
            task=other,
            started_at=timezone.now() - timedelta(days=10 - i),
            ended_at=timezone.now() - timedelta(days=10 - i) + timedelta(hours=1),
        )

    page_text = logged_in.get(reverse("core:dashboard")).text

    assert page_text.count('class="recent-task"') == 4
    assert "Aufgabe 4" in page_text and "Aufgabe 1" in page_text
    assert f'class="truncate text-xs font-normal text-muted">{customer.name} · {project.name}' in page_text
    # The task of the oldest entry is left out.
    assert f'name="task" value="{tasks[0].pk}"' not in page_text


def test_recent_tasks_leave_out_what_the_user_cannot_book(client, user, task):
    other = User.objects.create_user(username="other", password="geheim-123")
    TimeEntry.objects.create(user=other, task=task, started_at=timezone.now() - timedelta(hours=2))
    client.force_login(user)

    assert "Zuletzt genutzt" not in client.get(reverse("core:dashboard")).text
