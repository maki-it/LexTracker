from datetime import timedelta

import pytest
from asgiref.sync import async_to_sync
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from core import scheduler
from inbox import events, jobs, service
from inbox.levels import Level
from inbox.models import Message
from lexware.client import LexwareError, LexwareUnauthorized
from mailer import outbox
from mailer.models import MailSettings, OutgoingMail
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

notify = async_to_sync(service.anotify)
resolve = async_to_sync(service.aresolve)


@pytest.fixture
def admin(user) -> User:
    user.email = "kim@example.de"
    user.save()
    return user


@pytest.fixture
def employee(db) -> User:
    return User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)


@pytest.fixture
def customer_user(task) -> User:
    return User.objects.create_user(
        username="acme", password="geheim-123", role=User.Role.CUSTOMER, customer=task.project.customer
    )


@pytest.fixture
def smtp(db) -> MailSettings:
    config = MailSettings.objects.create(pk=1, host="smtp.example.de", from_address="zeit@example.de")
    config.set_password("geheim")
    config.save()
    return config


def stored(user: User) -> list[Message]:
    return list(Message.objects.filter(user=user))


# Creating messages


def test_system_messages_go_to_administrators_only(admin, employee, customer_user):
    notify(Level.INFO, "x", "Hallo")
    assert len(stored(admin)) == 1
    assert not stored(employee)
    assert not stored(customer_user)


def test_staff_audience_skips_customers(admin, employee, customer_user):
    notify(Level.INFO, "x", "Hallo", to=service.Audience.STAFF)
    assert (len(stored(admin)), len(stored(employee)), len(stored(customer_user))) == (1, 1, 0)


def test_message_to_one_user(admin, employee):
    notify(Level.WARNING, "x", "Nur Mia", to=employee)
    assert len(stored(employee)) == 1
    assert not stored(admin)


def test_inactive_users_get_nothing(admin):
    admin.is_active = False
    admin.save()
    assert notify(Level.INFO, "x", "Hallo") == []


def test_link_must_be_a_path_in_the_app(admin):
    for url in ("https://evil.example/", "//evil.example/"):
        with pytest.raises(ValueError):
            notify(Level.INFO, "x", "Hallo", url=url)
    notify(Level.INFO, "x", "Hallo", url="/settings/")


def test_same_unread_message_is_counted_not_repeated(admin):
    for _ in range(3):
        notify(Level.WARNING, "backup", "Fehler", "Platte voll", dedupe_key="backup")
    [message] = stored(admin)
    assert message.count == 3
    assert message.body == "Platte voll"


def test_read_message_is_not_updated_anymore(admin):
    notify(Level.WARNING, "backup", "Fehler", dedupe_key="backup")
    Message.objects.update(read_at=timezone.now())
    notify(Level.WARNING, "backup", "Fehler", dedupe_key="backup")
    assert Message.objects.count() == 2
    assert Message.objects.filter(read_at__isnull=True).get().count == 1


def test_repeated_message_keeps_the_higher_level(admin):
    notify(Level.CRITICAL, "x", "Fehler", dedupe_key="k")
    notify(Level.INFO, "x", "Fehler", dedupe_key="k")
    assert stored(admin)[0].level == Level.CRITICAL


def test_repeating_message_becomes_critical(admin):
    for _ in range(3):
        notify(Level.WARNING, "x", "Fehler", dedupe_key="k", escalate_after=3)
        assert stored(admin)[0].level == (Level.CRITICAL if Message.objects.get().count >= 3 else Level.WARNING)
    assert stored(admin)[0].level == Level.CRITICAL


def test_resolve_marks_messages_read(admin, employee):
    notify(Level.CRITICAL, "backup", "Fehler", dedupe_key="backup")
    notify(Level.CRITICAL, "other", "Anderes", dedupe_key="other")
    assert resolve("backup") == 1
    assert Message.objects.get(dedupe_key="backup").read_at
    assert Message.objects.get(dedupe_key="other").read_at is None


# What a user sees


def test_threshold_hides_lower_levels_but_never_critical(admin):
    for level in Level:
        notify(level, "x", level.label)
    admin.message_level = Level.WARNING
    assert {m.level for m in async_to_sync(list_visible)(admin)} == {Level.WARNING, Level.CRITICAL}
    admin.message_level = Level.CRITICAL
    assert {m.level for m in async_to_sync(list_visible)(admin)} == {Level.CRITICAL}


async def list_visible(user):
    return [m async for m in service.visible_to(user)]


