import re
import smtplib
import ssl
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from accounts import links, mfa
from accounts.models import LoginLink, User
from billing.models import Invoice
from core.models import AppSettings
from customers.models import Customer
from mailer import jobs, outbox
from mailer.models import MailSettings, OutgoingMail
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

send_due = async_to_sync(outbox.send_due)


@pytest.fixture
def smtp(db) -> MailSettings:
    AppSettings.objects.update_or_create(pk=1, defaults={"app_url": "https://zeit.example.de"})
    config = MailSettings.objects.create(pk=1, host="smtp.example.de", from_address="zeit@example.de")
    config.set_password("smtp-geheim")
    config.save()
    return config


@pytest.fixture
def kim(user) -> User:
    user.email = "kim@example.de"
    user.first_name = "Kim"
    user.save()
    return user


@pytest.fixture
def logged_in(client, kim):
    client.force_login(kim)
    return client


def link_in(text: str) -> str:
    return re.search(r"https://zeit\.example\.de(\S+)", text)[1]


def local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.get_current_timezone())


# SMTP settings and the queue


def test_settings_store_the_password_encrypted(logged_in):
    data = {
        "host": "smtp.example.de",
        "port": 587,
        "security": "starttls",
        "username": "zeit@example.de",
        "password": "smtp-geheim",
        "from_address": "zeit@example.de",
        "from_name": "LexTracker",
    }
    assert logged_in.post(reverse("mailer:settings"), data).status_code == 302
    config = MailSettings.objects.get()
    assert "smtp-geheim" not in config.encrypted_password
    assert config.password == "smtp-geheim"
    assert "smtp-geheim" not in logged_in.get(reverse("mailer:settings")).text

    # Left empty, the stored password stays.
    logged_in.post(reverse("mailer:settings"), data | {"password": ""})
    assert MailSettings.objects.get().password == "smtp-geheim"
    logged_in.post(reverse("mailer:settings"), data | {"password": "", "remove_password": "on"})
    assert MailSettings.objects.get().password == ""


def test_settings_need_a_sender(logged_in):
    response = logged_in.post(reverse("mailer:settings"), {"host": "smtp.example.de", "port": 587, "security": "ssl"})
    assert response.status_code == 200
    assert "Ohne Absenderadresse" in response.text


@pytest.mark.parametrize(
    ("port", "security", "field_error"),
    [
        (587, "ssl", "Port 587 nutzt STARTTLS"),
        (465, "starttls", "Port 465 erwartet SSL/TLS"),
    ],
)
def test_settings_reject_port_and_encryption_that_do_not_fit(logged_in, port, security, field_error):
    data = {"host": "smtp.example.de", "port": port, "security": security, "from_address": "zeit@example.de"}

    response = logged_in.post(reverse("mailer:settings"), data)

    assert response.status_code == 200
    assert field_error in response.text
    assert not MailSettings.objects.get(pk=1).host


@pytest.mark.parametrize(("port", "security"), [(587, "starttls"), (465, "ssl"), (25, "none"), (2525, "ssl")])
def test_settings_accept_fitting_port_and_encryption(logged_in, port, security):
    data = {"host": "smtp.example.de", "port": port, "security": security, "from_address": "zeit@example.de"}
    assert logged_in.post(reverse("mailer:settings"), data).status_code == 302


def describe(exc: Exception, port: int, security: str) -> str:
    return outbox._describe(exc, MailSettings(host="smtp.example.de", port=port, security=security))


def test_wrong_version_number_on_ssl_points_to_starttls():
    exc = ssl.SSLError(1, "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:1082)")
    error = describe(exc, 587, "ssl")
    assert "Port 587" in error and "„STARTTLS“" in error
    assert "SSLError" not in error


def test_starttls_on_the_ssl_port_points_to_ssl():
    error = describe(TimeoutError("timed out"), 465, "starttls")
    assert "Port 465" in error and "„SSL/TLS“" in error
    assert "Port 465" in describe(smtplib.SMTPServerDisconnected("Connection unexpectedly closed"), 465, "starttls")


def test_server_without_starttls_points_to_ssl():
    error = describe(smtplib.SMTPNotSupportedError("STARTTLS extension not supported by server."), 25, "starttls")
    assert "kein STARTTLS" in error and "„SSL/TLS“" in error


