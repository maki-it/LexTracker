from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from inbox import service
from inbox.levels import Level
from inbox.models import Message
from mailer.models import MailSettings, OutgoingMail
from reminders import jobs
from reminders.models import Reminder

pytestmark = pytest.mark.django_db

notify_due = async_to_sync(jobs.notify_due)


@pytest.fixture
def admin(user) -> User:
    user.email = "kim@example.de"
    user.save()
    return user


@pytest.fixture
def smtp(db) -> MailSettings:
    config = MailSettings.objects.create(pk=1, host="smtp.example.de", from_address="zeit@example.de")
    config.set_password("geheim")
    config.save()
    return config


@pytest.fixture
def logged_in(client, admin):
    client.force_login(admin)
    return client


def make(admin, task, **values) -> Reminder:
    project = values.pop("project", None)
    values.setdefault("title", "Angebot nachfassen")
    values.setdefault("due_at", (timezone.now() - timedelta(minutes=5)).replace(second=0, microsecond=0))
    return Reminder.objects.create(
        user=admin,
        customer=task.project.customer,
        project=task.project if project else None,
        **values,
    )


# The scheduler job


def test_due_reminder_goes_to_the_bell_and_by_mail(admin, task, smtp):
    reminder = make(admin, task, notes="Preis prüfen")

    assert notify_due(timezone.now()) == 1

    [message] = Message.objects.filter(user=admin)
    assert (message.level, message.kind, message.title) == (Level.INFO, "reminder.due", "Angebot nachfassen")
    assert "ACME GmbH" in message.body and "Preis prüfen" in message.body
    assert message.url == reverse("reminders:list")
    [mail] = OutgoingMail.objects.all()
    assert (mail.kind, mail.to, mail.subject) == (
        OutgoingMail.Kind.REMINDER,
        "kim@example.de",
        "Erinnerung: Angebot nachfassen",
    )
    assert "Preis prüfen" in mail.text
    reminder.refresh_from_db()
    assert reminder.notified_at is not None


def test_a_reminder_is_announced_once(admin, task, smtp):
    make(admin, task)
    assert notify_due(timezone.now()) == 1
    assert notify_due(timezone.now()) == 0
    assert Message.objects.count() == 1
    assert OutgoingMail.objects.count() == 1


def test_reminders_that_are_not_due_stay_quiet(admin, task, smtp):
    make(admin, task, title="später", due_at=timezone.now() + timedelta(hours=1))
    make(admin, task, title="ohne Datum", due_at=None)
    make(admin, task, title="erledigt", done_at=timezone.now())

    assert notify_due(timezone.now()) == 0
    assert not Message.objects.exists()
    assert not OutgoingMail.objects.exists()


def test_notification_channels_are_chosen_per_reminder(admin, task, smtp):
    make(admin, task, title="nur Glocke", notify_email=False)
    make(admin, task, title="nur Mail", notify_bell=False)

    assert notify_due(timezone.now()) == 2

    assert [m.title for m in Message.objects.all()] == ["nur Glocke"]
    assert [m.subject for m in OutgoingMail.objects.all()] == ["Erinnerung: nur Mail"]


def test_no_mail_without_smtp_or_address(admin, task):
    make(admin, task)
    assert notify_due(timezone.now()) == 1
    assert Message.objects.count() == 1
    assert not OutgoingMail.objects.exists()


def test_reminder_mail_does_not_follow_the_message_settings(admin, task, smtp):
    admin.message_email_level = 0
    admin.save()
    make(admin, task, notify_bell=True)

    notify_due(timezone.now())

    assert OutgoingMail.objects.count() == 1
    assert [m.kind for m in OutgoingMail.objects.all()] == [OutgoingMail.Kind.REMINDER]


def test_reminder_shows_in_the_bell_whatever_level_is_hidden(admin, task):
    admin.message_level = Level.CRITICAL
    admin.save()
    make(admin, task)
    notify_due(timezone.now())

    async def visible():
        return [m async for m in service.visible_to(admin)]

    assert [m.title for m in async_to_sync(visible)()] == ["Angebot nachfassen"]


def test_reminder_of_a_project_names_the_project(admin, task, smtp):
    make(admin, task, project=True)
    notify_due(timezone.now())
    assert Message.objects.get().body == "ACME GmbH · Website"


# The pages


def test_create_for_a_customer(logged_in, admin, task):
    customer = task.project.customer
    response = logged_in.post(
        reverse("reminders:create") + f"?customer={customer.pk}",
        {"title": "Vertrag prüfen", "due_at": "2026-12-01T09:30", "notes": "", "notify_bell": "on"},
    )

    assert response.status_code == 302
    reminder = Reminder.objects.get()
    assert (reminder.user, reminder.customer, reminder.project) == (admin, customer, None)
    assert reminder.notify_bell and not reminder.notify_email
    assert timezone.localtime(reminder.due_at).strftime("%d.%m.%Y %H:%M") == "01.12.2026 09:30"