def test_summary_counts_unread_visible_messages(admin):
    notify(Level.DEBUG, "x", "Debug")
    notify(Level.INFO, "x", "Info")
    notify(Level.WARNING, "x", "Warnung")
    Message.objects.filter(title="Info").update(read_at=timezone.now())
    result = async_to_sync(service.summary)(admin)
    # Debug is below the default threshold, Info is read.
    assert (result["count"], result["top"], result["critical"]) == (1, Level.WARNING, None)
    notify(Level.CRITICAL, "x", "Kritisch")
    result = async_to_sync(service.summary)(admin)
    assert (result["count"], result["critical"].title, result["critical_count"]) == (2, "Kritisch", 1)


# E-mail


def test_critical_message_is_also_mailed(admin, smtp):
    notify(Level.CRITICAL, "backup", "Sicherung kaputt", "Platte voll", dedupe_key="backup")
    notify(Level.CRITICAL, "backup", "Sicherung kaputt", "Platte voll", dedupe_key="backup")
    [queued] = OutgoingMail.objects.all()
    assert (queued.kind, queued.to, queued.user) == (OutgoingMail.Kind.NOTIFICATION, "kim@example.de", admin)
    assert queued.subject == "Kritisch: Sicherung kaputt"
    assert "Platte voll" in queued.text


def test_lower_levels_are_not_mailed_by_default(admin, smtp):
    notify(Level.WARNING, "x", "Warnung")
    assert not OutgoingMail.objects.exists()


def test_mail_level_is_per_user(admin, smtp):
    admin.message_email_level = Level.INFO
    admin.save()
    notify(Level.INFO, "x", "Info")
    assert OutgoingMail.objects.count() == 1
    admin.message_email_level = 0
    admin.save()
    notify(Level.CRITICAL, "x", "Kritisch")
    assert OutgoingMail.objects.count() == 1


def test_message_that_becomes_critical_is_mailed_then(admin, smtp):
    for _ in range(3):
        notify(Level.WARNING, "x", "Fehler", dedupe_key="k", escalate_after=3)
    [queued] = OutgoingMail.objects.all()
    assert queued.subject == "Kritisch: Fehler"


def test_no_mail_without_smtp_or_address(admin):
    notify(Level.CRITICAL, "x", "Kritisch")
    assert not OutgoingMail.objects.exists()


def test_notification_mail_is_sent_by_the_queue(admin, smtp):
    notify(Level.CRITICAL, "x", "Kritisch", "Details")
    assert async_to_sync(outbox.send_due)() == 1
    assert mail.outbox[0].subject == "Kritisch: Kritisch"


# Clean-up


def test_prune_deletes_by_level_and_age(admin):
    now = timezone.now()
    for level in Level:
        notify(level, "x", f"{level.label} gelesen")
    Message.objects.update(read_at=now - timedelta(days=60), last_at=now - timedelta(days=60))
    notify(Level.INFO, "x", "Info frisch")
    notify(Level.DEBUG, "x", "Debug ungelesen alt")
    Message.objects.filter(title="Debug ungelesen alt").update(last_at=now - timedelta(days=7))
    notify(Level.WARNING, "x", "Warnung ungelesen alt")
    Message.objects.filter(title="Warnung ungelesen alt").update(last_at=now - timedelta(days=400))

    # Read for 60 days: debug (3 days) and info (30) go, warning (90) and critical (365) stay.
    assert async_to_sync(service.prune)(now) == 3
    assert set(Message.objects.values_list("title", flat=True)) == {
        "Warnung gelesen",
        "Kritisch gelesen",
        "Info frisch",
        "Warnung ungelesen alt",
    }


def test_prune_caps_the_messages_per_user(admin, monkeypatch):
    monkeypatch.setattr(service, "KEEP_MAX", 3)
    notify(Level.CRITICAL, "x", "Wichtig")
    for n in range(4):
        notify(Level.DEBUG, "x", f"Debug {n}")
    assert async_to_sync(service.prune)() == 2
    titles = set(Message.objects.values_list("title", flat=True))
    assert "Wichtig" in titles and len(titles) == 3


# The bell, the panel and the page


@pytest.fixture
def logged_in(client, admin):
    client.force_login(admin)
    return client


def test_bell_shows_the_unread_count(logged_in, admin):
    notify(Level.WARNING, "x", "Warnung")
    page = logged_in.get(reverse("core:dashboard")).text
    assert 'id="nav-bell"' in page
    assert "Nachrichten, 1 ungelesen" in page


def test_bell_without_unread_messages_has_no_count(logged_in):
    assert "ungelesen" not in logged_in.get(reverse("core:dashboard")).text