def test_other_errors_stay_as_they_are():
    assert describe(smtplib.SMTPAuthenticationError(535, b"no"), 587, "starttls").startswith("SMTPAuthenticationError")
    assert describe(TimeoutError("timed out"), 587, "starttls") == "TimeoutError: timed out"
    assert describe(ssl.SSLError(1, "[SSL: CERTIFICATE_VERIFY_FAILED]"), 465, "ssl").startswith("SSLError")


def test_mail_settings_are_for_admins_only(client, kim):
    kim.role = User.Role.EMPLOYEE
    kim.save()
    client.force_login(kim)
    assert client.get(reverse("mailer:settings")).status_code == 403


def test_test_mail_goes_out_at_once(logged_in, smtp):
    response = logged_in.post(reverse("mailer:test"), {"to": "kim@example.de"}, follow=True)
    assert "Testmail an kim@example.de verschickt" in response.text
    assert len(mail.outbox) == 1
    assert mail.outbox[0].to == ["kim@example.de"]
    assert mail.outbox[0].from_email == '"LexTracker" <zeit@example.de>'
    assert not OutgoingMail.objects.exists()


def test_test_mail_shows_the_server_error(logged_in, smtp, monkeypatch):
    monkeypatch.setattr(outbox, "deliver", lambda config, messages: ["SMTPAuthenticationError: 535"])
    response = logged_in.post(reverse("mailer:test"), {"to": "kim@example.de"}, follow=True)
    assert "nicht verschickt: SMTPAuthenticationError: 535" in response.text


def queue(**kwargs) -> OutgoingMail:
    return async_to_sync(outbox.aqueue)(
        kwargs.pop("kind", OutgoingMail.Kind.WEEKLY_REPORT), "kim@example.de", "Betreff", "test", {}, **kwargs
    )


def test_queue_waits_without_smtp_server():
    MailSettings.objects.create(pk=1, host="smtp.example.de")
    queue()
    assert send_due() == 0
    assert OutgoingMail.objects.get().status == OutgoingMail.Status.PENDING


def test_queue_sends_and_retries(smtp, monkeypatch):
    queued = queue()
    assert send_due() == 1
    queued.refresh_from_db()
    assert queued.status == OutgoingMail.Status.SENT and queued.sent_at
    assert mail.outbox[0].alternatives[0].mimetype == "text/html"

    failing = queue()
    monkeypatch.setattr(outbox, "deliver", lambda config, messages: ["Connection refused"] * len(messages))
    now = timezone.now()
    for attempt, delay in enumerate(outbox.RETRY_DELAYS, start=1):
        send_due(now)
        failing.refresh_from_db()
        assert (failing.status, failing.attempts) == (OutgoingMail.Status.PENDING, attempt)
        assert failing.next_attempt_at == now + delay
        # Not again before the delay is over.
        assert send_due(now + delay - timedelta(seconds=1)) == 0
        now += delay
    send_due(now)
    failing.refresh_from_db()
    assert failing.status == OutgoingMail.Status.FAILED
    assert failing.last_error == "Connection refused"

    assert async_to_sync(outbox.aretry)(failing.pk)
    failing.refresh_from_db()
    assert (failing.status, failing.attempts) == (OutgoingMail.Status.PENDING, 0)


def test_link_mails_expire_and_forget_their_text(smtp):
    expired = queue(kind=OutgoingMail.Kind.LOGIN_LINK, expires_at=timezone.now() - timedelta(minutes=1))
    sent = queue(kind=OutgoingMail.Kind.PASSWORD_RESET)
    send_due()
    expired.refresh_from_db()
    sent.refresh_from_db()
    assert expired.status == OutgoingMail.Status.EXPIRED
    assert sent.status == OutgoingMail.Status.SENT
    assert (expired.text, sent.text, sent.html) == ("", "", "")
    assert len(mail.outbox) == 1


# Password reset


