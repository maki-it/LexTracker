import functools
import json
import uuid
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from asgiref.sync import async_to_sync
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice
from core import scheduler
from inbox import jobs as inbox_jobs
from inbox.levels import Level
from inbox.models import Message
from inbox.service import Audience, anotify, aresolve
from push import jobs, service, webpush
from push.models import PushKeys, PushSubscription
from push.topics import Topic, topic_of
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

notify = async_to_sync(anotify)


class Browser:
    """A browser with a push subscription: it has the keys to read what is sent to it."""

    def __init__(self):
        self.private = webpush.new_private_key()
        self.p256dh = webpush.b64encode(webpush.public_bytes(self.private))
        self.auth = webpush.b64encode(b"0123456789abcdef")
        self.endpoint = f"https://push.example.net/send/{uuid.uuid4()}"


class PushService:
    """Stands in for the push services of the browsers: keeps what was sent and answers with a status."""

    def __init__(self, status: int = 201):
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status)

    def messages(self, browser: Browser) -> list[dict]:
        return [
            json.loads(webpush.decrypt(r.content, browser.private, browser.auth))
            for r in self.requests
            if str(r.url) == browser.endpoint
        ]


@pytest.fixture
def push(monkeypatch) -> PushService:
    fake = PushService()
    monkeypatch.setattr(
        service.httpx, "AsyncClient", functools.partial(httpx.AsyncClient, transport=httpx.MockTransport(fake))
    )
    return fake


@pytest.fixture
def admin(user) -> User:
    return user


@pytest.fixture
def employee(db) -> User:
    return User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)


def subscribe(user: User, topics: list[str] | None = None, name: str = "Handy") -> tuple[Browser, PushSubscription]:
    browser = Browser()
    values = {} if topics is None else {"topics": topics}
    sub = PushSubscription.objects.create(
        user=user, endpoint=browser.endpoint, p256dh=browser.p256dh, auth=browser.auth, name=name, **values
    )
    return browser, sub


# The protocol


def test_a_message_can_be_read_by_the_browser_it_is_made_for():
    browser = Browser()
    body = webpush.encrypt(b'{"title":"Hallo"}', browser.p256dh, browser.auth)

    assert webpush.decrypt(body, browser.private, browser.auth) == b'{"title":"Hallo"}'
    # Salt, record size, length of the key, the key (65 bytes), then the ciphertext.
    assert int.from_bytes(body[16:20], "big") == webpush.RECORD_SIZE and body[20] == 65


def test_nobody_else_can_read_it():
    body = webpush.encrypt(b"geheim", Browser().p256dh, Browser().auth)
    other = Browser()

    with pytest.raises(InvalidTag):
        webpush.decrypt(body, other.private, other.auth)


def test_the_vapid_signature_proves_the_sender():
    private = webpush.new_private_key()
    header = webpush.vapid_header("https://push.example.net/send/abc", private, "https://zeit.example.de")

    scheme, rest = header.split(" ", 1)
    token = dict(part.strip().split("=", 1) for part in rest.split(","))
    head, claims, signature = token["t"].split(".")
    assert scheme == "vapid" and token["k"] == webpush.b64encode(webpush.public_bytes(private))
    assert json.loads(webpush.b64decode(claims)) | {"exp": 0} == {
        "aud": "https://push.example.net",
        "exp": 0,
        "sub": "https://zeit.example.de",
    }
    raw = webpush.b64decode(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    private.public_key().verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))


def test_the_key_is_made_once_and_stored_encrypted():
    first = async_to_sync(service.aload_keys)()
    second = async_to_sync(service.aload_keys)()

    assert first[1] == second[1] == PushKeys.objects.get().public_key
    assert "PRIVATE KEY" not in PushKeys.objects.get().encrypted_private_key


def test_a_key_that_cannot_be_read_anymore_is_replaced_and_the_subscriptions_with_it(admin):
    _, old = async_to_sync(service.aload_keys)()
    subscribe(admin)
    PushKeys.objects.update(encrypted_private_key="not-decryptable")

    _, new = async_to_sync(service.aload_keys)()

    assert new != old
    assert not PushSubscription.objects.exists()


