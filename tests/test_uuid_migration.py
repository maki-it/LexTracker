"""The migration from counters to UUIDs (core 0010, the ``*_uuid_primary_keys`` ones and core 0011).

A second, empty database is migrated up to the state before the conversion, filled with rows that point at
each other, and migrated forward.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from django.contrib.admin.models import LogEntry as NewLogEntry
from django.contrib.sessions.models import Session as NewSession
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django_otp.plugins.otp_totp.models import TOTPDevice as NewTOTPDevice

from accounts.models import ApiToken as NewApiToken
from accounts.models import User as NewUser
from billing.models import Invoice as NewInvoice
from core import backup
from customers.models import Customer as NewCustomer
from mailer.models import OutgoingMail as NewOutgoingMail
from tracking.models import TimeEntry as NewTimeEntry

# The last migration of each app before the conversion ...
BEFORE = [
    ("core", "0009_overdue_notice_and_invite_by_mail"),
    ("accounts", "0009_portal_contact"),
    ("billing", "0004_invoice_open_amount"),
    ("customers", "0002_category_customer_lexware_deleted_and_more"),
    ("mailer", "0002_alter_outgoingmail_kind"),
    ("projects", "0002_tasktemplate"),
    ("tracking", "0002_timeentry_invoice"),
]
# ... and the one that fills the new keys, which depends on all the others.
REKEY = ("core", "0011_uuid_primary_keys")
# Apps the conversion does not change but whose tables point at the converted ones.
OTHER_APPS = ["admin", "auth", "contenttypes", "sessions", "otp_static", "otp_totp"]


# Older migrations read the default database through the ORM; it only has to exist.
pytestmark = pytest.mark.django_db

DB = "legacy"


@pytest.fixture
def backups(monkeypatch):
    """Records the copies the migration makes, instead of reading the in-memory test database."""
    made = []
    monkeypatch.setattr(backup, "backup_before_upgrade", lambda: made.append("copy"))
    return made


@pytest.fixture
def old_state(backups, tmp_path, django_db_blocker):
    """A database as it was with counters, and ``apps`` to fill it with the old models."""
    # The database is not one pytest-django knows, so it must be allowed to touch it.
    with django_db_blocker.unblock():
        default = connections.settings["default"]
        connections.settings[DB] = {**default, "NAME": str(tmp_path / "legacy.sqlite3")}
        try:
            executor = MigrationExecutor(connections[DB])
            others = [n for n in executor.loader.graph.leaf_nodes() if n[0] in OTHER_APPS]
            executor.migrate(BEFORE + others)
            yield MigrationExecutor(connections[DB]).loader.project_state(BEFORE + others).apps
        finally:
            connections[DB].close()
            del connections[DB]
            del connections.settings[DB]


def convert():
    MigrationExecutor(connections[DB]).migrate([REKEY])


def test_every_key_and_reference_is_converted(old_state, backups):
    apps = old_state
    Customer = apps.get_model("customers", "Customer")
    Category = apps.get_model("customers", "Category")
    Project = apps.get_model("projects", "Project")
    Task = apps.get_model("projects", "Task")
    User = apps.get_model("accounts", "User")
    ApiToken = apps.get_model("accounts", "ApiToken")
    TimeEntry = apps.get_model("tracking", "TimeEntry")
    Invoice = apps.get_model("billing", "Invoice")
    OutgoingMail = apps.get_model("mailer", "OutgoingMail")
    TOTPDevice = apps.get_model("otp_totp", "TOTPDevice")
    Session = apps.get_model("sessions", "Session")
    LogEntry = apps.get_model("admin", "LogEntry")
    ContentType = apps.get_model("contenttypes", "ContentType")

    kim = User.objects.db_manager(DB).create(username="kim", password="x")
    mia = User.objects.db_manager(DB).create(username="mia", password="x", role="employee")
    customers = [Customer.objects.db_manager(DB).create(name=name) for name in ("Anton", "Berta", "Carla")]
    customers[0].categories.add(Category.objects.db_manager(DB).create(name="Stammkunde"))
    mia.bookable_customers.add(customers[1])
    project = Project.objects.db_manager(DB).create(customer=customers[0], name="Website")
    mia.bookable_projects.add(project)
    task = Task.objects.db_manager(DB).create(project=project, name="Entwicklung")
    invoice = Invoice.objects.db_manager(DB).create(
        customer=customers[0], period_start="2026-10-01", period_end="2026-10-31", total_net=100
    )
    start = datetime(2026, 10, 1, 9, tzinfo=UTC)
    TimeEntry.objects.db_manager(DB).create(
        user=kim, task=task, started_at=start, ended_at=start + timedelta(hours=1), invoice=invoice
    )
    running = TimeEntry.objects.db_manager(DB).create(user=mia, task=task, started_at=start + timedelta(days=1))
    ApiToken.objects.db_manager(DB).create(user=kim, name="Laptop", key_hash="a" * 64, hint="lxt_abc")
    TOTPDevice.objects.db_manager(DB).create(user=kim, name="Handy", key="00" * 20)
    Session.objects.db_manager(DB).create(session_key="s", session_data="x", expire_date=start)
    LogEntry.objects.db_manager(DB).create(
        user=kim,
        content_type=ContentType.objects.db_manager(DB).get_or_create(app_label="customers", model="customer")[0],
        object_id=str(customers[1].pk),
        object_repr="Berta",
        action_flag=1,
    )
    for key, user in (
        (f"weekly-report:{kim.pk}:2026-10-19", kim),
        (f"timer-reminder:{running.pk}", mia),
        (f"invoice-overdue:{invoice.pk}:2026-10-10:customer", None),
        (f"invoice-overdue:{invoice.pk}:2026-10-10:user:{kim.pk}", kim),
    ):
        OutgoingMail.objects.db_manager(DB).create(
            kind="x", user=user, to="a@example.de", subject="s", text="t", dedupe_key=key
        )

    convert()

    assert backups == ["copy"]
    users = {u.username: u for u in NewUser.objects.using(DB).all()}
    assert all(isinstance(u.pk, uuid.UUID) and u.pk.version == 7 for u in users.values())

    # Keys are in the order of the old counters, so sorting by key still sorts by age.
    assert [c.name for c in NewCustomer.objects.using(DB).order_by("pk")] == ["Anton", "Berta", "Carla"]

    anton = NewCustomer.objects.using(DB).get(name="Anton")
    assert [c.name for c in anton.categories.all()] == ["Stammkunde"]
    assert [p.name for p in anton.projects.all()] == ["Website"]
    assert [c.name for c in users["mia"].bookable_customers.all()] == ["Berta"]
    assert [p.name for p in users["mia"].bookable_projects.all()] == ["Website"]
    new_invoice = NewInvoice.objects.using(DB).get()
    assert new_invoice.customer == anton
    billed_entry = NewTimeEntry.objects.using(DB).get(user=users["kim"])
    assert billed_entry.invoice == new_invoice and billed_entry.task.project.customer == anton
    assert NewTimeEntry.objects.using(DB).get(ended_at=None).user == users["mia"]
    assert NewApiToken.objects.using(DB).get().user == users["kim"]

    # Tables from other packages.
    assert NewTOTPDevice.objects.using(DB).get().user == users["kim"]
    log = NewLogEntry.objects.using(DB).get()
    assert log.user == users["kim"] and NewCustomer.objects.using(DB).get(pk=log.object_id).name == "Berta"
    assert not NewSession.objects.using(DB).exists()  # They hold the old counter of the user.

    # Queued e-mails are still recognised as sent once.
    assert set(NewOutgoingMail.objects.using(DB).values_list("dedupe_key", flat=True)) == {
        f"weekly-report:{users['kim'].pk}:2026-10-19",
        f"timer-reminder:{NewTimeEntry.objects.using(DB).get(ended_at=None).pk}",
        f"invoice-overdue:{new_invoice.pk}:2026-10-10:customer",
        f"invoice-overdue:{new_invoice.pk}:2026-10-10:user:{users['kim'].pk}",
    }

    with connections[DB].cursor() as cursor:
        cursor.execute("PRAGMA foreign_key_check")
        assert cursor.fetchall() == []


def test_a_fresh_installation_makes_no_copy(old_state, backups):
    convert()
    assert backups == []