def test_login_page_offers_links_only_with_smtp_server(client, kim):
    page = client.get(reverse("accounts:login")).text
    assert reverse("accounts:password_forgot") not in page
    assert reverse("accounts:login_link_request") not in page

    MailSettings.objects.update_or_create(pk=1, defaults={"host": "smtp.example.de", "from_address": "zeit@example.de"})
    page = client.get(reverse("accounts:login")).text
    assert reverse("accounts:password_forgot") in page
    assert reverse("accounts:login_link_request") in page

    AppSettings.objects.update_or_create(pk=1, defaults={"login_link_enabled": False})
    assert reverse("accounts:login_link_request") not in client.get(reverse("accounts:login")).text


def test_password_reset(client, kim, smtp):
    response = client.post(reverse("accounts:password_forgot"), {"identifier": "KIM@example.de"})
    assert "Schau in dein Postfach" in response.text
    queued = OutgoingMail.objects.get()
    assert (queued.kind, queued.to, queued.user) == (OutgoingMail.Kind.PASSWORD_RESET, "kim@example.de", kim)
    url = link_in(queued.text)

    assert "Neues Passwort" in client.get(url).text
    data = {"new_password1": "ganz-neu-2026!", "new_password2": "ganz-neu-2026!"}
    response = client.post(url, data)
    assert response.status_code == 302
    kim.refresh_from_db()
    assert kim.check_password("ganz-neu-2026!")
    # Works only once.
    assert client.get(url).status_code == 400


def test_password_reset_answers_the_same_for_unknown_accounts(client, kim, smtp):
    def answer(identifier: str) -> str:
        page = client.post(reverse("accounts:password_forgot"), {"identifier": identifier}).text
        return re.sub(r"csrfToken.*", "", page.replace(identifier, "X"), flags=re.IGNORECASE)

    assert answer("kim") == answer("niemand")
    assert OutgoingMail.objects.count() == 1


def test_password_reset_link_expires_after_an_hour(client, kim, smtp, monkeypatch):
    client.post(reverse("accounts:password_forgot"), {"identifier": "kim"})
    url = link_in(OutgoingMail.objects.get().text)
    later = datetime.now() + timedelta(minutes=links.RESET_MINUTES + 1)
    monkeypatch.setattr(links.reset_tokens, "_now", lambda: later)
    assert client.get(url).status_code == 400


def test_link_requests_count_towards_the_login_rate_limit(client, kim, smtp):
    AppSettings.objects.update_or_create(pk=1, defaults={"login_max_attempts": 3})
    for _ in range(3):
        client.post(reverse("accounts:password_forgot"), {"identifier": "kim"})
    response = client.post(reverse("accounts:login_link_request"), {"identifier": "kim"})
    assert response.status_code == 429
    assert OutgoingMail.objects.count() == links.MAX_LINKS_PER_ACCOUNT


def test_one_account_gets_only_a_few_links(client, kim, smtp):
    AppSettings.objects.update_or_create(pk=1, defaults={"login_max_attempts": 0})
    for _ in range(links.MAX_LINKS_PER_ACCOUNT + 2):
        client.post(reverse("accounts:login_link_request"), {"identifier": "kim"})
    assert OutgoingMail.objects.count() == links.MAX_LINKS_PER_ACCOUNT


def test_no_links_without_smtp_server(client, kim):
    assert "verschickt keine E-Mails" in client.get(reverse("accounts:password_forgot")).text
    client.post(reverse("accounts:password_forgot"), {"identifier": "kim"})
    assert client.get(reverse("accounts:login_link_request")).status_code == 302
    assert not OutgoingMail.objects.exists()


# Login link


def request_login_link(client) -> str:
    client.post(reverse("accounts:login_link_request"), {"identifier": "kim"})
    return link_in(OutgoingMail.objects.get(kind=OutgoingMail.Kind.LOGIN_LINK).text)


def test_login_link_signs_in_once(client, kim, smtp):
    url = request_login_link(client)
    assert LoginLink.objects.get().key_hash not in url

    # Opening the link (or a mail scanner opening it) does not use it up.
    assert "Jetzt anmelden" in client.get(url).text
    assert "Jetzt anmelden" in client.get(url).text
    assert client.get(reverse("core:dashboard")).status_code == 302

    response = client.post(url)
    assert response.url == reverse("core:dashboard")
    assert client.get(reverse("core:dashboard")).status_code == 200

    client.logout()
    assert client.post(url).status_code == 400
    assert client.get(url).status_code == 400


