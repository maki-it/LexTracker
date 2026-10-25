import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from billing.models import Invoice
from customers.models import Customer
from projects.models import Project, Task
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db


def entry(user, task, description="", hours=1, days_ago=0, **extra):
    start = timezone.now() - timedelta(days=days_ago, hours=hours + 1)
    return TimeEntry.objects.create(
        user=user,
        task=task,
        started_at=start,
        ended_at=start + timedelta(hours=hours),
        description=description,
        **extra,
    )


def invoice(customer, number, status=Invoice.Status.PAID, origin=Invoice.Origin.APP):
    return Invoice.objects.create(
        customer=customer,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 9, 30),
        total_net=Decimal("100"),
        status=status,
        voucher_number=number,
        lexware_id=uuid.uuid4(),
        origin=origin,
    )


@pytest.fixture
def customer_user(task):
    return User.objects.create_user(
        username="acme", password="geheim-123", role=User.Role.CUSTOMER, customer=task.project.customer
    )


@pytest.fixture
def other_task(db):
    customer = Customer.objects.create(name="Fremd AG")
    return Task.objects.create(project=Project.objects.create(customer=customer, name="Geheim"), name="Intern")


def test_entries_show_whether_and_where_they_were_billed(client, customer_user, user, task):
    inv = invoice(task.project.customer, "RE-100")
    entry(user, task, "Abgerechnet", invoice=inv)
    entry(user, task, "Noch offen")
    entry(user, task, "Kaffee", is_billable=False)
    client.force_login(customer_user)

    response = client.get(reverse("portal:entries"))
    assert response.text.count("abgerechnet</span>") == 1
    assert response.text.count(">offen</span>") == 1
    assert "RE-100" in response.text
    assert reverse("portal:invoice_entries", args=[inv.voucher_number]) in response.text


def test_entries_of_a_draft_invoice_count_as_open(client, customer_user, user, task):
    draft = invoice(task.project.customer, "ENTWURF-1", Invoice.Status.DRAFT)
    entry(user, task, invoice=draft)
    client.force_login(customer_user)

    response = client.get(reverse("portal:entries")).text
    assert "ENTWURF-1" not in response and ">offen</span>" in response and "abgerechnet</span>" not in response


def test_voided_invoice_is_marked(client, customer_user, user, task):
    entry(user, task, invoice=invoice(task.project.customer, "RE-9", Invoice.Status.VOIDED))
    client.force_login(customer_user)
    assert "(storniert)" in client.get(reverse("portal:entries")).text


def test_billed_entries_without_invoice_permission_show_no_number(client, customer_user, user, task):
    inv = invoice(task.project.customer, "RE-100")
    entry(user, task, invoice=inv)
    customer_user.portal_invoices = False
    customer_user.save()
    client.force_login(customer_user)

    response = client.get(reverse("portal:entries")).text
    assert "abgerechnet</span>" in response and "RE-100" not in response
    assert reverse("portal:invoice_entries", args=[inv.voucher_number]) not in response


def test_invoice_lists_its_entries(client, customer_user, user, task):
    inv = invoice(task.project.customer, "RE-100")
    entry(user, task, "Im Paket", hours=2, invoice=inv)
    entry(user, task, "Noch offen")
    client.force_login(customer_user)

    listing = client.get(reverse("portal:invoices")).text
    assert reverse("portal:invoice_entries", args=[inv.voucher_number]) in listing

    response = client.get(reverse("portal:invoice_entries", args=[inv.voucher_number])).text
    assert "RE-100" in response and "Im Paket" in response and "Noch offen" not in response
    assert "Website · Entwicklung" in response and "2:00 h" in response


def test_invoice_entries_hide_descriptions_when_not_allowed(client, customer_user, user, task):
    inv = invoice(task.project.customer, "RE-100")
    entry(user, task, "Interne Notiz", invoice=inv)
    customer_user.portal_descriptions = False
    customer_user.save()
    client.force_login(customer_user)

    response = client.get(reverse("portal:invoice_entries", args=[inv.voucher_number])).text
    assert "Interne Notiz" not in response and "Entwicklung" in response


def test_invoice_entries_need_both_permissions(client, customer_user, user, task):
    inv = invoice(task.project.customer, "RE-100")
    entry(user, task, invoice=inv)
    client.force_login(customer_user)
    url = reverse("portal:invoice_entries", args=[inv.voucher_number])

    customer_user.portal_entries = False
    customer_user.save()
    assert client.get(url).status_code == 403
    assert (
        reverse("portal:invoice_entries", args=[inv.voucher_number]) not in client.get(reverse("portal:invoices")).text
    )

    customer_user.portal_entries, customer_user.portal_invoices = True, False
    customer_user.save()
    assert client.get(url).status_code == 403


def test_lexware_only_invoices_have_no_entries_link(client, customer_user, task):
    inv = invoice(task.project.customer, "RE-7", origin=Invoice.Origin.LEXWARE)
    client.force_login(customer_user)

    assert (
        reverse("portal:invoice_entries", args=[inv.voucher_number]) not in client.get(reverse("portal:invoices")).text
    )
    assert "keine erfassten Zeiten" in client.get(reverse("portal:invoice_entries", args=[inv.voucher_number])).text


