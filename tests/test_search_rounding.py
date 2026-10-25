import uuid
from datetime import datetime, timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models import AppSettings
from core.templatetags.timefmt import hours
from customers.models import Category, Customer
from customers.sync import sync_customers
from projects.models import Project, Task
from tests.lexware_fakes import contact, fake_client, page, serve_pages
from tracking.models import TimeEntry
from tracking.services import round_to_step, rounded_times, stop_timer

pytestmark = pytest.mark.django_db

TZ = timezone.get_current_timezone()


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


# Rounding


def test_round_to_step_rounds_to_the_nearest_step():
    day = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)
    assert round_to_step(day.replace(minute=7), 15) == day
    assert round_to_step(day.replace(minute=8), 15) == day.replace(minute=15)
    assert round_to_step(day.replace(minute=7, second=30), 15) == day.replace(minute=15)
    assert round_to_step(day.replace(minute=32), 5) == day.replace(minute=30)
    assert round_to_step(day.replace(hour=23, minute=55), 15) == day.replace(hour=0) + timedelta(days=1)
    assert round_to_step(day.replace(minute=7), 0) == day.replace(minute=7)


def test_rounded_times_keeps_at_least_one_step():
    day = datetime(2026, 10, 22, 9, 0, tzinfo=TZ)
    assert rounded_times(day.replace(minute=3), day.replace(minute=6), 15) == (day, day.replace(minute=15))
    assert rounded_times(day.replace(minute=8), day.replace(hour=10, minute=53), 15) == (
        day.replace(minute=15),
        day.replace(hour=11),
    )


def test_stopping_timer_rounds_start_and_end(user, task):
    AppSettings.objects.create(pk=1, time_rounding=15)
    started = timezone.now() - timedelta(minutes=50)
    TimeEntry.objects.create(user=user, task=task, started_at=started)

    entry = stop_timer(user)

    assert entry.started_at == round_to_step(started, 15)
    assert timezone.localtime(entry.started_at).minute % 15 == 0
    assert timezone.localtime(entry.ended_at).minute % 15 == 0
    assert entry.duration.total_seconds() % (15 * 60) == 0


def test_manual_entry_is_rounded(logged_in, user, task):
    AppSettings.objects.create(pk=1, time_rounding=15)
    logged_in.post(
        reverse("tracking:create"),
        {"task": task.pk, "started_at": "2026-10-20T09:08", "ended_at": "2026-10-20T11:37", "is_billable": "on"},
    )
    entry = TimeEntry.objects.get()
    assert timezone.localtime(entry.started_at).time() == datetime(2026, 1, 1, 9, 15).time()
    assert timezone.localtime(entry.ended_at).time() == datetime(2026, 1, 1, 11, 30).time()
    assert entry.duration == timedelta(hours=2, minutes=15)


def test_time_fields_step_and_snap_by_the_rounding(logged_in, user, task):
    AppSettings.objects.create(pk=1, time_rounding=15)
    start = datetime(2026, 10, 20, 8, 31, tzinfo=TZ)
    entry = TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=58))

    page_text = logged_in.get(reverse("tracking:edit", args=[entry.pk])).text

    assert 'type="datetime-local"' in page_text
    assert 'step="900"' in page_text
    assert page_text.count('data-snap-minutes="15"') == 2
    assert 'value="2026-10-20T08:30"' in page_text
    assert 'value="2026-10-20T09:30"' in page_text


def test_time_fields_are_free_without_rounding(logged_in, user, task):
    page_text = logged_in.get(reverse("tracking:create")).text

    assert "data-snap-minutes" not in page_text


def test_time_fields_have_a_now_button_that_does_not_submit(logged_in, user, task):
    page_text = logged_in.get(reverse("tracking:create")).text

    for name in ("started_at", "ended_at"):
        assert f'data-now-for="id_{name}"' in page_text
        assert f'<input type="datetime-local" name="{name}"' in page_text
    assert page_text.count('type="button" class="btn" data-now-for') == 2
    assert 'aria-label="Beginn auf jetzt setzen"' in page_text
    assert 'aria-label="Ende auf jetzt setzen"' in page_text


