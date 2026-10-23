import re
import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import ApiToken, User
from billing.models import Invoice
from customers.models import Customer
from projects.models import Project, Task
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def entry(user, task, description="", hours=1, days_ago=0, billable=True):
    start = timezone.now() - timedelta(days=days_ago, hours=hours + 1)
    return TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=start,
        ended_at=start + timedelta(hours=hours),
        description=description,
        is_billable=billable,
    )


@pytest.fixture
def employee(db):
    return User.objects.create_user(username="mia", password="geheim-123", role=User.Role.EMPLOYEE)


@pytest.fixture
def customer_user(task):
    return User.objects.create_user(
        username="acme", password="geheim-123", role=User.Role.CUSTOMER, customer=task.project.customer
    )


@pytest.fixture
def other_task(db):
    customer = Customer.objects.create(name="Fremd AG")
    return Task.objects.create(project=Project.objects.create(customer=customer, name="Geheim"), name="Intern")


# Employees


@pytest.mark.parametrize(
    ("url", "status"),
    [
        ("core:dashboard", 200),
        ("tracking:list", 200),
        ("account:settings", 200),
        ("projects:list", 403),
        ("customers:list", 403),
        ("billing:overview", 403),
        ("reports:overview", 403),
        ("users:list", 403),
        ("core:settings", 403),
    ],
)
def test_employee_access(client, employee, task, url, status):
    client.force_login(employee)
    assert client.get(reverse(url)).status_code == status


def test_employee_sidebar_and_own_time_only(client, employee, user, task):
    entry(user, task, "Kims Arbeit")
    entry(employee, task, "Mias Arbeit")
    client.force_login(employee)

    response = client.get(reverse("tracking:list"))
    assert "Mias Arbeit" in response.text and "Kims Arbeit" not in response.text
    assert "Abrechnung" not in response.text and "Benutzer" not in response.text


# Customers


def test_customer_is_sent_to_the_portal(client, customer_user):
    client.force_login(customer_user)
    assert client.get("/").url == reverse("portal:overview")
    for url in ("tracking:list", "projects:list", "billing:overview", "users:list"):
        assert client.get(reverse(url)).status_code == 403


def test_portal_shows_only_the_own_customer(client, customer_user, user, task, other_task):
    task.project.budget_hours = Decimal("10")
    task.project.save()
    entry(user, task, "Startseite gestaltet", hours=2)
    entry(user, task, "Kaffee", billable=False)
    entry(user, other_task, "Streng geheim")
    client.force_login(customer_user)

    overview = client.get(reverse("portal:overview")).text
    assert "Website" in overview and "Geheim" not in overview
    assert "30 % von 10 h" in overview

    entries = client.get(reverse("portal:entries")).text
    assert "Startseite gestaltet" in entries and "Streng geheim" not in entries
    assert "nicht berechnet" in entries


def test_portal_permissions_can_be_narrowed(client, customer_user, user, task):
    task.project.budget_hours = Decimal("10")
    task.project.save()
    entry(user, task, "Startseite gestaltet")
    customer_user.portal_budget = False
    customer_user.portal_descriptions = False
    customer_user.portal_invoices = False
    customer_user.save()
    client.force_login(customer_user)

    overview = client.get(reverse("portal:overview")).text
    assert "Budget" not in overview and "Rechnungen" not in overview
    assert "Startseite gestaltet" not in client.get(reverse("portal:entries")).text
    assert client.get(reverse("portal:invoices")).status_code == 403

    customer_user.portal_entries = False
    customer_user.save()
    assert client.get(reverse("portal:entries")).status_code == 403


def test_portal_hides_draft_and_deleted_invoices(client, customer_user, task):
    customer = task.project.customer
    for number, status in [
        ("RE1", Invoice.Status.PAID),
        ("RE2", Invoice.Status.DRAFT),
        ("RE3", Invoice.Status.DELETED),
    ]:
        Invoice.objects.create(
            customer=customer,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            total_net=Decimal("100"),
            status=status,
            voucher_number=number,
            lexware_id=uuid.uuid4(),
            # Invoices written directly in Lexware show up like the others.
            origin=Invoice.Origin.LEXWARE if number == "RE1" else Invoice.Origin.APP,
        )
    client.force_login(customer_user)

    response = client.get(reverse("portal:invoices")).text
    assert "RE1" in response and "RE2" not in response and "RE3" not in response