def test_login_link_expires(client, kim, smtp):
    url = request_login_link(client)
    LoginLink.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
    assert client.post(url).status_code == 400
    assert client.get(reverse("core:dashboard")).status_code == 302


def test_login_link_does_not_work_for_deactivated_users(client, kim, smtp):
    url = request_login_link(client)
    User.objects.filter(pk=kim.pk).update(is_active=False)
    assert client.post(url).status_code == 400


def test_login_link_still_asks_for_the_second_factor(client, kim, smtp):
    device = mfa.pending_device(kim)
    device.confirmed = True
    device.save()
    url = request_login_link(client)

    response = client.post(url)
    assert response.url.startswith(reverse("accounts:login_code"))
    assert client.get(reverse("core:dashboard")).status_code == 302


# Weekly report and timer reminder


def test_last_weekly_slot():
    # 2026-10-26 is a Monday.
    assert jobs.last_weekly_slot(local(26, 7), 0, time(7)) == local(26, 7)
    assert jobs.last_weekly_slot(local(26, 6, 59), 0, time(7)) == local(19, 7)
    assert jobs.last_weekly_slot(local(30, 12), 4, time(17)) == local(23, 17)


def test_weekly_report_due_once_and_not_days_late():
    app_settings = AppSettings(weekly_report_weekday=0, weekly_report_time=time(7))
    assert jobs.weekly_report_due(local(26, 7, 5), app_settings) == local(26, 7)
    app_settings.weekly_report_at = local(26, 7, 5)
    assert jobs.weekly_report_due(local(26, 7, 6), app_settings) is None
    # Missed by more than a day: waits for the next week.
    app_settings.weekly_report_at = None
    assert jobs.weekly_report_due(local(28, 9), app_settings) is None
    app_settings.weekly_report_enabled = False
    assert jobs.weekly_report_due(local(26, 7, 5), app_settings) is None


def book(user, task, start: datetime, hours: float, **kwargs) -> TimeEntry:
    return TimeEntry.objects.create(
        user=user, task=task, started_at=start, ended_at=start + timedelta(hours=hours), **kwargs
    )


@pytest.mark.django_db(transaction=True)
def test_weekly_report_goes_to_users_who_booked_time(kim, task, smtp):
    employee = User.objects.create_user("mia", "mia@example.de", "x", role=User.Role.EMPLOYEE)
    idle = User.objects.create_user("ole", "ole@example.de", "x", role=User.Role.EMPLOYEE)
    opted_out = User.objects.create_user("eva", "eva@example.de", "x", role=User.Role.EMPLOYEE, weekly_report=False)
    User.objects.create_user(
        "acme", "acme@example.de", "x", role=User.Role.CUSTOMER, customer=Customer.objects.create(name="ACME")
    )
    book(kim, task, local(20, 9), 2.5)
    book(employee, task, local(21, 9), 1)
    book(opted_out, task, local(21, 9), 1)
    book(kim, task, local(26, 6), 1)  # on the day of the report: belongs to next week

    queued = async_to_sync(jobs.queue_weekly_reports)(local(26, 7))
    assert queued == 2
    reports = {m.to: m for m in OutgoingMail.objects.filter(kind=OutgoingMail.Kind.WEEKLY_REPORT)}
    assert set(reports) == {"kim@example.de", "mia@example.de"}
    assert idle.email not in reports

    text = reports["kim@example.de"].text
    assert "19.10. – 25.10.2026" in reports["kim@example.de"].subject
    assert "Deine Stunden: 2:30" in text
    assert "Di 20.10.  2:30" in text
    assert "ACME GmbH · Website: 2:30" in text
    assert "Stunden aller Benutzer: 4:30" in text
    assert "https://zeit.example.de/reports/?from=2026-10-19&to=2026-10-25" in text
    assert "Überblick" not in reports["mia@example.de"].text

    # Only once per week.
    assert async_to_sync(jobs.queue_weekly_reports)(local(26, 8)) == 0


