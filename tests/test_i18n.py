import re
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest
from asgiref.sync import async_to_sync
from django.conf import settings
from django.urls import reverse
from django.utils import timezone, translation
from django.utils.translation import gettext as _

from accounts.models import User
from core import i18n
from core.models import AppSettings
from customers.models import Customer
from inbox import events
from inbox.models import Message
from mailer import jobs
from mailer.models import MailSettings, OutgoingMail
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

PREFERENCES = {
    "first_name": "Kim",
    "last_name": "",
    "email": "",
    "theme": "system",
    "date_format": "d.m.Y",
    "duration_format": "clock",
    "list_page_size": "25",
    "message_level": "20",
    "message_email_level": "40",
}

# Words that only German pages contain, to notice a text that was left out of the translation.
GERMAN = re.compile(
    r"\b(und|nicht|für|noch|keine?|wird|werden|oder|Einstellungen|Kunden?|Rechnung(?:en)?|Zeiten?|Aufgabe[n]?"
    r"|Speichern|Löschen|Bearbeiten|Übersicht|dein[e]?|Benutzer|Stunden|Abrechnung|Projekte?)\b"
)


@pytest.fixture
def smtp(db) -> MailSettings:
    config = MailSettings.objects.create(pk=1, host="smtp.example.de", from_address="zeit@example.de")
    config.set_password("geheim")
    config.save()
    return config


@pytest.fixture
def kim(user) -> User:
    user.email = "kim@example.de"
    user.save()
    return user


def visible_text(html: str) -> str:
    html = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)
    return re.sub(r"<[^>]+>", "\n", html)


# Which language a request gets


def test_german_is_the_default(client, user):
    response = client.get(reverse("accounts:login"))
    assert response["Content-Language"] == "de"
    assert '<html lang="de"' in response.text
    assert "Anmelden" in response.text


def test_login_page_follows_the_browser(client, user, english):
    response = client.get(reverse("accounts:login"), headers={"Accept-Language": "en-GB,en;q=0.8"})
    assert response["Content-Language"] == "en"
    assert '<html lang="en"' in response.text
    assert "Sign in" in response.text
    assert "Anmelden" not in response.text


def test_unknown_browser_language_gives_german(client, user):
    response = client.get(reverse("accounts:login"), headers={"Accept-Language": "fr"})
    assert response["Content-Language"] == "de"


def test_language_of_the_account_beats_the_browser(client, user, english):
    user.language = "en"
    user.save()
    client.force_login(user)
    response = client.get(reverse("core:dashboard"), headers={"Accept-Language": "de"})
    assert response["Content-Language"] == "en"
    assert "Sign out" in response.text


def test_account_without_a_choice_is_german(client, user):
    assert user.language == "de"
    client.force_login(user)
    assert "Abmelden" in client.get(reverse("core:dashboard")).text


# Choosing the language


def test_account_page_offers_both_languages(client, user):
    client.force_login(user)
    page = client.get(reverse("account:settings")).text
    assert 'name="language"' in page
    assert "Deutsch" in page and "English" in page


def test_choosing_english_in_the_account(client, user, english):
    client.force_login(user)
    response = client.post(reverse("account:settings"), PREFERENCES | {"language": "en"})
    assert response.status_code == 302
    user.refresh_from_db()
    assert user.language == "en"
    assert response.cookies[settings.LANGUAGE_COOKIE_NAME].value == "en"

    # The confirmation and the page are already in the new language.
    page = client.get(response["Location"]).text
    assert "Settings saved." in page
    assert "Einstellungen gespeichert." not in page
    assert "Sign out" in page


def test_the_login_page_keeps_the_language_after_signing_out(client, user, english):
    client.force_login(user)
    client.post(reverse("account:settings"), PREFERENCES | {"language": "en"})
    client.post(reverse("accounts:logout"))
    assert "Sign in" in client.get(reverse("accounts:login")).text


def test_switching_back_to_german(client, user, english):
    user.language = "en"
    user.save()
    client.force_login(user)
    response = client.post(reverse("account:settings"), PREFERENCES | {"language": "de"})
    assert "Einstellungen gespeichert." in client.get(response["Location"]).text
    user.refresh_from_db()
    assert user.language == "de"


def test_an_unknown_language_is_rejected(client, user):
    client.force_login(user)
    response = client.post(reverse("account:settings"), PREFERENCES | {"language": "fr"})
    assert response.status_code == 200
    user.refresh_from_db()
    assert user.language == "de"


def test_language_stays_without_a_value_in_the_form(client, user):
    user.language = "en"
    user.save()
    client.force_login(user)
    assert client.post(reverse("account:settings"), PREFERENCES).status_code == 302
    user.refresh_from_db()
    assert user.language == "en"


# The English interface


