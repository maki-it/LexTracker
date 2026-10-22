from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from projects.models import Project, Task
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


@pytest.fixture
def logged_in(client, user):
    client.force_login(user)
    return client


def test_create_project(logged_in):
    customer = Customer.objects.create(name="ACME GmbH")

    response = logged_in.post(
        reverse("projects:create"), {"customer": customer.pk, "name": "Relaunch", "status": "active"}
    )

    project = Project.objects.get(name="Relaunch")
    assert response.url == reverse("projects:detail", args=[project.pk])
    assert project.customer == customer


def test_project_form_rejects_end_before_start(logged_in):
    customer = Customer.objects.create(name="ACME GmbH")

    response = logged_in.post(
        reverse("projects:create"),
        {
            "customer": customer.pk,
            "name": "X",
            "status": "active",
            "start_date": "2026-05-02",
            "end_date": "2026-05-01",
        },
    )

    assert response.status_code == 200
    assert "Das Ende liegt vor dem Start." in response.text
    assert not Project.objects.exists()


def test_project_list_and_detail_show_booked_hours(logged_in, user, task):
    start = timezone.now() - timedelta(hours=3)
    TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=90))

    assert "1:30 h" in logged_in.get(reverse("projects:list")).text
    assert "1:30 h" in logged_in.get(reverse("projects:detail", args=[task.project.pk])).text


def test_add_task_returns_task_list(logged_in, task):
    response = logged_in.post(
        reverse("projects:task_create", args=[task.project.pk]), {"name": "Design", "is_billable": "on"}
    )

    assert response.status_code == 200
    assert Task.objects.filter(project=task.project, name="Design").exists()
    assert "Design" in response.text


def test_set_task_status(logged_in, task):
    logged_in.post(reverse("projects:task_status", args=[task.project.pk, task.pk]), {"status": "done"})

    task.refresh_from_db()
    assert task.status == Task.Status.DONE