@pytest.mark.django_db(transaction=True)
def test_timer_reminder_once_per_running_timer(kim, task, smtp):
    TimeEntry.objects.create(user=kim, task=task, started_at=timezone.now() - timedelta(hours=11))
    employee = User.objects.create_user("mia", "mia@example.de", "x", role=User.Role.EMPLOYEE, timer_reminder=False)
    TimeEntry.objects.create(user=employee, task=task, started_at=timezone.now() - timedelta(hours=11))
    short = User.objects.create_user("ole", "ole@example.de", "x", role=User.Role.EMPLOYEE)
    TimeEntry.objects.create(user=short, task=task, started_at=timezone.now() - timedelta(hours=2))

    run_due = async_to_sync(jobs.run_due)
    AppSettings.objects.update_or_create(
        pk=1, defaults={"weekly_report_enabled": False, "timer_reminder_hours": 10, "overdue_notice": "off"}
    )
    assert run_due(timezone.now()) == {"timer reminder": 1}
    reminder = OutgoingMail.objects.get()
    assert reminder.to == "kim@example.de"
    assert "Entwicklung" in reminder.text and "11:00 Stunden" in reminder.text
    assert run_due(timezone.now()) == {"timer reminder": 0}


@pytest.mark.django_db(transaction=True)
def test_no_reports_or_reminders_without_smtp_server(kim, task):
    TimeEntry.objects.create(user=kim, task=task, started_at=timezone.now() - timedelta(hours=24))
    assert async_to_sync(jobs.run_due)(timezone.now()) == {}
    assert not OutgoingMail.objects.exists()


def test_account_page_has_mail_preferences(logged_in, kim):
    data = {
        "first_name": "Kim",
        "email": "kim@example.de",
        "theme": "system",
        "date_format": "d.m.Y",
        "duration_format": "clock",
        "list_page_size": 50,
        "message_level": 20,
        "message_email_level": 40,
        "timer_reminder": "on",
    }
    assert logged_in.post(reverse("account:settings"), data).status_code == 302
    kim.refresh_from_db()
    assert (kim.weekly_report, kim.timer_reminder) == (False, True)


# Overdue invoices


@pytest.fixture
def overdue(kim, task) -> Invoice:
    customer = task.project.customer
    customer.email = "buchhaltung@acme.example"
    customer.save()
    return Invoice.objects.create(
        customer=customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        total_net=Decimal("200.00"),
        lexware_id=uuid.uuid4(),
        status=Invoice.Status.OVERDUE,
        voucher_number="RE0042",
        voucher_date=date(2026, 10, 1),
        due_date=timezone.localdate() - timedelta(days=4),
        open_amount=Decimal("1238.00"),
        status_synced_at=timezone.now(),
    )


def overdue_notices(**app_settings) -> int:
    AppSettings.objects.update_or_create(
        pk=1, defaults={"weekly_report_enabled": False, "timer_reminder_hours": 0, **app_settings}
    )
    return async_to_sync(jobs.run_due)(timezone.now()).get("overdue invoice", 0)


@pytest.mark.django_db(transaction=True)
def test_overdue_invoice_notifies_admins_once(overdue, smtp):
    User.objects.create_user("mia", "mia@example.de", "x", role=User.Role.EMPLOYEE)
    assert overdue_notices() == 1
    notice = OutgoingMail.objects.get()
    assert notice.to == "kim@example.de"
    assert notice.subject == "Rechnung RE0042 von ACME GmbH ist überfällig"
    assert "seit 4 Tagen überfällig" in notice.text and "1.238,00 €" in notice.text
    assert "An den Kunden ging keine Erinnerung." in notice.text
    assert f"https://app.lexware.de/permalink/invoices/view/{overdue.lexware_id}" in notice.text
    assert overdue_notices() == 0

    # A new due date is a new notice.
    Invoice.objects.filter(pk=overdue.pk).update(due_date=overdue.due_date - timedelta(days=1))
    assert overdue_notices() == 1


@pytest.mark.django_db(transaction=True)
def test_overdue_invoice_reminds_the_customer(overdue, smtp):
    assert overdue_notices(overdue_notice="customer") == 2
    reminder = OutgoingMail.objects.get(to="buchhaltung@acme.example")
    assert reminder.subject == "Zahlungserinnerung zur Rechnung RE0042"
    assert "vom 01.10.2026" in reminder.text and "1.238,00 €" in reminder.text
    assert "Viele Grüße\nLexTracker" in reminder.text
    assert "lexware.de" not in reminder.text + reminder.html
    notice = OutgoingMail.objects.get(to="kim@example.de")
    assert "Zahlungserinnerung an buchhaltung@acme.example" in notice.text
    assert overdue_notices(overdue_notice="customer") == 0