def test_invoice_entries_only_for_own_visible_invoices(client, customer_user, user, task, other_task):
    foreign = invoice(other_task.project.customer, "FREMD-1")
    entry(user, other_task, "Streng geheim", invoice=foreign)
    draft = invoice(task.project.customer, "ENTWURF-1", Invoice.Status.DRAFT)
    entry(user, task, invoice=draft)
    client.force_login(customer_user)

    assert client.get(reverse("portal:invoice_entries", args=[foreign.voucher_number])).status_code == 404
    assert client.get(reverse("portal:invoice_entries", args=[draft.voucher_number])).status_code == 404


def test_portal_lists_use_a_fixed_number_of_queries(client, customer_user, user, task, django_assert_max_num_queries):
    for i in range(5):
        entry(user, task, days_ago=i, invoice=invoice(task.project.customer, f"RE-{i}"))
    client.force_login(customer_user)
    with django_assert_max_num_queries(6):
        client.get(reverse("portal:entries"))
    with django_assert_max_num_queries(6):
        client.get(reverse("portal:invoices"))


def test_invoice_number_links_to_the_pdf_and_replaces_online_view(client, customer_user, task):
    inv = invoice(task.project.customer, "RE-2026-07-00403")
    client.force_login(customer_user)

    text = client.get(reverse("portal:invoices")).text
    pdf = reverse("portal:invoice_pdf", args=[inv.voucher_number])
    assert pdf == "/portal/invoices/RE-2026-07-00403/pdf/"
    assert f'href="{pdf}?inline=1"' in text and f'href="{pdf}"' in text
    assert "Online ansehen" not in text


def test_urls_use_the_number_in_every_form(client, customer_user, task, monkeypatch):
    import httpx

    from tests.lexware_fakes import fake_client

    # Lexware numbers are free-form: a slash, a space and a umlaut must survive the URL.
    numbers = ["2026/00403", "RE 2026 Ä", "00045", "RE-1?x#y%z"]
    invoices = {n: invoice(task.project.customer, n) for n in numbers}
    fetched = []

    def handler(request):
        fetched.append(request.url.path)
        return httpx.Response(200, content=b"%PDF", headers={"Content-Type": "application/pdf"})

    monkeypatch.setattr("portal.views.client_from_settings", lambda: fake_client(handler))
    client.force_login(customer_user)

    for number, inv in invoices.items():
        response = client.get(reverse("portal:invoice_pdf", args=[number]))
        assert response.status_code == 200, number
        assert fetched[-1].endswith(f"/invoices/{inv.lexware_id}/file")
        assert "/" not in response["Content-Disposition"].split("filename", 1)[1]
        assert client.get(reverse("portal:invoice_entries", args=[number])).status_code == 200, number


def test_same_number_at_two_customers_stays_apart(client, customer_user, task, other_task):
    own = invoice(task.project.customer, "RE-1")
    foreign = invoice(other_task.project.customer, "RE-1")
    Invoice.objects.filter(pk=foreign.pk).update(total_net=Decimal("999"))
    client.force_login(customer_user)

    response = client.get(reverse("portal:invoice_entries", args=["RE-1"]))
    assert response.status_code == 200 and response.context["invoice"].pk == own.pk


def test_voided_invoice_keeps_its_number_url(client, customer_user, task):
    inv = invoice(task.project.customer, "RE-9", Invoice.Status.VOIDED)
    client.force_login(customer_user)

    assert client.get(reverse("portal:invoice_entries", args=[inv.voucher_number])).status_code == 200
    assert reverse("portal:invoice_pdf", args=["RE-9"]) in client.get(reverse("portal:invoices")).text


def test_unknown_and_foreign_numbers_are_404(client, customer_user, task, other_task):
    invoice(other_task.project.customer, "FREMD-1")
    invoice(task.project.customer, "ENTWURF-1", Invoice.Status.DRAFT)
    client.force_login(customer_user)

    for number in ["FREMD-1", "ENTWURF-1", "GIBT-ES-NICHT"]:
        assert client.get(reverse("portal:invoice_pdf", args=[number])).status_code == 404
        assert client.get(reverse("portal:invoice_entries", args=[number])).status_code == 404


def test_invoice_without_a_number_has_no_links(client, customer_user, task):
    inv = invoice(task.project.customer, "", Invoice.Status.OPEN)
    entry(customer_user, task, invoice=inv)
    client.force_login(customer_user)

    text = client.get(reverse("portal:invoices")).text
    table = text.split("<tbody>", 1)[1]
    assert "/pdf/" not in table and "/time/" not in table
    assert "abgerechnet</span>" in client.get(reverse("portal:entries")).text


def test_old_numeric_id_urls_are_not_found(client, customer_user, task):
    invoice(task.project.customer, "RE-2026-07-00403")
    client.force_login(customer_user)

    # Links from before the number was used in the URL carried the counter, which no longer exists.
    assert client.get("/portal/invoices/12/pdf/").status_code == 404
    assert client.get("/portal/invoices/12/time/").status_code == 404


def test_a_number_that_looks_like_an_id_is_still_a_number(client, customer_user, task):
    numeric = invoice(task.project.customer, "42")
    client.force_login(customer_user)

    response = client.get(reverse("portal:invoice_entries", args=[numeric.voucher_number]))
    assert response.status_code == 200 and response.context["invoice"].pk == numeric.pk