def test_customer_has_no_api_tokens(client, customer_user):
    client.force_login(customer_user)
    assert "API-Tokens" not in client.get(reverse("account:settings")).text
    assert client.post(reverse("account:token_create"), {"name": "x"}).status_code == 403

    _, key = ApiToken.issue(customer_user, "alt")
    client.logout()
    response = client.post("/mcp/", "{}", content_type="application/json", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 401


# User management


def test_admin_invites_a_user(client, user, task):
    client.force_login(user)

    response = client.post(
        reverse("users:create"),
        {"username": "mia", "first_name": "Mia", "role": User.Role.EMPLOYEE, "portal_entries": "on"},
    )
    mia = User.objects.get(username="mia")
    assert response.url == reverse("users:invite", args=[mia.pk])
    assert not mia.has_usable_password()

    link = re.search(r"http://testserver(/accounts/einladung/[^<\s]+)", client.get(response.url).text).group(1)
    client.logout()

    assert "Passwort festlegen" in client.get(link).text
    response = client.post(link, {"new_password1": "Sehr-sicher-42", "new_password2": "Sehr-sicher-42"})
    assert response.url.startswith(reverse("accounts:login"))
    mia.refresh_from_db()
    assert mia.check_password("Sehr-sicher-42")

    # The link works only once.
    assert client.get(link).status_code == 400


def test_customer_login_needs_a_customer(client, user):
    client.force_login(user)
    response = client.post(reverse("users:create"), {"username": "kunde", "role": User.Role.CUSTOMER})
    assert "braucht einen Kunden" in response.text
    assert not User.objects.filter(username="kunde").exists()


def test_admin_cannot_lock_themself_out(client, user):
    client.force_login(user)
    response = client.post(
        reverse("users:edit", args=[user.pk]), {"username": user.username, "role": User.Role.EMPLOYEE}
    )
    assert "Administratorrolle" in response.text and "nicht selbst deaktivieren" in response.text
    user.refresh_from_db()
    assert user.is_admin and user.is_active


def test_admin_deletes_a_user(client, user, employee):
    ApiToken.objects.create(user=employee, name="Agent", key_hash="x" * 64, hint="lxt_test")
    client.force_login(user)
    assert "Benutzer löschen" in client.get(reverse("users:edit", args=[employee.pk])).text

    response = client.post(reverse("users:delete", args=[employee.pk]))
    assert response.url == reverse("users:list")
    assert not User.objects.filter(pk=employee.pk).exists()
    assert not ApiToken.objects.exists()
    assert "mia gelöscht" in client.get(response.url).text


def test_users_with_booked_time_cannot_be_deleted(client, user, employee, task):
    entry(employee, task)
    client.force_login(user)
    form = client.get(reverse("users:edit", args=[employee.pk])).text
    assert "Zeiten gebucht" in form and reverse("users:delete", args=[employee.pk]) not in form

    client.post(reverse("users:delete", args=[employee.pk]))
    assert User.objects.filter(pk=employee.pk).exists()


def test_admin_cannot_delete_themself(client, user):
    client.force_login(user)
    assert "Benutzer löschen" not in client.get(reverse("users:edit", args=[user.pk])).text

    response = client.post(reverse("users:delete", args=[user.pk]))
    assert response.url == reverse("users:list")
    assert User.objects.filter(pk=user.pk).exists()
    assert "nicht selbst löschen" in client.get(response.url).text


def test_only_admins_delete_users(client, user, employee):
    client.force_login(employee)
    assert client.post(reverse("users:delete", args=[user.pk])).status_code == 403
    assert User.objects.filter(pk=user.pk).exists()


def test_booking_lists_can_select_all(client, user, employee, task, other_task):
    client.force_login(user)
    form = client.get(reverse("users:edit", args=[employee.pk])).text
    # Two customers and two projects: each list gets its own "select all" box.
    assert form.count("data-select-all") == 2


def test_long_booking_lists_and_customer_select_are_searchable(client, user, employee, task, other_task):
    client.force_login(user)
    url = reverse("users:edit", args=[employee.pk])
    # Short lists do not need a search field.
    assert "data-filter" not in client.get(url).text
    for number in range(6):
        Customer.objects.create(name=f"Kunde {number}")
    form = client.get(url).text
    assert form.count("data-filter") == 1
    assert 'name="customer"' in form and "data-searchable" in form


def test_health_check_stays_open_for_everyone(client, customer_user):
    client.force_login(customer_user)
    assert client.get(reverse("core:health")).status_code == 200


def test_descriptions_need_the_entries(client, user, customer_user):
    client.force_login(user)
    form = client.get(reverse("users:edit", args=[customer_user.pk])).text
    assert 'data-requires="portal_entries"' in form

    def save_without_entries():
        # The browser does not send the greyed-out box. Scripts off, it would send it ticked: ignored either way.
        client.post(
            reverse("users:edit", args=[customer_user.pk]),
            {
                "username": customer_user.username,
                "role": User.Role.CUSTOMER,
                "customer": customer_user.customer_id,
                "portal_descriptions": "on",
                "is_active": "on",
            },
        )
        customer_user.refresh_from_db()

    # The stored choice is kept, so it is back when the entries are turned on again.
    save_without_entries()
    assert not customer_user.portal_entries and customer_user.portal_descriptions

    customer_user.portal_descriptions = False
    customer_user.save()
    save_without_entries()
    assert not customer_user.portal_descriptions


def test_customer_access_settings_only_for_customers(client, user, employee, customer_user):
    client.force_login(user)
    form = client.get(reverse("users:edit", args=[employee.pk])).text
    assert re.search(r'data-shown-for="role=customer"\s+hidden disabled', form)
    form = client.get(reverse("users:edit", args=[customer_user.pk])).text
    assert 'data-shown-for="role=customer">' in form

    # Turning a customer into an employee sends no settings: they are kept for the case it turns back.
    customer_user.portal_invoices = False
    customer_user.save()
    client.post(
        reverse("users:edit", args=[customer_user.pk]),
        {"username": customer_user.username, "role": User.Role.EMPLOYEE, "is_active": "on"},
    )
    customer_user.refresh_from_db()
    assert customer_user.role == User.Role.EMPLOYEE and customer_user.customer is None
    assert customer_user.portal_entries and not customer_user.portal_invoices


def test_customer_downloads_the_invoice_pdf(client, customer_user, other_task, monkeypatch):
    import httpx

    from tests.lexware_fakes import fake_client

    def invoice(customer, number, status=Invoice.Status.OPEN):
        return Invoice.objects.create(
            customer=customer,
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            total_net=Decimal("100"),
            status=status,
            voucher_number=number,
            lexware_id=uuid.uuid4(),
        )

    own = invoice(customer_user.customer, "RE0042")
    draft = invoice(customer_user.customer, "RE0044", Invoice.Status.DRAFT)
    foreign = invoice(other_task.project.customer, "RE0043")
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith(f"/invoices/{own.lexware_id}/file"):
            return httpx.Response(200, content=b"%PDF-1.7", headers={"Content-Type": "application/pdf"})
        return httpx.Response(500)

    monkeypatch.setattr("portal.views.client_from_settings", lambda: fake_client(handler))
    client.force_login(customer_user)

    assert reverse("portal:invoice_pdf", args=[own.voucher_number]) in client.get(reverse("portal:invoices")).text
    response = client.get(reverse("portal:invoice_pdf", args=[own.voucher_number]))
    assert response.content == b"%PDF-1.7" and response["Content-Type"] == "application/pdf"
    assert 'filename="Rechnung-RE0042.pdf"' in response["Content-Disposition"]
    assert requests[0].headers["Accept"] == "application/pdf"
    # The invoice number in the list opens the same PDF in the browser.
    response = client.get(reverse("portal:invoice_pdf", args=[own.voucher_number]), {"ansehen": "1"})
    assert response["Content-Disposition"].startswith("inline")

    # Drafts and other customers' invoices are not to be had.
    assert client.get(reverse("portal:invoice_pdf", args=[draft.voucher_number])).status_code == 404
    assert client.get(reverse("portal:invoice_pdf", args=[foreign.voucher_number])).status_code == 404

    # Lexware failing ends on the list with a message.
    Invoice.objects.filter(pk=own.pk).update(lexware_id=uuid.uuid4())
    response = client.get(reverse("portal:invoice_pdf", args=[own.voucher_number]), follow=True)
    assert "kann gerade nicht heruntergeladen werden" in response.text

    customer_user.portal_invoices = False
    customer_user.save()
    assert client.get(reverse("portal:invoice_pdf", args=[own.voucher_number])).status_code == 403


# What employees may book on


def test_employee_books_only_on_unlocked_customers_and_projects(client, user, employee, task, other_task):
    client.force_login(employee)
    start_url = reverse("tracking:timer_start")
    search_url = reverse("tracking:task_search")

    # Nothing unlocked yet.
    offered = client.get(search_url).text
    assert task.name not in offered and other_task.name not in offered
    assert "Noch keine offenen Aufgaben" in client.get(start_url).text
    assert client.post(start_url, {"task": task.pk}).status_code == 404

    employee.bookable_customers.add(task.project.customer)
    offered = client.get(search_url).text
    assert task.name in offered and other_task.name not in offered

    employee.bookable_projects.add(other_task.project)
    assert other_task.name in client.get(search_url).text
    client.post(start_url, {"task": other_task.pk})
    assert TimeEntry.objects.get(user=employee, ended_at__isnull=True).task == other_task


def test_employee_entry_form_rejects_locked_tasks(client, employee, task):
    client.force_login(employee)
    now = timezone.localtime().replace(second=0, microsecond=0)
    data = {
        "task": task.pk,
        "started_at": (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M"),
        "ended_at": now.strftime("%Y-%m-%dT%H:%M"),
    }
    response = client.post(reverse("tracking:create"), data)
    assert response.status_code == 200 and not TimeEntry.objects.exists()

    employee.bookable_customers.add(task.project.customer)
    client.post(reverse("tracking:create"), data)
    assert TimeEntry.objects.filter(user=employee, task=task).exists()


def test_employee_agent_sees_only_unlocked_tasks(client, employee, task, other_task):
    import json

    employee.bookable_projects.add(task.project)
    _, key = ApiToken.issue(employee, "Agent")

    def call(tool, /, **arguments):
        message = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": arguments}}
        response = client.post(
            "/mcp/", json.dumps(message), content_type="application/json", headers={"Authorization": f"Bearer {key}"}
        )
        return response.json()["result"]["content"][0]["text"]

    assert [p["name"] for p in json.loads(call("list_projects"))] == ["Website"]
    assert json.loads(call("find_tasks", query="Intern")) == []
    assert "Keine offene Aufgabe" in call("start_timer", task_id=other_task.pk)
    assert "Kein aktives Projekt" in call("create_task", project_id=other_task.project_id, name="Neu")


def test_admin_unlocks_customers_and_projects(client, user, employee, task, other_task):
    client.force_login(user)
    url = reverse("users:edit", args=[employee.pk])
    form = client.get(url).text
    assert 'data-shown-for="role=employee">' in form and "Fremd AG · Geheim" in form

    client.post(
        url,
        {
            "username": employee.username,
            "role": User.Role.EMPLOYEE,
            "bookable_customers": [task.project.customer_id],
            "bookable_projects": [other_task.project_id],
            "is_active": "on",
        },
    )
    assert list(employee.bookable_customers.all()) == [task.project.customer]
    assert list(employee.bookable_projects.all()) == [other_task.project]
    assert "1 Kunde, 1 Projekt" in client.get(reverse("users:list")).text

    # Another role keeps the unlocks, they are just not used.
    client.post(url, {"username": employee.username, "role": User.Role.ADMIN, "is_active": "on"})
    assert employee.bookable_customers.exists()


def test_portal_invoices_filter_by_status_and_date(client, customer_user):
    def invoice(number, status, day):
        return Invoice.objects.create(
            customer=customer_user.customer,
            period_start=day,
            period_end=day,
            voucher_date=day,
            total_net=Decimal("100"),
            status=status,
            voucher_number=number,
            lexware_id=uuid.uuid4(),
        )

    invoice("RE-ALT", Invoice.Status.PAID, date(2025, 3, 1))
    current = invoice("RE-NEU", Invoice.Status.OPEN, date(2026, 10, 1))
    client.force_login(customer_user)
    url = reverse("portal:invoices")

    text = client.get(url).text
    assert "RE-ALT" in text and "RE-NEU" in text
    text = client.get(url, {"status": "bezahlt"}).text
    assert "RE-ALT" in text and "RE-NEU" not in text
    text = client.get(url, {"von": "2026-01-01", "bis": "2026-12-31"}).text
    assert "RE-ALT" not in text and "RE-NEU" in text
    text = client.get(url, {"von": "2026-01-01", "bis": "2026-12-31", "status": "bezahlt"}).text
    assert "Keine Rechnung passt zum Filter" in text
    # Drafts cannot be picked.
    assert "RE-NEU" in client.get(url, {"status": "entwurf"}).text

    text = client.get(url).text
    assert f'href="{reverse("portal:invoice_pdf", args=[current.voucher_number])}?ansehen=1"' in text
    assert "Online ansehen" not in text
