from datetime import date, datetime, timedelta

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


def test_list_shows_the_open_reminders_by_default(logged_in, admin, task):
    make(admin, task, title="fällig jetzt")
    make(admin, task, title="kommt noch", due_at=timezone.now() + timedelta(days=1))
    make(admin, task, title="irgendwann", due_at=None)
    make(admin, task, title="schon fertig", done_at=timezone.now())

    page = logged_in.get(reverse("reminders:list"))

    assert page.context["overdue"][0].title == "fällig jetzt"
    assert [r.title for r in page.context["upcoming"]] == ["kommt noch"]
    assert [r.title for r in page.context["undated"]] == ["irgendwann"]
    assert page.context["done"] == []
    assert [(key, count) for key, _, count, _ in page.context["view_links"]] == [("open", 3), ("done", 1), ("all", 4)]


def test_list_filters_by_status(logged_in, admin, task):
    make(admin, task, title="offen")
    make(admin, task, title="fertig", done_at=timezone.now())

    done = logged_in.get(reverse("reminders:list"), {"view": "done"}).context
    both = logged_in.get(reverse("reminders:list"), {"view": "all"}).context
    unknown = logged_in.get(reverse("reminders:list"), {"view": "gibtsnicht"}).context

    assert ([r.title for r in done["overdue"]], [r.title for r in done["done"]]) == ([], ["fertig"])
    assert ([r.title for r in both["overdue"]], [r.title for r in both["done"]]) == (["offen"], ["fertig"])
    assert unknown["view"] == "open"


def test_list_filters_by_customer_and_project(logged_in, admin, task):
    from customers.models import Customer
    from projects.models import Project

    other = Customer.objects.create(name="Beta AG")
    other_project = Project.objects.create(customer=other, name="Shop")
    make(admin, task, title="ACME allgemein")
    make(admin, task, title="ACME Website", project=True)
    Reminder.objects.create(user=admin, customer=other, project=other_project, title="Beta Shop")

    def titles(**params):
        context = logged_in.get(reverse("reminders:list"), params).context
        return sorted(r.title for r in context["overdue"] + context["undated"] + context["upcoming"])

    assert len(titles()) == 3
    assert titles(customer=task.project.customer.pk) == ["ACME Website", "ACME allgemein"]
    assert titles(project=task.project.pk) == ["ACME Website"]
    assert titles(customer=other.pk) == ["Beta Shop"]
    # A project of another customer does not fit the customer: nothing matches both.
    assert titles(customer=other.pk, project=task.project.pk) == ["Beta Shop"]


def test_list_filter_ignores_unknown_ids_and_other_users(logged_in, admin, task):
    other = User.objects.create_user(username="ines", password="geheim-123", role=User.Role.ADMIN)
    make(admin, task)
    make(other, task, title="von Ines")

    context = logged_in.get(reverse("reminders:list"), {"customer": "kaputt", "project": "0" * 32}).context

    assert [r.title for r in context["overdue"]] == ["Angebot nachfassen"]
    assert context["customer"] is None and context["project"] is None


def test_actions_on_the_list_return_to_the_same_filter(logged_in, admin, task):
    reminder = make(admin, task)
    url = reverse("reminders:list") + "?view=all"

    page = logged_in.get(url)

    assert f'value="{url}"' in page.text
    response = logged_in.post(reverse("reminders:done", args=[reminder.pk]), {"next": url})
    assert response["Location"] == url


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


def test_bell_brings_the_sidebar_count_of_due_reminders(logged_in, admin, task):
    make(admin, task)

    fragment = logged_in.get(reverse("inbox:bell")).text

    assert 'id="nav-reminders-count" class="contents"' in fragment
    assert 'hx-swap-oob="true"' in fragment
    assert ">1<" in fragment


def test_bell_has_no_reminder_count_for_employees(client, task):
    employee = User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)
    client.force_login(employee)

    assert "nav-reminders-count" not in client.get(reverse("inbox:bell")).text


# Repeating reminders