def test_hours_filter_formats():
    assert hours(timedelta(hours=2, minutes=45)) == "2:45"
    assert hours(timedelta(hours=2, minutes=45), "decimal") == "2,75"
    assert hours(timedelta(minutes=20), "decimal") == "0,33"
    assert hours(None, "decimal") == "0,00"


def test_decimal_hours_preference_is_used(logged_in, user, task):
    user.duration_format = user.DurationFormat.DECIMAL
    user.save()
    start = datetime(2026, 10, 20, 9, 0, tzinfo=TZ)
    TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(hours=2, minutes=45))

    response = logged_in.get(reverse("tracking:list"), {"week": "2026-W43"})

    assert "2,75" in response.text


# Lexware: deleted contacts


@pytest.mark.django_db(transaction=True)
async def test_contacts_missing_from_lexware_are_archived_and_restored():
    gone = await Customer.objects.acreate(name="Weg GmbH", lexware_id=uuid.uuid4(), lexware_version=1)
    kept = contact("Bleibt GmbH")

    result = await sync_customers(fake_client(serve_pages(page([kept]))))

    assert result.removed == 1
    await gone.arefresh_from_db()
    assert gone.lexware_deleted and gone.is_archived

    back = contact("Weg GmbH", id=gone.lexware_id)
    await sync_customers(fake_client(serve_pages(page([kept, back]))))
    await gone.arefresh_from_db()
    assert not gone.lexware_deleted and not gone.is_archived


# Search and categories


def test_customer_search_and_category_filter(logged_in):
    hosting = Category.objects.create(name="Hosting")
    acme = Customer.objects.create(name="ACME GmbH", email="info@acme.de")
    acme.categories.add(hosting)
    Customer.objects.create(name="Muster AG")

    page_text = logged_in.get(reverse("customers:list"), {"q": "acme"}).text
    assert "ACME GmbH" in page_text and "Muster AG" not in page_text

    page_text = logged_in.get(reverse("customers:list"), {"category": hosting.pk}).text
    assert "ACME GmbH" in page_text and "Muster AG" not in page_text


def test_customer_form_creates_and_cleans_up_categories(logged_in):
    customer = Customer.objects.create(name="ACME GmbH")
    data = {"name": "ACME GmbH", "email": "", "phone": "", "default_hourly_rate": "", "notes": ""}

    logged_in.post(reverse("customers:edit", args=[customer.pk]), {**data, "new_categories": "Hosting, Stammkunde"})
    assert sorted(customer.categories.values_list("name", flat=True)) == ["Hosting", "Stammkunde"]

    hosting = Category.objects.get(name="Hosting")
    logged_in.post(reverse("customers:edit", args=[customer.pk]), {**data, "categories": [hosting.pk]})
    assert list(Category.objects.values_list("name", flat=True)) == ["Hosting"]


def test_project_search(logged_in, task):
    Project.objects.create(customer=task.project.customer, name="Intranet")

    page_text = logged_in.get(reverse("projects:list"), {"q": "intra"}).text

    assert "Intranet" in page_text
    assert ">Website<" not in page_text


# Tasks


def test_edit_task(logged_in, task):
    url = reverse("projects:task_edit", args=[task.project.pk, task.pk])
    response = logged_in.post(
        url, {"name": "Umsetzung", "status": "in_progress", "description": "", "hourly_rate": "90", "is_billable": "on"}
    )
    assert response.status_code == 302
    task.refresh_from_db()
    assert task.name == "Umsetzung"
    assert task.status == Task.Status.IN_PROGRESS


def test_delete_task_only_without_time(logged_in, user, task):
    url = reverse("projects:task_delete", args=[task.project.pk, task.pk])
    start = timezone.now() - timedelta(hours=1)
    TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=30))

    logged_in.post(url)
    assert Task.objects.filter(pk=task.pk).exists()

    TimeEntry.objects.all().delete()
    logged_in.post(url)
    assert not Task.objects.filter(pk=task.pk).exists()
