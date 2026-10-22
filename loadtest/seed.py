"""Fill an empty database with a realistic amount of test data for the load test.

Run it from the app folder, against a database that holds nothing you need:

    cd app && APP_DATA_DIR=/tmp/loadtest-data uv run python ../loadtest/seed.py

or in the container (see loadtest/README.md). It never talks to Lexware: the customers get no Lexware ID.
"""

import argparse
import os
import random
import sys
from datetime import date, datetime, time, timedelta
from decimal import Decimal

sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from accounts.models import User  # noqa: E402
from billing.models import BillingAgreement, Invoice  # noqa: E402
from customers.models import Category, Customer  # noqa: E402
from projects.models import Project, Task  # noqa: E402
from tracking.models import TimeEntry  # noqa: E402

PASSWORD = "lasttest-123"
TASK_NAMES = ["Konzeption", "Entwicklung", "Support", "Abstimmung", "Wartung", "Dokumentation", "Design", "Testing"]
WORDS = [
    "Fehler behoben",
    "Termin",
    "Review",
    "Deployment",
    "Recherche",
    "Meeting",
    "Anpassung",
    "Rückfrage",
    "Analyse",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--customers", type=int, default=300)
    parser.add_argument("--projects-per-customer", type=int, default=3)
    parser.add_argument("--tasks-per-project", type=int, default=4)
    parser.add_argument("--entries", type=int, default=25_000, help="time entries in total")
    parser.add_argument("--users", type=int, default=10, help="logins loadtest01, loadtest02, …")
    parser.add_argument("--days", type=int, default=730, help="how far back the entries go")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--force", action="store_true", help="also run if the database already has customers")
    return parser.parse_args()


@transaction.atomic
def seed(args: argparse.Namespace) -> None:
    rnd = random.Random(args.seed)
    tz = timezone.get_current_timezone()
    today = timezone.localdate()

    users = []
    for i in range(1, args.users + 1):
        user, created = User.objects.get_or_create(username=f"loadtest{i:02d}", defaults={"role": User.Role.ADMIN})
        if created:
            user.set_password(PASSWORD)
            user.save()
        users.append(user)

    categories = [Category.objects.get_or_create(name=n)[0] for n in ("Stammkunde", "Agentur", "Retainer", "Neu")]
    customers = Customer.objects.bulk_create(
        Customer(
            name=f"Lasttest Kunde {i:04d} GmbH",
            customer_number=str(20000 + i),
            email=f"kunde{i}@example.com",
            default_hourly_rate=Decimal(rnd.choice([85, 95, 110, 120])),
            is_archived=rnd.random() < 0.1,
        )
        for i in range(args.customers)
    )
    for customer in customers:
        customer.categories.add(*rnd.sample(categories, rnd.randint(0, 2)))

    projects = Project.objects.bulk_create(
        Project(
            customer=c,
            name=f"Projekt {j + 1}",
            status=rnd.choices(list(Project.Status.values), weights=[1, 6, 1, 2])[0],
            hourly_rate=Decimal(130) if rnd.random() < 0.2 else None,
        )
        for c in customers
        for j in range(args.projects_per_customer)
    )
    tasks = Task.objects.bulk_create(
        Task(
            project=p,
            name=TASK_NAMES[k % len(TASK_NAMES)],
            status=rnd.choices(list(Task.Status.values), weights=[5, 3, 2])[0],
            is_billable=rnd.random() < 0.9,
            estimated_hours=Decimal(rnd.choice([4, 8, 16, 40])) if rnd.random() < 0.3 else None,
        )
        for p in projects
        for k in range(args.tasks_per_project)
    )

    # A tenth of the customers pays a quarterly retainer.
    BillingAgreement.objects.bulk_create(
        BillingAgreement(
            customer=c,
            kind=BillingAgreement.Kind.RETAINER,
            period=BillingAgreement.Period.QUARTER,
            included_hours=Decimal(20),
            fixed_price=Decimal(2000),
            valid_from=today - timedelta(days=args.days),
        )
        for c in customers[::10]
    )

    # Most entries belong to the first user, like a freelancer with a few helpers.
    weights = [5] + [1] * (len(users) - 1)
    entries = []
    for _ in range(args.entries):
        day = today - timedelta(days=rnd.randint(1, args.days))
        start = datetime.combine(day, time(rnd.randint(7, 17), rnd.choice([0, 15, 30, 45])), tzinfo=tz)
        task = rnd.choice(tasks)
        entries.append(
            TimeEntry(
                user=rnd.choices(users, weights=weights)[0],
                task=task,
                started_at=start,
                ended_at=start + timedelta(minutes=rnd.choice([15, 30, 45, 60, 90, 120, 180])),
                description=" ".join(rnd.sample(WORDS, 2)),
                is_billable=task.is_billable,
            )
        )
    entries = TimeEntry.objects.bulk_create(entries, batch_size=2000)

    # Entries older than three months are billed: one invoice per customer and month.
    cutoff = datetime.combine(today - timedelta(days=90), time.min, tzinfo=tz)
    customer_of_task = {t.pk: t.project.customer for t in tasks}
    invoices: dict[tuple[int, date], Invoice] = {}
    billed = []
    for entry in entries:
        if entry.started_at >= cutoff or not entry.is_billable:
            continue
        customer = customer_of_task[entry.task_id]
        month = timezone.localtime(entry.started_at).date().replace(day=1)
        key = (customer.pk, month)
        if key not in invoices:
            end = (month + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            invoices[key] = Invoice(
                customer=customer,
                period_start=month,
                period_end=end,
                total_net=Decimal(0),
                status=rnd.choice([Invoice.Status.PAID] * 4 + [Invoice.Status.OPEN]),
                voucher_number=f"RE{len(invoices) + 1:05d}",
                voucher_date=end,
            )
        invoices[key].total_net += Decimal(100)
        billed.append((entry, key))
    Invoice.objects.bulk_create(invoices.values(), batch_size=2000)
    for entry, key in billed:
        entry.invoice = invoices[key]
    TimeEntry.objects.bulk_update([e for e, _ in billed], ["invoice"], batch_size=2000)

    print(
        f"{len(users)} Benutzer (Passwort {PASSWORD}), {len(customers)} Kunden, {len(projects)} Projekte, "
        f"{len(tasks)} Aufgaben, {len(entries)} Zeiteinträge, {len(invoices)} Rechnungen"
    )


if __name__ == "__main__":
    args = parse_args()
    if Customer.objects.exists() and not args.force:
        sys.exit("Die Datenbank enthält schon Kunden. Nur gegen eine Testdatenbank laufen lassen (oder --force).")
    seed(args)