# Which message goes to which topic


def test_messages_are_sorted_into_topics():
    assert topic_of("reminder.due", Level.INFO) == Topic.REMINDER
    assert topic_of("timer.long", Level.WARNING) == Topic.TIMER_LONG
    assert topic_of("invoice.overdue", Level.WARNING) == Topic.OVERDUE_INVOICE
    assert topic_of("backup.failed", Level.CRITICAL) == Topic.CRITICAL
    assert topic_of("customers.failed", Level.WARNING) == Topic.WARNING
    assert topic_of("backup.done", Level.INFO) is None
    assert topic_of("backup.done", Level.DEBUG) is None


def test_a_new_device_gets_reminders_and_critical_messages(admin):
    _, sub = subscribe(admin)

    assert set(sub.topics) == {Topic.REMINDER, Topic.CRITICAL}


# Pushing messages


def test_a_critical_message_reaches_the_devices_that_want_it(admin, employee, push):
    phone, _ = subscribe(admin)
    desktop, _ = subscribe(admin, [Topic.REMINDER], name="Rechner")
    other, _ = subscribe(employee)

    notify(Level.CRITICAL, "backup.failed", "Datensicherung fehlgeschlagen", "Platte voll", url="/settings/backups/")

    [message] = push.messages(phone)
    assert message["title"] == "Datensicherung fehlgeschlagen"
    assert message["body"] == "Platte voll"
    assert message["url"] == "/settings/backups/"
    assert message["icon"].endswith(".png")
    assert not push.messages(desktop)
    # The employee is not an administrator: the message is not for them.
    assert not push.messages(other)


def test_a_reminder_is_pushed_to_its_user_whatever_the_level(employee, push):
    browser, _ = subscribe(employee)

    notify(Level.INFO, "reminder.due", "Angebot nachfassen", to=employee, mail=False)

    assert [m["title"] for m in push.messages(browser)] == ["Angebot nachfassen"]


def test_info_and_debug_messages_are_never_pushed(admin, push):
    subscribe(admin, [t.value for t in Topic])

    notify(Level.INFO, "x.done", "Fertig")
    notify(Level.DEBUG, "y.done", "Fertig")

    assert not push.requests


def test_warnings_and_the_rest_are_opt_in(admin, push):
    browser, sub = subscribe(admin)
    notify(Level.WARNING, "customers.failed", "Kundenimport fehlgeschlagen", dedupe_key="a")
    assert not push.requests

    sub.topics = [Topic.WARNING]
    sub.save()
    notify(Level.WARNING, "invoices.failed", "Abgleich fehlgeschlagen", dedupe_key="b")

    assert [m["title"] for m in push.messages(browser)] == ["Abgleich fehlgeschlagen"]


def test_a_repeated_message_is_pushed_once(admin, push):
    browser, _ = subscribe(admin)

    for _ in range(3):
        notify(Level.CRITICAL, "backup.failed", "Fehler", dedupe_key="backup")

    assert len(push.messages(browser)) == 1


def test_a_message_that_becomes_critical_is_pushed_again(admin, push):
    browser, _ = subscribe(admin, [Topic.CRITICAL])

    for _ in range(3):
        notify(Level.WARNING, "customers.failed", "Fehler", dedupe_key="k", escalate_after=3)

    assert len(push.messages(browser)) == 1


def test_a_device_that_is_gone_is_forgotten(admin, push):
    push.status = 410
    subscribe(admin)

    notify(Level.CRITICAL, "backup.failed", "Fehler")

    assert not PushSubscription.objects.exists()
    assert Message.objects.count() == 1


def test_a_push_service_that_fails_does_not_stop_the_message(admin, push):
    push.status = 503
    _, sub = subscribe(admin)

    notify(Level.CRITICAL, "backup.failed", "Fehler")

    assert Message.objects.count() == 1
    sub.refresh_from_db()
    assert sub.last_used_at is None


def test_a_broken_push_does_not_stop_the_message(admin, monkeypatch):
    async def broken(*args, **kwargs):
        raise RuntimeError("no network")

    subscribe(admin)
    monkeypatch.setattr(service, "apush", broken)

    notify(Level.CRITICAL, "backup.failed", "Fehler")

    assert Message.objects.count() == 1


