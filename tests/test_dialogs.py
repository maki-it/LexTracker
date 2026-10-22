from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from projects.models import Project
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

DIALOG = {"HX-Request": "true", "HX-Target": "dialog-body", "HX-Current-URL": "http://testserver/zeiten/"}


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def entry(user, task):
    start = timezone.now() - timedelta(hours=2)
    return TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(hours=1))


def test_page_in_dialog_has_no_sidebar(logged_in, entry):
    url = reverse("tracking:edit", args=[entry.pk])

    page = logged_in.get(url).text
    dialog = logged_in.get(url, headers=DIALOG).text

    assert "Hauptnavigation" in page
    assert "Hauptnavigation" not in dialog
    assert "Zeiteintrag bearbeiten" in dialog
    assert f'action="{url}"' in dialog


def test_save_in_dialog_reloads_page_behind(logged_in, entry, task):
    url = reverse("tracking:edit", args=[entry.pk])
    data = {
        "task": task.pk,
        "started_at": "2026-10-20T09:00",
        "ended_at": "2026-10-20T10:30",
        "description": "im Dialog",
        "is_billable": "on",
    }

    response = logged_in.post(url, data, headers=DIALOG)

    assert response.status_code == 200
    assert response["HX-Refresh"] == "true"
    entry.refresh_from_db()
    assert entry.description == "im Dialog"
    # Without the dialog, the usual redirect.
    assert logged_in.post(url, data).status_code == 302


def test_invalid_form_stays_in_dialog(logged_in):
    response = logged_in.post(reverse("projects:create"), {}, headers=DIALOG)

    assert response.status_code == 200
    assert "HX-Refresh" not in response
    assert "Hauptnavigation" not in response.text


def test_new_project_from_dialog_goes_to_its_page(logged_in, task):
    customer = task.project.customer
    response = logged_in.post(
        reverse("projects:create"), {"customer": customer.pk, "name": "Neu", "status": "active"}, headers=DIALOG
    )

    project = Project.objects.get(name="Neu")
    assert response["HX-Redirect"] == reverse("projects:detail", args=[project.pk])


def test_timer_start_form_and_start_from_dialog(logged_in, task):
    url = reverse("tracking:timer_start")
    assert task.name in logged_in.get(url, headers=DIALOG).text

    response = logged_in.post(url, {"task": task.pk}, headers=DIALOG)

    assert "close-dialog" in response["HX-Trigger"]
    assert response["HX-Reswap"] == "none"
    assert TimeEntry.objects.get(ended_at__isnull=True).task == task


def test_project_delete(logged_in, task, user):
    project = task.project
    start = timezone.now() - timedelta(hours=1)
    booked = TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=30))
    url = reverse("projects:delete", args=[project.pk])

    assert "Zeiten gebucht" in logged_in.get(reverse("projects:edit", args=[project.pk])).text
    logged_in.post(url)
    assert Project.objects.filter(pk=project.pk).exists()

    booked.delete()
    assert "Projekt löschen" in logged_in.get(reverse("projects:edit", args=[project.pk])).text
    response = logged_in.post(url, headers=DIALOG)
    assert response["HX-Redirect"] == reverse("projects:list")
    assert not Project.objects.filter(pk=project.pk).exists()


def test_customer_list_archive_filter(logged_in):
    Customer.objects.create(name="Aktiv GmbH")
    Customer.objects.create(name="Alt AG", is_archived=True)
    url = reverse("customers:list")

    response = logged_in.get(url)
    assert "Aktiv GmbH" in response.text and "Alt AG" not in response.text
    assert "Archiviert" in response.text

    response = logged_in.get(url, {"ansicht": "archiviert"})
    assert "Alt AG" in response.text and "Aktiv GmbH" not in response.text

    response = logged_in.get(url, {"ansicht": "alle"})
    assert "Alt AG" in response.text and "Aktiv GmbH" in response.text


def test_overview_entries_can_be_edited(logged_in, entry):
    text = logged_in.get(reverse("core:dashboard")).text

    assert reverse("tracking:edit", args=[entry.pk]) in text


def test_entries_filter_by_customer_and_project(logged_in, entry, user):
    other_customer = Customer.objects.create(name="Andere GmbH")
    other_project = Project.objects.create(customer=other_customer, name="Anderes Projekt")
    other_task = other_project.tasks.create(name="Pflege")
    start = timezone.now() - timedelta(hours=1)
    TimeEntry.objects.create(
        user=user, task=other_task, started_at=start, ended_at=start + timedelta(minutes=20), description="Zwei"
    )
    TimeEntry.objects.filter(pk=entry.pk).update(description="Eins")
    project = entry.task.project

    for url in (reverse("core:dashboard"), reverse("tracking:list")):
        text = logged_in.get(url).text
        assert "– Eins" in text and "– Zwei" in text
        assert f"kunde={project.customer_id}" in text

        text = logged_in.get(url, {"kunde": other_customer.pk}).text
        assert "Gefiltert nach" in text
        assert "– Zwei" in text and "– Eins" not in text

        text = logged_in.get(url, {"projekt": project.pk}).text
        assert "ACME GmbH · Website" in text
        assert "– Eins" in text and "– Zwei" not in text


def test_account_settings_open_in_the_dialog(logged_in):
    page = logged_in.get(reverse("core:dashboard")).text
    assert 'hx-get="/konto/" hx-target="#dialog-body"' in page

    response = logged_in.get(reverse("account:settings"), headers=DIALOG)
    assert 'id="sidebar"' not in response.text and 'action="/konto/"' in response.text


def test_sidebar_timer_comes_with_the_page(logged_in, entry):
    TimeEntry.objects.filter(pk=entry.pk).update(ended_at=None)
    page = logged_in.get(reverse("projects:list")).text
    assert 'id="nav-timer"' in page and entry.task.name in page
    assert 'hx-trigger="load"' not in page
