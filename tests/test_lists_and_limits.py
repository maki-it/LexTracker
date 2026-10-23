"""Task choices, lists that load more while scrolling, the login rate limit and compressed responses."""

import gzip
from datetime import date, timedelta
from decimal import Decimal

import brotli
import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import LoginFailure
from billing.models import Invoice
from core.models import AppSettings
from customers.models import Customer
from projects.models import Project, Task
from tracking.forms import task_choices
from tracking.models import TimeEntry
from tracking.queries import booked_time

pytestmark = pytest.mark.django_db
HTMX = {"HX-Request": "true"}


@pytest.fixture
def logged_in(client, user):
    user.list_page_size = 25
    user.save()
    client.force_login(user)
    return client


# Task choices


def test_task_choices_only_active_projects_and_recently_used_first(user, task):
    customer = task.project.customer
    paused = Project.objects.create(customer=customer, name="Pausiert", status=Project.Status.PAUSED)
    Task.objects.create(project=paused, name="Ruht")
    other = Task.objects.create(project=task.project, name="Abstimmung")
    start = timezone.now() - timedelta(days=1)
    TimeEntry.objects.create(user=user, task=task, started_at=start, ended_at=start + timedelta(hours=1))

    assert [t.name for t in task_choices(user)] == ["Entwicklung", "Abstimmung"]
    TimeEntry.objects.create(
        user=user, task=other, started_at=start + timedelta(hours=2), ended_at=start + timedelta(hours=3)
    )
    assert [t.name for t in task_choices(user)] == ["Abstimmung", "Entwicklung"]


# Lists


def test_project_list_shows_active_projects_and_loads_more(logged_in, task):
    customer = task.project.customer
    for i in range(30):
        Project.objects.create(customer=customer, name=f"P{i:02d}")
    Project.objects.create(customer=customer, name="Fertig", status=Project.Status.DONE)

    page = logged_in.get(reverse("projects:list")).text
    assert "P00" in page and "P23" in page and "P24" not in page and ">Fertig<" not in page
    assert 'hx-get="?seite=2"' in page

    rows = logged_in.get(reverse("projects:list"), {"status": "aktiv", "seite": 2}, headers=HTMX).text
    assert "P24" in rows and "<html" not in rows and "seite=3" not in rows

    done = logged_in.get(reverse("projects:list"), {"status": "abgeschlossen"}).text
    assert ">Fertig<" in done and "P00" not in done


def test_customer_list_loads_more(logged_in):
    Customer.objects.bulk_create(Customer(name=f"Kunde {i:02d}") for i in range(30))

    page = logged_in.get(reverse("customers:list")).text
    assert "Kunde 24" in page and "Kunde 25" not in page

    rows = logged_in.get(reverse("customers:list"), {"seite": 2}, headers=HTMX).text
    assert "Kunde 25" in rows and "Kunde 29" in rows and "<html" not in rows


def test_invoice_list_filters_by_customer_and_sorts_newest_first(logged_in, task):
    acme, other = task.project.customer, Customer.objects.create(name="Andere AG")

    def invoice(customer, number, day):
        return Invoice.objects.create(
            customer=customer,
            period_start=day,
            period_end=day,
            total_net=Decimal(1),
            voucher_number=number,
            voucher_date=day,
            status=Invoice.Status.OPEN,
        )

    invoice(acme, "RE-1", date(2026, 9, 1))
    invoice(acme, "RE-3", date(2026, 10, 1))
    invoice(acme, "RE-2", date(2026, 10, 1))
    invoice(other, "RE-9", date(2026, 8, 1))

    page = logged_in.get(reverse("billing:invoices")).text
    assert page.index("RE-3") < page.index("RE-2") < page.index("RE-1") < page.index("RE-9")

    page = logged_in.get(reverse("billing:invoices"), {"kunde": other.pk}).text
    assert "RE-9" in page and "RE-1" not in page


def test_invoice_list_loads_more(logged_in, task):
    Invoice.objects.bulk_create(
        Invoice(
            customer=task.project.customer,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 1, 31),
            total_net=Decimal(1),
            voucher_number=f"RE-{i:02d}",
            voucher_date=date(2026, 1, 1) + timedelta(days=i),
        )
        for i in range(30)
    )
    page = logged_in.get(reverse("billing:invoices")).text
    assert "RE-29" in page and "RE-05" in page and "RE-04" not in page

    rows = logged_in.get(reverse("billing:invoices"), {"seite": 2}, headers=HTMX).text
    assert "RE-04" in rows and "RE-00" in rows and "<html" not in rows


# Login rate limit


def _login(client, password):
    return client.post(reverse("accounts:login"), {"username": "kim", "password": password})


def test_login_is_locked_after_too_many_failures(client, user):
    AppSettings.objects.update_or_create(pk=1, defaults={"login_max_attempts": 3, "login_lockout_minutes": 10})
    for _ in range(3):
        assert _login(client, "falsch").status_code == 200

    response = _login(client, "geheim-123")
    assert response.status_code == 429
    assert "Zu viele Fehlversuche. Versuche es in 10 Minuten wieder." in response.text

    # Once the failures are older than the lockout, the login works again and clears them.
    LoginFailure.objects.update(at=timezone.now() - timedelta(minutes=11))
    assert _login(client, "geheim-123").status_code == 302
    assert not LoginFailure.objects.exists()


def test_login_rate_limit_can_be_turned_off(client, user):
    AppSettings.objects.update_or_create(pk=1, defaults={"login_max_attempts": 0})
    for _ in range(10):
        _login(client, "falsch")
    assert _login(client, "geheim-123").status_code == 302
    assert not LoginFailure.objects.exists()


# Compression


def test_pages_are_compressed(logged_in, task):
    page = logged_in.get(reverse("projects:list"), headers={"Accept-Encoding": "gzip, deflate, br"})
    assert page["Content-Encoding"] == "br"
    assert "Accept-Encoding" in page["Vary"]
    assert b"<html" in brotli.decompress(page.content)

    page = logged_in.get(reverse("projects:list"), headers={"Accept-Encoding": "gzip"})
    assert page["Content-Encoding"] == "gzip"
    assert b"<html" in gzip.decompress(page.content)

    assert not logged_in.get(reverse("projects:list")).has_header("Content-Encoding")
    assert not logged_in.get(reverse("core:health"), headers={"Accept-Encoding": "br"}).has_header("Content-Encoding")


def test_booked_time_is_summed_in_the_database_to_the_millisecond(user, task):
    start = timezone.now().replace(microsecond=250_000)
    for minutes in (61, 30):
        TimeEntry.objects.create(
            user=user, task=task, started_at=start, ended_at=start + timedelta(minutes=minutes, seconds=3)
        )
    TimeEntry.objects.create(user=user, task=task, started_at=start)  # running, counts as zero

    assert TimeEntry.objects.aggregate(t=booked_time())["t"] == timedelta(minutes=91, seconds=6)
