from datetime import timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from customers.models import Customer
from projects.models import Project, Task, TaskTemplate
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


def test_create_task_template(logged_in):
    response = logged_in.post(
        reverse("projects:template_create"), {"name": "Projektmanagement", "hourly_rate": "80", "is_billable": "on"}
    )

    assert response.url == reverse("projects:templates")
    template = TaskTemplate.objects.get()
    assert template.hourly_rate == Decimal("80")
    assert "Projektmanagement" in logged_in.get(reverse("projects:templates")).text


def test_add_tasks_from_templates_copies_values_and_skips_existing(logged_in, task):
    meeting = TaskTemplate.objects.create(
        name="Meetings", description="Abstimmungen", is_billable=False, estimated_hours=Decimal("4")
    )
    existing = TaskTemplate.objects.create(name=task.name)

    response = logged_in.post(
        reverse("projects:task_from_templates", args=[task.project.pk]), {"template": [meeting.pk, existing.pk]}
    )

    assert response.status_code == 200
    assert task.project.tasks.count() == 2
    added = task.project.tasks.get(name="Meetings")
    assert (added.description, added.is_billable, added.estimated_hours) == ("Abstimmungen", False, Decimal("4"))
    assert "Aus Vorlagen hinzufügen" in response.text


def test_create_project_with_templates(logged_in):
    customer = Customer.objects.create(name="ACME GmbH")
    template = TaskTemplate.objects.create(name="Konzeption", hourly_rate=Decimal("95"))
    assert "Aufgaben aus Vorlagen" in logged_in.get(reverse("projects:create")).text

    logged_in.post(
        reverse("projects:create"),
        {"customer": customer.pk, "name": "Relaunch", "status": "active", "templates": [template.pk]},
    )

    task = Project.objects.get(name="Relaunch").tasks.get()
    assert (task.name, task.hourly_rate) == ("Konzeption", Decimal("95"))


def test_edit_form_does_not_offer_templates(logged_in, task):
    TaskTemplate.objects.create(name="Konzeption")

    assert "Aufgaben aus Vorlagen" not in logged_in.get(reverse("projects:edit", args=[task.project.pk])).text


def test_save_task_as_template(logged_in, task):
    task.estimated_hours = Decimal("2.5")
    task.save()
    url = reverse("projects:task_save_as_template", args=[task.project.pk, task.pk])

    logged_in.post(url)
    response = logged_in.post(url, follow=True)

    template = TaskTemplate.objects.get()
    assert (template.name, template.estimated_hours) == ("Entwicklung", Decimal("2.5"))
    assert "Es gibt schon eine Vorlage" in response.text


def test_delete_template_keeps_tasks(logged_in, task):
    template = TaskTemplate.objects.create(name="Konzeption")
    logged_in.post(reverse("projects:task_from_templates", args=[task.project.pk]), {"template": [template.pk]})

    logged_in.post(reverse("projects:template_delete", args=[template.pk]))

    assert not TaskTemplate.objects.exists()
    assert task.project.tasks.filter(name="Konzeption").exists()
