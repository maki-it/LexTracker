import csv
import io
from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from billing.models import BillingAgreement, Invoice
from customers.models import Customer
from projects.models import Project, Task
from reports.queries import build_report
from reports.ranges import DateRange, presets, selected_range
from tracking.models import TimeEntry

pytestmark = pytest.mark.django_db

OCTOBER = DateRange("", "Oktober", date(2026, 10, 1), date(2026, 10, 31))


def work(user, task, day: str, hours: float, **extra) -> TimeEntry:
    start = datetime.fromisoformat(f"{day}T09:00").replace(tzinfo=timezone.get_current_timezone())
    return TimeEntry.objects.create(
        user=user, task=task, started_at=start, ended_at=start + timedelta(hours=hours), **extra
    )


@pytest.fixture
def setup(user, task):
    """ACME (100 €/h, budget 10 h) and a retainer customer."""
    acme = task.project.customer
    acme.default_hourly_rate = Decimal("100")
    acme.save()
    task.project.budget_hours = Decimal("10")
    task.project.save()
    retainer_customer = Customer.objects.create(name="Retainer AG", default_hourly_rate=Decimal("90"))
    retainer_task = Task.objects.create(
        project=Project.objects.create(customer=retainer_customer, name="Wartung"), name="Updates"
    )
    BillingAgreement.objects.create(
        customer=retainer_customer,
        kind=BillingAgreement.Kind.RETAINER,
        period=BillingAgreement.Period.MONTH,
        included_hours=Decimal("4"),
        fixed_price=Decimal("300"),
        valid_from=date(2026, 1, 1),
    )
    return acme, task, retainer_customer, retainer_task


def test_ranges():
    today = date(2026, 10, 22)
    keys = {r.key: r for r in presets(today)}
    assert (keys["vormonat"].start, keys["vormonat"].end) == (date(2026, 9, 1), date(2026, 9, 30))
    assert keys["vorquartal"].start == date(2026, 7, 1)
    assert keys["vorjahr"].end == date(2025, 12, 31)
    assert selected_range({}, today).key == "monat"
    assert selected_range({"zeitraum": "jahr"}, today).start == date(2026, 1, 1)
    custom = selected_range({"von": "2026-10-05", "bis": "2026-10-11"}, today)
    assert (custom.start, custom.end, custom.days) == (date(2026, 10, 5), date(2026, 10, 11), 7)
    assert selected_range({"von": "2026-10-11", "bis": "2026-10-05"}, today).key == "monat"


def test_report_totals_and_rows(user, setup):
    acme, task, _, retainer_task = setup
    invoice = Invoice.objects.create(
        customer=acme,
        period_start=date(2026, 9, 1),
        period_end=date(2026, 10, 15),
        total_net=Decimal("200.00"),
        status=Invoice.Status.PAID,
    )
    work(user, task, "2026-10-05", 2, invoice=invoice)
    work(user, task, "2026-10-06", 1.5)
    work(user, task, "2026-10-07", 1, is_billable=False)
    work(user, retainer_task, "2026-10-08", 5)
    work(user, task, "2026-09-30", 3)  # before the range, counts for the budget only
    Invoice.objects.create(
        customer=acme,
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        total_net=Decimal("999.00"),
        status=Invoice.Status.DELETED,
    )

    report = build_report(OCTOBER, today=date(2026, 10, 22))

    assert report.totals.total == timedelta(hours=9.5)
    assert report.totals.billable == timedelta(hours=8.5)
    assert report.totals.unbilled == timedelta(hours=6.5)
    # 1.5 h at 100 €; the retainer customer is left out.
    assert report.unbilled_value == Decimal("150.00")
    assert report.unbilled_value_skips_retainers
    assert report.invoiced == report.paid == Decimal("200.00")

    acme_row = next(r for r in report.customers if r.obj == acme)
    assert acme_row.total == timedelta(hours=4.5)
    assert acme_row.invoiced == Decimal("200.00")
    project_row = next(r for r in report.projects if r.obj == task.project)
    assert project_row.booked_all_time == timedelta(hours=7.5)
    assert project_row.budget_share == 75

    assert len(report.buckets) == 31
    assert report.buckets[7].total == timedelta(hours=5)

    (retainer,) = report.retainers
    assert retainer.period_label == "10/2026"
    assert retainer.used == timedelta(hours=5)
    assert retainer.overage == timedelta(hours=1)


def test_report_for_one_customer_and_by_month(user, setup):
    acme, task, _, retainer_task = setup
    work(user, task, "2026-03-05", 2)
    work(user, retainer_task, "2026-03-06", 1)

    year = DateRange("jahr", "Jahr", date(2026, 1, 1), date(2026, 12, 31))
    report = build_report(year, customer_id=acme.pk, today=date(2026, 10, 22))

    assert report.totals.total == timedelta(hours=2)
    assert [r.obj for r in report.customers] == [acme]
    assert report.retainers == []
    assert [b.label for b in report.buckets][:3] == ["Jan 26", "Feb 26", "Mär 26"]
    assert report.buckets[2].share == 100


def test_reports_page(client, user, setup):
    _, task, _, _ = setup
    client.force_login(user)
    work(user, task, timezone.localdate().isoformat(), 2)

    response = client.get(reverse("reports:overview"))

    assert response.status_code == 200
    assert "Auswertungen" in response.text
    assert "Retainer im laufenden Zeitraum" in response.text
    assert task.project.name in response.text


def test_csv_export(client, user, setup):
    _, task, _, _ = setup
    client.force_login(user)
    work(user, task, "2026-10-05", 1.25, description="Logo; Farben")

    response = client.get(reverse("reports:entries_csv"), {"von": "2026-10-01", "bis": "2026-10-31"})

    assert response["Content-Disposition"] == 'attachment; filename="zeiten-2026-10-01-2026-10-31.csv"'
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0][:4] == ["Datum", "Beginn", "Ende", "Stunden"]
    assert rows[1][:4] == ["05.10.2026", "09:00", "10:15", "1,25"]
    assert rows[1][8] == "Logo; Farben"
    assert len(rows) == 2