def test_critical_message_shows_a_banner_on_every_page(logged_in, admin):
    notify(Level.CRITICAL, "backup", "Datensicherung fehlgeschlagen", "Platte voll")
    notify(Level.CRITICAL, "other", "Zweite")
    page = logged_in.get(reverse("core:dashboard")).text
    # The newest one is named, the rest counted.
    assert "Zweite" in page
    assert "Und 1 weitere kritische Nachrichten." in page
    Message.objects.update(read_at=timezone.now())
    assert "weitere kritische" not in logged_in.get(reverse("core:dashboard")).text


def test_bell_fragment(logged_in, admin):
    notify(Level.INFO, "x", "Info")
    assert "Nachrichten, 1 ungelesen" in logged_in.get(reverse("inbox:bell")).text


def test_panel_lists_the_latest_messages(logged_in, admin):
    notify(Level.CRITICAL, "backup", "Sicherung kaputt", "Platte voll", dedupe_key="backup")
    notify(Level.CRITICAL, "backup", "Sicherung kaputt", "Platte voll", dedupe_key="backup")
    notify(Level.DEBUG, "x", "Versteckter Debug")
    page = logged_in.get(reverse("inbox:panel")).text
    assert "Sicherung kaputt" in page and "Platte voll" in page
    assert "2×" in page
    assert "Versteckter Debug" not in page
    assert "Angezeigt ab Priorität „Info“" in page


def test_panel_without_messages(logged_in):
    assert "Keine Nachrichten." in logged_in.get(reverse("inbox:panel")).text


def test_panel_links_to_the_page_when_there_are_more(logged_in, admin):
    for n in range(9):
        notify(Level.INFO, "x", f"Nr {n}")
    assert "Alle Nachrichten anzeigen" in logged_in.get(reverse("inbox:panel")).text


def test_panel_in_dialog_has_no_sidebar(logged_in, admin):
    notify(Level.INFO, "x", "Info")
    page = logged_in.get(reverse("inbox:panel"), headers={"HX-Request": "true", "HX-Target": "dialog-body"}).text
    assert "Hauptnavigation" not in page and "Info" in page


def test_open_marks_read_and_goes_to_the_target(logged_in, admin):
    notify(Level.WARNING, "x", "Warnung", url="/settings/")
    message = Message.objects.get()
    response = logged_in.get(reverse("inbox:open", args=[message.pk]))
    assert response.status_code == 302 and response["Location"] == "/settings/"
    message.refresh_from_db()
    assert message.read_at


def test_read_one_message(logged_in, admin):
    notify(Level.INFO, "x", "Eins")
    notify(Level.INFO, "x", "Zwei")
    message = Message.objects.get(title="Eins")
    response = logged_in.post(reverse("inbox:read", args=[message.pk]), {"next": reverse("inbox:all")})
    assert response.status_code == 302
    assert Message.objects.get(title="Eins").read_at
    assert Message.objects.get(title="Zwei").read_at is None


def test_action_in_dialog_returns_the_panel_and_tells_the_bell(logged_in, admin):
    notify(Level.INFO, "x", "Eins")
    notify(Level.INFO, "x", "Zwei")
    dialog = {"HX-Request": "true", "HX-Target": "dialog-body"}
    response = logged_in.post(reverse("inbox:read_all"), headers=dialog)
    assert response.status_code == 200
    assert response["HX-Trigger"] == "inbox-changed"
    assert "Alle als gelesen markieren" not in response.text
    assert not Message.objects.filter(read_at__isnull=True).exists()


def test_delete_message(logged_in, admin):
    notify(Level.INFO, "x", "Eins")
    logged_in.post(reverse("inbox:delete", args=[Message.objects.get().pk]))
    assert not Message.objects.exists()


def test_redirect_after_action_stays_in_the_inbox(logged_in, admin):
    notify(Level.INFO, "x", "Eins")
    pk = Message.objects.get().pk
    response = logged_in.post(reverse("inbox:read", args=[pk]), {"next": "https://evil.example/"})
    assert response["Location"] == reverse("inbox:all")
    response = logged_in.post(reverse("inbox:read", args=[pk]), {"next": reverse("inbox:all") + "?filter=critical"})
    assert response["Location"] == reverse("inbox:all") + "?filter=critical"