def test_delivery_is_noted(admin, push):
    _, sub = subscribe(admin)

    notify(Level.CRITICAL, "backup.failed", "Fehler")

    sub.refresh_from_db()
    assert sub.last_used_at is not None
    request = push.requests[0]
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["authorization"].startswith("vapid t=")


# Overdue invoices


@pytest.fixture
def overdue(task) -> Invoice:
    return Invoice.objects.create(
        customer=task.project.customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        total_net=Decimal("200.00"),
        lexware_id=uuid.uuid4(),
        status=Invoice.Status.OVERDUE,
        voucher_number="RE0042",
        voucher_date=date(2026, 10, 1),
        due_date=timezone.localdate() - timedelta(days=2),
        open_amount=Decimal("1238.00"),
        status_synced_at=timezone.now(),
    )


def announce_overdue() -> int:
    return async_to_sync(inbox_jobs.notify_overdue_invoices)(timezone.now())


def test_an_overdue_invoice_is_announced_once_to_the_administrators(admin, employee, overdue):
    assert announce_overdue() == 1
    assert announce_overdue() == 0

    [message] = Message.objects.all()
    assert message.user == admin
    assert (message.level, message.kind) == (Level.WARNING, "invoice.overdue")
    assert message.title == "Rechnung RE0042 von ACME GmbH ist überfällig"
    assert "1.238,00 €" in message.body
    assert message.url == reverse("billing:invoices") + "?status=overdue"
    # Not again once it was read.
    Message.objects.update(read_at=timezone.now())
    assert announce_overdue() == 0


def test_old_or_unchecked_invoices_are_not_announced(admin, overdue):
    overdue.due_date = timezone.localdate() - timedelta(days=30)
    overdue.save()
    assert announce_overdue() == 0

    overdue.due_date = timezone.localdate() - timedelta(days=2)
    overdue.status_synced_at = timezone.now() - timedelta(days=3)
    overdue.save()
    assert announce_overdue() == 0


def test_the_message_goes_away_when_the_invoice_is_paid(admin, overdue):
    announce_overdue()
    overdue.status = Invoice.Status.PAID
    overdue.save()

    announce_overdue()

    assert Message.objects.get().read_at is not None


def test_overdue_invoices_are_pushed_only_to_those_who_subscribed(admin, overdue, push):
    wanting, _ = subscribe(admin, [Topic.OVERDUE_INVOICE])
    default, _ = subscribe(admin)

    announce_overdue()

    assert [m["title"] for m in push.messages(wanting)] == ["Rechnung RE0042 von ACME GmbH ist überfällig"]
    assert not push.messages(default)


def test_overdue_invoices_are_checked_by_the_scheduler_job(admin, overdue):
    assert async_to_sync(inbox_jobs.run_due)(timezone.now()) == {"overdue invoice": 1, "long timer": 0}


# The running timer


@pytest.fixture
def running(admin, task) -> TimeEntry:
    return TimeEntry.objects.create(user=admin, task=task, started_at=timezone.now() - timedelta(minutes=5))


def sync_timers() -> int:
    return async_to_sync(jobs.sync_timers)(timezone.now())


def test_the_running_timer_is_shown_on_the_devices_that_want_it(admin, running, push):
    phone, sub = subscribe(admin, [Topic.TIMER_LIVE])
    desktop, _ = subscribe(admin)

    assert sync_timers() == 1
    assert sync_timers() == 0

    [message] = push.messages(phone)
    assert (message["kind"], message["title"]) == ("timer", "Timer läuft")
    assert message["body"] == "ACME GmbH · Website · Entwicklung"
    assert message["since"] == int(running.started_at.timestamp() * 1000)
    assert not push.messages(desktop)
    sub.refresh_from_db()
    assert sub.timer_shown == running.pk