@pytest.mark.django_db(transaction=True)
def test_overdue_notice_waits_and_skips_unclear_invoices(overdue, smtp):
    # Not before the days after the due date have passed.
    assert overdue_notices(overdue_notice_days=5) == 0
    # Not if the status was not checked with Lexware lately; the invoice may be paid by now.
    Invoice.objects.filter(pk=overdue.pk).update(status_synced_at=timezone.now() - timedelta(days=2))
    assert overdue_notices() == 0
    # Not for invoices overdue long before the notice was turned on.
    Invoice.objects.filter(pk=overdue.pk).update(
        status_synced_at=timezone.now(), due_date=timezone.localdate() - timedelta(days=30)
    )
    assert overdue_notices() == 0
    # Not for paid ones, and not at all when turned off.
    Invoice.objects.filter(pk=overdue.pk).update(due_date=overdue.due_date, status=Invoice.Status.PAID)
    assert overdue_notices() == 0
    Invoice.objects.filter(pk=overdue.pk).update(status=Invoice.Status.OVERDUE)
    assert overdue_notices(overdue_notice="off") == 0
    assert not OutgoingMail.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_customer_without_email_gets_no_reminder(overdue, smtp):
    Customer.objects.filter(pk=overdue.customer_id).update(email="")
    assert overdue_notices(overdue_notice="customer") == 1
    assert "keine E-Mail-Adresse in Lexware" in OutgoingMail.objects.get().text


# Invitations


def test_new_user_gets_the_invitation_by_mail(logged_in, kim, smtp):
    response = logged_in.post(
        reverse("users:create"),
        {"username": "mia", "first_name": "Mia", "email": "mia@example.de", "role": User.Role.EMPLOYEE},
        follow=True,
    )
    assert "Einladung an mia@example.de ist unterwegs" in response.text
    invitation = OutgoingMail.objects.get()
    assert (invitation.kind, invitation.to) == (OutgoingMail.Kind.INVITATION, "mia@example.de")
    assert "Kim hat dir einen Zugang" in invitation.text and "„mia“" in invitation.text
    assert invitation.expires_at > timezone.now() + timedelta(days=6)
    link = link_in(invitation.text)

    send_due()
    invitation.refresh_from_db()
    assert invitation.text == ""  # The link sets a password, so no copy stays in the database.

    logged_in.logout()
    data = {"new_password1": "Sehr-sicher-42", "new_password2": "Sehr-sicher-42"}
    assert logged_in.post(link, data).url.startswith(reverse("accounts:login"))
    assert User.objects.get(username="mia").check_password("Sehr-sicher-42")


def test_invitation_by_mail_can_be_turned_off(logged_in, kim, smtp):
    AppSettings.objects.update_or_create(pk=1, defaults={"invite_by_mail": False})
    logged_in.post(reverse("users:create"), {"username": "mia", "email": "mia@example.de", "role": User.Role.EMPLOYEE})
    assert not OutgoingMail.objects.exists()

    # It can still be sent from the invitation page.
    mia = User.objects.get(username="mia")
    page = logged_in.get(reverse("users:invite", args=[mia.pk])).text
    assert "Per E-Mail an mia@example.de schicken" in page
    assert "https://zeit.example.de/accounts/invite/" in page
    logged_in.post(reverse("users:invite", args=[mia.pk]))
    assert OutgoingMail.objects.get().to == "mia@example.de"


def test_no_invitation_mail_without_smtp_server_or_address(logged_in, kim):
    logged_in.post(reverse("users:create"), {"username": "mia", "email": "mia@example.de", "role": User.Role.EMPLOYEE})
    mia = User.objects.get(username="mia")
    assert "Per E-Mail" not in logged_in.get(reverse("users:invite", args=[mia.pk])).text
    logged_in.post(reverse("users:invite", args=[mia.pk]))
    assert not OutgoingMail.objects.exists()