def test_nobody_touches_the_messages_of_others(client, admin, employee):
    notify(Level.INFO, "x", "Nur für Kim")
    pk = Message.objects.get().pk
    client.force_login(employee)
    for name, method in (("open", client.get), ("read", client.post), ("delete", client.post)):
        assert method(reverse(f"inbox:{name}", args=[pk])).status_code == 404
    assert "Nur für Kim" not in client.get(reverse("inbox:all")).text
    assert Message.objects.get().read_at is None


def test_all_page_filters_by_level(logged_in, admin):
    notify(Level.CRITICAL, "x", "Ein Kritischer")
    notify(Level.INFO, "x", "Eine Info")
    Message.objects.filter(title="Eine Info").update(read_at=timezone.now())
    everything = logged_in.get(reverse("inbox:all")).text
    assert "Ein Kritischer" in everything and "Eine Info" in everything
    critical = logged_in.get(reverse("inbox:all"), {"filter": "critical"}).text
    assert "Ein Kritischer" in critical and "Eine Info" not in critical
    unread = logged_in.get(reverse("inbox:all"), {"filter": "unread"}).text
    assert "Ein Kritischer" in unread and "Eine Info" not in unread


def test_debug_filter_only_for_users_who_see_debug(logged_in, admin):
    assert "?filter=debug" not in logged_in.get(reverse("inbox:all")).text
    admin.message_level = Level.DEBUG
    admin.save()
    assert "?filter=debug" in logged_in.get(reverse("inbox:all")).text


def test_all_page_loads_more_while_scrolling(logged_in, admin):
    admin.list_page_size = 25
    admin.save()
    for n in range(30):
        notify(Level.INFO, "x", f"Nachricht {n:02}")
    first = logged_in.get(reverse("inbox:all")).text
    assert "Weitere laden" in first
    more = logged_in.get(reverse("inbox:all"), {"page": 2}, headers={"HX-Request": "true"}).text
    assert "Weitere laden" not in more
    assert more.count("<li") == 5


def test_employees_have_a_bell_and_customers_do_not(client, employee, customer_user):
    notify(Level.WARNING, "x", "Für Mia", to=employee)
    client.force_login(employee)
    assert "Nachrichten, 1 ungelesen" in client.get(reverse("tracking:list")).text
    assert client.get(reverse("inbox:all")).status_code == 200
    client.force_login(customer_user)
    assert 'id="nav-bell"' not in client.get(reverse("portal:overview")).text
    assert client.get(reverse("inbox:all")).status_code == 403


def test_login_is_required(client):
    assert client.get(reverse("inbox:panel")).status_code == 302


# Settings


def test_account_page_sets_the_levels(logged_in, admin):
    data = {
        "first_name": "Kim",
        "email": "kim@example.de",
        "theme": "system",
        "date_format": "d.m.Y",
        "duration_format": "clock",
        "list_page_size": 50,
        "message_level": Level.WARNING,
        "message_email_level": 0,
    }
    assert logged_in.post(reverse("account:settings"), data).status_code == 302
    admin.refresh_from_db()
    assert (admin.message_level, admin.message_email_level) == (Level.WARNING, 0)
    page = logged_in.get(reverse("account:settings")).text
    assert "Nachrichten anzeigen ab" in page


def test_customers_have_no_message_settings(client, customer_user):
    client.force_login(customer_user)
    assert "Nachrichten anzeigen ab" not in client.get(reverse("account:settings")).text


# What the app reports on its own


def test_failed_job_warns_and_turns_critical_when_it_keeps_failing(admin):
    for _ in range(3):
        async_to_sync(events.job_failed)("customers", "Kundenimport", LexwareError("Zeitüberschreitung"))
    [message] = stored(admin)
    assert (message.level, message.count, message.title) == (Level.CRITICAL, 3, "Kundenimport fehlgeschlagen")
    assert message.body == "Zeitüberschreitung"
    assert message.url == "/settings/?tab=lexware"


def test_first_failure_is_a_warning(admin):
    async_to_sync(events.job_failed)("invoices", "Rechnungsabgleich", LexwareError("kaputt"))
    assert stored(admin)[0].level == Level.WARNING


def test_rejected_key_is_critical_at_once(admin):
    async_to_sync(events.job_failed)("customers", "Kundenimport", LexwareUnauthorized("abgelehnt"))
    [message] = stored(admin)
    assert (message.level, message.title) == (Level.CRITICAL, "Lexware lehnt den API-Schlüssel ab")


def test_job_that_works_again_clears_its_failure(admin):
    async_to_sync(events.job_failed)("customers", "Kundenimport", LexwareError("kaputt"))
    async_to_sync(events.job_failed)("customers", "Kundenimport", LexwareUnauthorized("abgelehnt"))
    async_to_sync(events.job_done)("customers", "Kundenimport", "0 neu.", changed=False)
    assert not Message.objects.filter(level__gte=Level.WARNING, read_at__isnull=True).exists()
    [done] = Message.objects.filter(kind="customers.done")
    assert done.level == Level.DEBUG