def test_a_stopped_timer_is_taken_off_with_its_duration(admin, running, push):
    phone, sub = subscribe(admin, [Topic.TIMER_LIVE])
    sync_timers()
    running.started_at = timezone.now() - timedelta(minutes=95)
    running.ended_at = timezone.now()
    running.save()

    assert sync_timers() == 1

    last = push.messages(phone)[-1]
    assert (last["kind"], last["title"]) == ("timer-end", "Timer gestoppt")
    assert last["body"] == "ACME GmbH · Website · Entwicklung · 1:35"
    sub.refresh_from_db()
    assert sub.timer_shown is None
    assert sync_timers() == 0


def test_a_timer_that_was_deleted_is_taken_off_too(admin, running, push):
    phone, _ = subscribe(admin, [Topic.TIMER_LIVE])
    sync_timers()
    running.delete()

    sync_timers()

    assert push.messages(phone)[-1]["kind"] == "timer-end"


def test_a_new_timer_replaces_the_old_one(admin, running, task, push):
    phone, sub = subscribe(admin, [Topic.TIMER_LIVE])
    sync_timers()
    running.ended_at = timezone.now()
    running.save()
    second = TimeEntry.objects.create(user=admin, task=task, started_at=timezone.now())

    sync_timers()

    assert push.messages(phone)[-1]["kind"] == "timer"
    sub.refresh_from_db()
    assert sub.timer_shown == second.pk


def test_turning_the_topic_off_takes_the_timer_off(admin, running, push):
    phone, sub = subscribe(admin, [Topic.TIMER_LIVE])
    sync_timers()
    sub.refresh_from_db()
    sub.topics = []
    sub.save()

    sync_timers()

    assert push.messages(phone)[-1]["kind"] == "timer-end"


def test_nothing_happens_without_devices_that_show_the_timer(admin, running, push):
    subscribe(admin)

    assert sync_timers() == 0
    assert not push.requests


def test_the_scheduler_has_a_loop_for_the_timer():
    assert scheduler.PUSH_TIMER_INTERVAL == 5
    assert callable(scheduler.show_timers)


# The account page and the endpoints


@pytest.fixture
def logged_in(client, admin):
    client.force_login(admin)
    return client


def post_json(client, url, body):
    return client.post(url, json.dumps(body), content_type="application/json")


def test_the_service_worker_may_control_the_whole_app(logged_in):
    response = logged_in.get(reverse("push:sw"))

    assert response.status_code == 200
    assert response["Service-Worker-Allowed"] == "/"
    assert response["Cache-Control"] == "no-cache"
    assert response["Content-Type"].startswith("text/javascript")
    assert b'addEventListener("push"' in response.content


def test_the_public_key_is_the_one_notifications_are_signed_with(logged_in):
    key = logged_in.get(reverse("push:key")).json()["key"]

    assert key == PushKeys.objects.get().public_key
    assert len(webpush.b64decode(key)) == 65


def test_a_browser_can_subscribe(logged_in, admin):
    browser = Browser()

    response = post_json(
        logged_in,
        reverse("push:subscribe"),
        {"endpoint": browser.endpoint, "keys": {"p256dh": browser.p256dh, "auth": browser.auth}, "name": "Mein Handy"},
    )

    assert response.status_code == 200
    sub = PushSubscription.objects.get()
    assert (sub.user, sub.name, sub.endpoint) == (admin, "Mein Handy", browser.endpoint)
    assert set(sub.topics) == {Topic.REMINDER, Topic.CRITICAL}


def test_subscribing_again_keeps_the_choices(logged_in, admin):
    browser, sub = subscribe(admin, [Topic.TIMER_LIVE])

    post_json(
        logged_in,
        reverse("push:subscribe"),
        {"endpoint": browser.endpoint, "keys": {"p256dh": "neu", "auth": "neu"}, "name": ""},
    )

    sub.refresh_from_db()
    assert (sub.topics, sub.p256dh, sub.name) == ([Topic.TIMER_LIVE], "neu", "Handy")