def test_main_pages_have_no_german_left(client, user, task, english):
    user.language = "en"
    user.save()
    customer = task.project.customer
    TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=timezone.now() - timedelta(hours=3),
        ended_at=timezone.now() - timedelta(hours=1),
        description="Concept",
    )
    client.force_login(user)
    urls = [
        reverse("core:dashboard"),
        reverse("core:settings"),
        reverse("core:jobs"),
        reverse("core:backups"),
        reverse("customers:list"),
        reverse("customers:edit", args=[customer.pk]),
        reverse("projects:list"),
        reverse("projects:create"),
        reverse("projects:detail", args=[task.project.pk]),
        reverse("projects:task_edit", args=[task.project.pk, task.pk]),
        reverse("projects:templates"),
        reverse("tracking:list"),
        reverse("tracking:create"),
        reverse("tracking:timer_start"),
        reverse("billing:overview"),
        reverse("billing:invoices"),
        reverse("billing:customer", args=[customer.pk]),
        reverse("billing:customer_entries", args=[customer.pk]),
        reverse("billing:agreement_create", args=[customer.pk]),
        reverse("reports:overview"),
        reverse("inbox:all"),
        reverse("inbox:panel"),
        reverse("reminders:list"),
        reverse("reminders:list") + "?view=all",
        reverse("reminders:create"),
        reverse("reminders:create") + f"?project={task.project.pk}",
        reverse("account:settings"),
        reverse("users:list"),
        reverse("mailer:settings"),
    ]
    for tab in ("lexware", "email", "backup"):
        urls.append(reverse("core:settings") + f"?tab={tab}")
    for tab in ("profile", "security", "notifications", "agents"):
        urls.append(reverse("account:settings") + f"?tab={tab}")
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200, url
        leftovers = sorted({m.group(0) for m in GERMAN.finditer(visible_text(response.text))})
        assert not leftovers, (url, leftovers)


def test_customer_portal_in_english(client, task, english):
    customer = task.project.customer
    portal = User.objects.create_user(
        username="acme",
        password="x",
        role=User.Role.CUSTOMER,
        customer=customer,
        language="en",
        portal_contact=True,
    )
    client.force_login(portal)
    for name in ("overview", "entries", "invoices", "contact"):
        response = client.get(reverse(f"portal:{name}"))
        assert response.status_code == 200, name
        leftovers = sorted({m.group(0) for m in GERMAN.finditer(visible_text(response.text))})
        assert not leftovers, (name, leftovers)


def test_validation_messages_follow_the_language(client, user, english):
    user.language = "en"
    user.save()
    client.force_login(user)
    response = client.post(reverse("account:settings"), PREFERENCES | {"email": "no-address"})
    assert "Enter a valid email address." in response.text


# Formats


def test_hours_use_the_decimal_separator_of_the_language():
    from core.templatetags.timefmt import hours

    value = timedelta(hours=2, minutes=45)
    with translation.override("de"):
        assert hours(value, "decimal") == "2,75"
    with translation.override("en"):
        assert hours(value, "decimal") == "2.75"
        assert hours(value, "clock") == "2:45"


def test_dates_follow_the_language(english):
    day = date(2026, 10, 20)
    with translation.override("de"):
        assert (i18n.short_date(day), i18n.full_date(day)) == ("20.10.", "20.10.2026")
    with translation.override("en"):
        assert (i18n.short_date(day), i18n.full_date(day)) == ("20 Oct", "20 Oct 2026")


def test_the_long_date_format_of_an_account_follows_the_language(english):
    with translation.override("de"):
        assert str(i18n.date_format("j. F Y")) == "j. F Y"
    with translation.override("en"):
        assert str(i18n.date_format("j. F Y")) == "j F Y"
        assert str(i18n.datetime_format("j. F Y")) == "j F Y, H:i"
        # The format of an account is left alone otherwise.
        assert str(i18n.date_format("Y-m-d")) == "Y-m-d"


def test_account_dates_use_the_chosen_format_in_english(client, user, english):
    user.language = "en"
    user.date_format = "j. F Y"
    user.save()
    client.force_login(user)
    page = visible_text(client.get(reverse("tracking:list")).text)
    # The long format has no full stop after the day in English: "25 October 2026".
    assert re.search(r"\b\d{1,2} [A-Z][a-z]+ \d{4}\b", page)
    assert not re.search(r"\b\d{1,2}\. [A-Z][a-z]+ \d{4}\b", page)


def test_csv_separator_follows_the_language(client, user, english):
    client.force_login(user)
    assert "Datum;Beginn" in client.get(reverse("reports:entries_csv")).text.replace("﻿", "")
    user.language = "en"
    user.save()
    assert "Date,Start" in client.get(reverse("reports:entries_csv")).text.replace("﻿", "")


# Mails and messages are written in the language of whoever gets them