def test_import_with_changes_is_news(admin):
    async_to_sync(events.job_done)("customers", "Kundenimport", "2 neu.", changed=True)
    async_to_sync(events.job_done)("customers", "Kundenimport", "2 neu.", changed=True)
    assert [m.level for m in stored(admin)] == [Level.INFO, Level.INFO]


@pytest.mark.django_db(transaction=True)
async def test_scheduler_reports_a_failed_job(admin, monkeypatch, settings):
    from dataclasses import replace

    settings.LEXWARE_API_KEY = "test-key"

    async def broken():
        raise LexwareError("Lexware ist nicht erreichbar")

    monkeypatch.setattr(scheduler, "JOBS", [replace(job, run=broken) for job in scheduler.JOBS[:1]])
    assert await scheduler.run_due_jobs(timezone.now()) == ["customer import"]
    message = await Message.objects.aget()
    assert (message.level, message.title) == (Level.WARNING, "Kundenimport fehlgeschlagen")


def test_failed_backup_is_critical_and_a_working_one_clears_it(admin):
    async_to_sync(events.backup_failed)(OSError("Read-only file system"))
    [message] = stored(admin)
    assert message.level == Level.CRITICAL and "Read-only file system" in message.body
    async_to_sync(events.backup_done)("db-2026-10-23-030000.sqlite3")
    assert Message.objects.get(kind="backup.failed").read_at


def test_restore_and_upload_are_info(admin):
    async_to_sync(events.backup_restored)("db-1.sqlite3", "kim")
    async_to_sync(events.backup_uploaded)("db-2.sqlite3", "kim")
    assert [m.level for m in stored(admin)] == [Level.INFO, Level.INFO]


def test_mail_that_gives_up_is_reported(admin, smtp, monkeypatch):
    mail_ = OutgoingMail.objects.create(
        kind=OutgoingMail.Kind.WEEKLY_REPORT,
        to="x@example.de",
        subject="Bericht",
        text="t",
        attempts=len(outbox.RETRY_DELAYS),
        last_error="boom",
    )
    monkeypatch.setattr(outbox, "deliver", lambda config, messages: ["Connection refused"] * len(messages))
    assert async_to_sync(outbox.send_due)(on_failed=events.mail_failed) == 0
    mail_.refresh_from_db()
    assert mail_.status == OutgoingMail.Status.FAILED
    [message] = stored(admin)
    assert message.level == Level.WARNING
    assert "Bericht" in message.body and "Connection refused" in message.body


def test_a_message_that_cannot_be_stored_does_not_stop_the_job(admin, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(events, "anotify", broken)
    async_to_sync(events.job_done)("customers", "Kundenimport", "ok", changed=True)


# Long-running timers


@pytest.fixture
def running(admin, task) -> TimeEntry:
    return TimeEntry.objects.create(user=admin, task=task, started_at=timezone.now() - timedelta(hours=11))


def test_long_timer_warns_once(admin, running):
    assert async_to_sync(jobs.notify_long_timers)(timezone.now(), 10) == 1
    assert async_to_sync(jobs.notify_long_timers)(timezone.now(), 10) == 0
    [message] = stored(admin)
    assert message.level == Level.WARNING
    assert message.title == "Dein Timer läuft schon seit 11 Stunden"
    assert "ACME GmbH" in message.body
    # Not again after it was read.
    Message.objects.update(read_at=timezone.now())
    assert async_to_sync(jobs.notify_long_timers)(timezone.now(), 10) == 0


def test_timer_below_the_limit_is_left_alone(admin, running):
    assert async_to_sync(jobs.notify_long_timers)(timezone.now(), 12) == 0


def test_warning_goes_away_when_the_timer_stops(admin, running):
    async_to_sync(jobs.notify_long_timers)(timezone.now(), 10)
    running.ended_at = timezone.now()
    running.save()
    async_to_sync(jobs.notify_long_timers)(timezone.now(), 10)
    assert Message.objects.get().read_at


def test_timer_warning_can_be_turned_off(admin, running):
    from core.models import AppSettings

    AppSettings.load()
    AppSettings.objects.filter(pk=1).update(timer_reminder_hours=0)
    assert async_to_sync(jobs.run_due)(timezone.now()) == {}
    assert not Message.objects.exists()