def test_create_for_a_project_also_names_its_customer(logged_in, task):
    logged_in.post(
        reverse("reminders:create") + f"?project={task.project.pk}", {"title": "Abnahme", "notify_bell": "on"}
    )
    reminder = Reminder.objects.get()
    assert (reminder.project, reminder.customer) == (task.project, task.project.customer)
    assert reminder.due_at is None


def test_create_from_the_list_chooses_customer_or_project(logged_in, task):
    page = logged_in.get(reverse("reminders:create"))
    assert f"customer:{task.project.customer.pk}" in page.text
    assert f"project:{task.project.pk}" in page.text

    logged_in.post(reverse("reminders:create"), {"target": f"project:{task.project.pk}", "title": "Abnahme"})

    assert Reminder.objects.get().project == task.project


def test_create_from_the_list_needs_a_target(logged_in, task):
    response = logged_in.post(reverse("reminders:create"), {"title": "Irgendwas"})
    assert response.status_code == 200
    assert not Reminder.objects.exists()


def test_create_for_an_unknown_customer_is_not_found(logged_in):
    response = logged_in.get(reverse("reminders:create") + "?customer=" + "0" * 8 + "-0000-4000-8000-" + "0" * 12)
    assert response.status_code == 404


def test_new_date_announces_the_reminder_again(logged_in, admin, task):
    reminder = make(admin, task, notified_at=timezone.now(), done_at=timezone.now())
    new_date = (timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")

    logged_in.post(
        reverse("reminders:edit", args=[reminder.pk]),
        {"title": reminder.title, "due_at": new_date, "notify_bell": "on", "notify_email": "on"},
    )

    reminder.refresh_from_db()
    assert reminder.notified_at is None and reminder.done_at is None


def test_editing_something_else_keeps_it_announced(logged_in, admin, task):
    reminder = make(admin, task, notified_at=timezone.now())
    due = timezone.localtime(reminder.due_at).strftime("%Y-%m-%dT%H:%M")

    logged_in.post(reverse("reminders:edit", args=[reminder.pk]), {"title": "Neuer Titel", "due_at": due})

    reminder.refresh_from_db()
    assert reminder.title == "Neuer Titel"
    assert reminder.notified_at is not None


def test_done_clears_the_message_and_reopen_brings_the_reminder_back(logged_in, admin, task):
    reminder = make(admin, task)
    notify_due(timezone.now())

    logged_in.post(reverse("reminders:done", args=[reminder.pk]))

    reminder.refresh_from_db()
    assert reminder.is_done
    assert Message.objects.get().read_at is not None

    logged_in.post(reverse("reminders:reopen", args=[reminder.pk]))
    reminder.refresh_from_db()
    assert not reminder.is_done


def test_delete(logged_in, admin, task):
    reminder = make(admin, task)
    logged_in.post(reverse("reminders:delete", args=[reminder.pk]))
    assert not Reminder.objects.exists()


def test_actions_return_only_to_pages_of_the_app(logged_in, admin, task):
    reminder = make(admin, task)
    response = logged_in.post(reverse("reminders:done", args=[reminder.pk]), {"next": "https://evil.example/"})
    assert response["Location"] == reverse("reminders:list")


def test_reminders_of_someone_else_are_not_found(client, admin, task):
    other = User.objects.create_user(username="ines", password="geheim-123", role=User.Role.ADMIN)
    reminder = make(other, task)
    client.force_login(admin)
    assert client.get(reverse("reminders:edit", args=[reminder.pk])).status_code == 404
    assert client.post(reverse("reminders:done", args=[reminder.pk])).status_code == 404
    assert Reminder.objects.get().done_at is None


def test_employees_have_no_reminders(client, task):
    employee = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)
    assert client.get(reverse("reminders:list")).status_code == 403


def test_list_groups_by_state(logged_in, admin, task):
    make(admin, task, title="fällig jetzt")
    make(admin, task, title="kommt noch", due_at=timezone.now() + timedelta(days=1))
    make(admin, task, title="irgendwann", due_at=None)
    make(admin, task, title="schon fertig", done_at=timezone.now())

    page = logged_in.get(reverse("reminders:list"))

    assert page.context["overdue"][0].title == "fällig jetzt"
    assert [r.title for r in page.context["upcoming"]] == ["kommt noch"]
    assert [r.title for r in page.context["undated"]] == ["irgendwann"]
    assert [r.title for r in page.context["done"]] == ["schon fertig"]


def test_customer_and_project_pages_list_their_reminders(logged_in, admin, task):
    make(admin, task, title="Für den Kunden")
    make(admin, task, title="Für das Projekt", project=True)

    customer_page = logged_in.get(reverse("customers:edit", args=[task.project.customer.pk]))
    project_page = logged_in.get(reverse("projects:detail", args=[task.project.pk]))

    assert "Für den Kunden" in customer_page.text and "Für das Projekt" in customer_page.text
    assert "Für das Projekt" in project_page.text and "Für den Kunden" not in project_page.text


def test_sidebar_counts_due_reminders(logged_in, admin, task):
    make(admin, task)
    make(admin, task, due_at=timezone.now() + timedelta(days=1))
    make(admin, task, done_at=timezone.now())

    response = logged_in.get(reverse("projects:list"))

    assert response.wsgi_request.nav_counts["reminders"] == 1