def test_mail_is_written_in_the_language_of_the_recipient(client, kim, smtp, english):
    kim.language = "en"
    kim.save()
    # The browser asks for German, but the mail is for an account that uses English.
    client.post(
        reverse("accounts:password_forgot"), {"identifier": "kim@example.de"}, headers={"Accept-Language": "de"}
    )
    queued = OutgoingMail.objects.get()
    assert queued.subject == "New password for LexTracker"
    assert "Set a new password" in queued.html
    assert 'lang="en"' in queued.html
    assert "Neues Passwort" not in queued.text + queued.html


def test_german_mail_stays_german(client, kim, smtp):
    client.post(
        reverse("accounts:password_forgot"), {"identifier": "kim@example.de"}, headers={"Accept-Language": "en"}
    )
    queued = OutgoingMail.objects.get()
    assert queued.subject == "Neues Passwort für LexTracker"
    assert "Neues Passwort festlegen" in queued.html


@pytest.mark.django_db(transaction=True)
def test_weekly_report_in_english(kim, task, smtp, english):
    kim.language = "en"
    kim.save()
    start = datetime(2026, 10, 20, 9, tzinfo=timezone.get_current_timezone())
    TimeEntry.objects.create(user=kim, task=task, started_at=start, ended_at=start + timedelta(hours=2.5))
    queued = async_to_sync(jobs.queue_weekly_reports)(datetime(2026, 10, 26, 7, tzinfo=timezone.get_current_timezone()))
    assert queued == 1
    report = OutgoingMail.objects.get()
    assert report.subject == "Your weekly report 19 Oct – 25 Oct 2026"
    assert "Your hours: 2:30" in report.text
    assert "Tue 20 Oct" in report.text
    assert "Hours of all users" not in report.text or "Hours of all users: 2:30" in report.text
    assert "Dein" not in report.text and "Stunden" not in report.text


@pytest.mark.django_db(transaction=True)
def test_timer_reminder_in_english(kim, task, smtp, english):
    kim.language = "en"
    kim.save()
    TimeEntry.objects.create(user=kim, task=task, started_at=timezone.now() - timedelta(hours=11))
    AppSettings.objects.update_or_create(
        pk=1, defaults={"weekly_report_enabled": False, "timer_reminder_hours": 10, "overdue_notice": "off"}
    )
    assert async_to_sync(jobs.run_due)(timezone.now()) == {"timer reminder": 1}
    reminder = OutgoingMail.objects.get()
    assert reminder.subject == "Your timer is still running"
    assert "has been running since" in reminder.text and "11:00 hours" in reminder.text


def test_each_administrator_gets_the_message_in_their_language(kim, english):
    User.objects.create_user(username="mia", password="x", language="en")
    async_to_sync(events.backup_done)("db-2026.sqlite3")
    titles = {message.user.username: message.title for message in Message.objects.select_related("user")}
    assert titles == {"kim": "Datensicherung erstellt", "mia": "Backup created"}


# The English catalog


def catalog_entries() -> list[dict[str, str]]:
    path = Path(settings.LOCALE_PATHS[0]) / "en" / "LC_MESSAGES" / "django.po"
    entries, current = [], {}
    for line in [*path.read_text(encoding="utf-8").split("\n"), ""]:
        if not line.strip():
            if current.get("msgid"):
                entries.append(current)
            current = {}
        elif line.startswith("#,"):
            current["flags"] = line
        elif m := re.match(r'(msgid_plural|msgid|msgstr(?:\[\d\])?)\s+"(.*)"$', line):
            current[m[1]] = m[2]
            current["last"] = m[1]
        elif m := re.match(r'"(.*)"$', line):
            current[current["last"]] = current.get(current["last"], "") + m[1]
    return entries


def test_every_text_has_an_english_translation():
    entries = catalog_entries()
    assert len(entries) > 1000
    untranslated = [e["msgid"][:60] for e in entries if not (e.get("msgstr") or e.get("msgstr[0]"))]
    assert not untranslated
    fuzzy = [e["msgid"][:60] for e in entries if "fuzzy" in e.get("flags", "")]
    assert not fuzzy


def test_translations_keep_their_placeholders():
    pattern = re.compile(r"%\([a-z_0-9]+\)[sd]|%%")
    for entry in catalog_entries():
        pairs = [(entry["msgid"], entry.get("msgstr") or entry["msgstr[0]"])]
        if "msgid_plural" in entry:
            pairs.append((entry["msgid_plural"], entry["msgstr[1]"]))
        for source, translated in pairs:
            assert sorted(pattern.findall(source)) == sorted(pattern.findall(translated)), source


def test_translation_lookup_works_both_ways(english):
    with translation.override("en"):
        assert _("Einstellungen gespeichert.") == "Settings saved."
    with translation.override("de"):
        assert _("Einstellungen gespeichert.") == "Einstellungen gespeichert."


def test_customer_names_and_other_data_are_never_translated(client, user, english):
    Customer.objects.create(name="Offene Rechnungen GmbH")
    user.language = "en"
    user.save()
    client.force_login(user)
    assert "Offene Rechnungen GmbH" in client.get(reverse("customers:list")).text