def test_a_browser_that_changes_the_account_starts_afresh(client, admin, employee):
    browser, sub = subscribe(admin, [Topic.TIMER_LIVE])
    client.force_login(employee)

    post_json(
        client,
        reverse("push:subscribe"),
        {"endpoint": browser.endpoint, "keys": {"p256dh": browser.p256dh, "auth": browser.auth}},
    )

    sub.refresh_from_db()
    assert sub.user == employee
    assert set(sub.topics) == {Topic.REMINDER, Topic.CRITICAL}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"endpoint": "http://push.example.net/x", "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": "https://push.example.net/x", "keys": {"p256dh": "a"}},
        {"endpoint": "https://push.example.net/" + "x" * 3000, "keys": {"p256dh": "a", "auth": "b"}},
        {"endpoint": 5, "keys": {"p256dh": "a", "auth": "b"}},
    ],
)
def test_a_made_up_subscription_is_refused(logged_in, body):
    assert post_json(logged_in, reverse("push:subscribe"), body).status_code == 400
    assert not PushSubscription.objects.exists()


def test_push_needs_a_login(client):
    assert client.post(reverse("push:subscribe"), "{}", content_type="application/json").status_code == 302
    assert client.get(reverse("push:key")).status_code == 302


def test_customers_have_no_push(client, task):
    customer = User.objects.create_user(
        username="acme", password="geheim-123", role=User.Role.CUSTOMER, customer=task.project.customer
    )
    client.force_login(customer)

    assert client.get(reverse("push:key")).status_code == 403
    assert "Push-Benachrichtigungen" not in client.get(reverse("account:settings")).content.decode()


def test_the_choices_of_a_device_are_saved(logged_in, admin):
    _, sub = subscribe(admin)

    response = logged_in.post(
        reverse("push:topics", args=[sub.pk]),
        {"topics": [Topic.WARNING, Topic.TIMER_LIVE, "unbekannt"], "name": "Pixel"},
    )

    assert response.status_code == 302 and response.url.endswith("tab=notifications")
    sub.refresh_from_db()
    assert (sub.topics, sub.name) == ([Topic.WARNING, Topic.TIMER_LIVE], "Pixel")


def test_employees_cannot_pick_what_is_for_administrators(client, employee):
    _, sub = subscribe(employee)
    client.force_login(employee)

    client.post(reverse("push:topics", args=[sub.pk]), {"topics": [Topic.OVERDUE_INVOICE, Topic.REMINDER]})

    sub.refresh_from_db()
    assert sub.topics == [Topic.REMINDER]


def test_nobody_changes_the_devices_of_somebody_else(client, admin, employee):
    _, sub = subscribe(admin)
    client.force_login(employee)

    for name in ("topics", "test", "remove"):
        assert client.post(reverse(f"push:{name}", args=[sub.pk])).status_code == 404
    assert PushSubscription.objects.filter(pk=sub.pk).exists()


def test_a_device_can_be_removed(logged_in, admin):
    _, sub = subscribe(admin)

    assert logged_in.post(reverse("push:remove", args=[sub.pk])).status_code == 302
    assert not PushSubscription.objects.exists()


def test_a_test_message_is_sent_to_the_device(logged_in, admin, push):
    browser, sub = subscribe(admin, [])

    response = logged_in.post(reverse("push:test", args=[sub.pk]))

    assert response.status_code == 302
    assert [m["title"] for m in push.messages(browser)] == ["Test"]


def test_the_account_page_lists_the_devices_and_the_topics(logged_in, admin):
    subscribe(admin, [Topic.REMINDER], name="Pixel 9")

    page = logged_in.get(reverse("account:settings") + "?tab=notifications").content.decode()

    assert "Pixel 9" in page
    assert "Fällige Erinnerungen" in page and "Überfällige Rechnungen" in page
    assert 'value="reminder" class="mt-0.5" checked' in page
    assert 'value="critical" class="mt-0.5">' in page


def test_employees_do_not_see_what_is_only_for_administrators(client, employee):
    subscribe(employee)
    client.force_login(employee)

    page = client.get(reverse("account:settings") + "?tab=notifications").content.decode()

    assert "Fällige Erinnerungen" in page
    assert "Überfällige Rechnungen" not in page


def test_everything_resolves(admin):
    # The messages that clear themselves must not push anything: no device, no error.
    notify(Level.CRITICAL, "x", "Fehler", dedupe_key="x", to=Audience.ADMINS)
    assert async_to_sync(aresolve)("x") == 1