def local(year, month, day, hour=9, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


def series(repeat, start, **values) -> Reminder:
    return Reminder(title="Wiederkehrend", due_at=start, repeat=repeat, **values)


def test_a_daily_and_a_weekly_series_count_in_steps():
    start = local(2026, 10, 27)

    assert series("daily", start).next_due(start) == local(2026, 10, 28)
    assert series("daily", start, repeat_every=3).next_due(start) == local(2026, 10, 30)
    assert series("weekly", start).next_due(start) == local(2026, 11, 3)
    assert series("weekly", start, repeat_every=2).next_due(start) == local(2026, 11, 10)


def test_a_monthly_series_returns_to_the_day_after_a_short_month():
    reminder = series("monthly", local(2026, 1, 31), repeat_from=local(2026, 1, 31))

    reminder.due_at = reminder.next_due(reminder.due_at)
    assert reminder.due_at == local(2026, 2, 28)
    reminder.due_at = reminder.next_due(reminder.due_at)
    assert reminder.due_at == local(2026, 3, 31)


def test_a_yearly_series_survives_a_leap_day():
    reminder = series("yearly", local(2028, 2, 29), repeat_from=local(2028, 2, 29))

    assert reminder.next_due(reminder.due_at) == local(2029, 2, 28)
    reminder.due_at = local(2031, 2, 28)
    assert reminder.next_due(reminder.due_at) == local(2032, 2, 29)


def test_the_time_of_day_stays_across_the_change_to_summer_time():
    start = local(2026, 3, 27, 9, 30)

    assert series("weekly", start).next_due(start) == local(2026, 4, 3, 9, 30)
    assert series("daily", local(2026, 3, 28, 9, 30), repeat_every=2).next_due(start) == local(2026, 3, 30, 9, 30)


def test_missed_dates_are_skipped():
    start = local(2026, 10, 1)

    assert series("weekly", start).next_due(local(2026, 10, 27, 12)) == local(2026, 10, 29)


def test_a_series_ends_after_its_last_date():
    start = local(2026, 10, 27)

    assert series("weekly", start, repeat_until=date(2026, 11, 3)).next_due(start) == local(2026, 11, 3)
    assert series("weekly", start, repeat_until=date(2026, 11, 2)).next_due(start) is None
    assert series("", start).next_due(start) is None
    assert Reminder(title="x", repeat="weekly").next_due(start) is None


def test_the_series_is_described_in_words():
    assert series("weekly", None).repeat_text == "wöchentlich"
    assert series("monthly", None, repeat_every=3).repeat_text == "alle 3 Monate"
    assert series("", None).repeat_text == ""


def test_a_repeating_reminder_moves_on_when_it_was_announced(admin, task, smtp):
    due = (timezone.now() - timedelta(minutes=5)).replace(second=0, microsecond=0)
    reminder = make(admin, task, due_at=due, repeat="weekly", repeat_from=due)

    assert notify_due(timezone.now()) == 1

    reminder.refresh_from_db()
    assert reminder.due_at == series("weekly", due).next_due(due)
    assert reminder.notified_at is None and reminder.done_at is None
    assert Message.objects.filter(kind="reminder.due").count() == 1
    assert OutgoingMail.objects.count() == 1
    # Nothing more until the next date.
    assert notify_due(timezone.now()) == 0


def test_each_time_a_new_message_replaces_the_one_before(admin, task):
    due = (timezone.now() - timedelta(minutes=5)).replace(second=0, microsecond=0)
    reminder = make(admin, task, due_at=due, repeat="daily", repeat_from=due, notify_email=False)
    notify_due(timezone.now())
    Reminder.objects.filter(pk=reminder.pk).update(due_at=timezone.now() - timedelta(minutes=1))

    assert notify_due(timezone.now()) == 1

    first, second = Message.objects.order_by("created_at")
    assert first.read_at is not None and second.read_at is None
    assert (first.count, second.count) == (1, 1)


def test_the_last_date_of_a_series_ends_it_like_a_single_reminder(admin, task):
    due = (timezone.now() - timedelta(minutes=5)).replace(second=0, microsecond=0)
    reminder = make(
        admin,
        task,
        due_at=due,
        repeat="daily",
        repeat_from=due,
        repeat_until=timezone.localdate(due),
        notify_email=False,
    )

    assert notify_due(timezone.now()) == 1

    reminder.refresh_from_db()
    assert reminder.due_at == due and reminder.notified_at is not None
    assert notify_due(timezone.now()) == 0


def post_reminder(client, reminder, **values):
    due = timezone.localtime(reminder.due_at).strftime("%Y-%m-%dT%H:%M")
    return client.post(
        reverse("reminders:edit", args=[reminder.pk]), {"title": reminder.title, "due_at": due, **values}
    )


def test_a_repeating_reminder_is_created_with_its_first_date_as_the_start(logged_in, admin, task):
    logged_in.post(
        reverse("reminders:create") + f"?customer={task.project.customer.pk}",
        {"title": "Wartung", "due_at": "2026-12-31T09:30", "repeat": "monthly", "repeat_every": "2"},
    )

    reminder = Reminder.objects.get()
    assert (reminder.repeat, reminder.repeat_every) == ("monthly", 2)
    assert reminder.repeat_from == reminder.due_at == local(2026, 12, 31, 9, 30)
    assert reminder.repeat_text == "alle 2 Monate"


def test_a_repetition_needs_a_date(logged_in, task):
    response = logged_in.post(
        reverse("reminders:create") + f"?customer={task.project.customer.pk}",
        {"title": "Wartung", "repeat": "weekly"},
    )

    assert response.status_code == 200
    assert "Eine Wiederholung braucht ein Datum." in response.text
    assert not Reminder.objects.exists()


def test_the_end_may_not_lie_before_the_start(logged_in, task):
    response = logged_in.post(
        reverse("reminders:create") + f"?customer={task.project.customer.pk}",
        {"title": "Wartung", "due_at": "2026-12-31T09:30", "repeat": "weekly", "repeat_until": "2026-12-30"},
    )

    assert "Das Ende liegt vor dem ersten Datum." in response.text
    assert not Reminder.objects.exists()


def test_editing_something_else_keeps_the_start_of_the_series(logged_in, admin, task):
    start = local(2026, 1, 31)
    reminder = make(admin, task, due_at=local(2026, 2, 28), repeat="monthly", repeat_from=start)

    post_reminder(logged_in, reminder, title="Anders", repeat="monthly", repeat_every="1")

    reminder.refresh_from_db()
    assert (reminder.title, reminder.repeat_from) == ("Anders", start)


def test_a_new_date_or_a_new_interval_starts_the_series_afresh(logged_in, admin, task):
    reminder = make(admin, task, due_at=local(2026, 2, 28), repeat="monthly", repeat_from=local(2026, 1, 31))

    post_reminder(logged_in, reminder, repeat="monthly", repeat_every="2")

    reminder.refresh_from_db()
    assert reminder.repeat_from == local(2026, 2, 28)


def test_switching_the_repetition_off_forgets_it(logged_in, admin, task):
    reminder = make(
        admin, task, repeat="weekly", repeat_every=2, repeat_from=timezone.now(), repeat_until=date(2030, 1, 1)
    )

    post_reminder(logged_in, reminder, repeat="")

    reminder.refresh_from_db()
    assert (reminder.repeat, reminder.repeat_every, reminder.repeat_until, reminder.repeat_from) == ("", 1, None, None)


def test_the_list_says_how_a_reminder_repeats(logged_in, admin, task):
    make(admin, task, due_at=timezone.now() + timedelta(days=1), repeat="weekly", repeat_until=date(2030, 1, 1))

    page = logged_in.get(reverse("reminders:list")).text

    assert "↻ wöchentlich" in page and "bis 01.01.2030" in page
    assert "Beendet auch die Wiederholung" in page
