"""Figures for the reports page. Plain functions; the view runs them in a thread."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from billing.calculation import CENT, to_hours
from billing.models import BillingAgreement, Invoice
from billing.periods import period_containing
from core.models import AppSettings
from projects.models import Project
from reports.ranges import DateRange
from tracking.models import TimeEntry
from tracking.queries import booked_time

# Invoices that count as revenue. Voided and deleted ones do not.
BILLED_STATUSES = [s for s in Invoice.Status.values if s not in (Invoice.Status.VOIDED, Invoice.Status.DELETED)]
OPEN_STATUSES = [Invoice.Status.OPEN, Invoice.Status.OVERDUE, Invoice.Status.TRANSFERRED, Invoice.Status.SEPADEBIT]
MONTHS = ["Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"]


@dataclass
class Totals:
    total: timedelta = field(default_factory=timedelta)
    billable: timedelta = field(default_factory=timedelta)
    unbilled: timedelta = field(default_factory=timedelta)

    def add(self, entry: TimeEntry) -> None:
        self.total += entry.duration
        if entry.is_billable and entry.task.is_billable:
            self.billable += entry.duration
            if entry.invoice_id is None:
                self.unbilled += entry.duration

    @property
    def billable_share(self) -> int:
        return round(self.billable / self.total * 100) if self.total else 0


@dataclass
class Row(Totals):
    obj: object = None
    invoiced: Decimal = Decimal("0")
    # Projects only: everything ever booked, against the budget.
    booked_all_time: timedelta | None = None

    @property
    def budget_share(self) -> int | None:
        budget = getattr(self.obj, "budget_hours", None)
        if not budget or self.booked_all_time is None:
            return None
        return round(to_hours(self.booked_all_time) / budget * 100)


@dataclass
class Bucket:
    label: str
    total: timedelta
    billable: timedelta
    # Bar height relative to the longest bar, and the billable part of the bar.
    share: int = 0

    @property
    def billable_part(self) -> int:
        return round(self.billable / self.total * 100) if self.total else 0


@dataclass
class Retainer:
    agreement: BillingAgreement
    period_label: str
    used: timedelta

    @property
    def included(self) -> timedelta:
        return timedelta(hours=float(self.agreement.included_hours))

    @property
    def share(self) -> int:
        return round(self.used / self.included * 100) if self.included else 0

    @property
    def remaining(self) -> timedelta:
        return max(self.included - self.used, timedelta())

    @property
    def overage(self) -> timedelta:
        return max(self.used - self.included, timedelta())


@dataclass
class Report:
    range: DateRange
    totals: Totals
    customers: list[Row]
    projects: list[Row]
    buckets: list[Bucket]
    invoiced: Decimal
    paid: Decimal
    open: Decimal
    drafts: Decimal
    unbilled_value: Decimal
    unbilled_value_skips_retainers: bool
    retainers: list[Retainer]


def _bounds(start: date, end: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    return datetime.combine(start, time.min, tzinfo=tz), datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz)


def entries_in(start: date, end: date, customer_id: int | None = None):
    """Finished entries that started in the range, oldest first."""
    since, until = _bounds(start, end)
    entries = TimeEntry.objects.filter(ended_at__isnull=False, started_at__gte=since, started_at__lt=until)
    if customer_id:
        entries = entries.filter(task__project__customer_id=customer_id)
    return entries.select_related("task", "task__project", "task__project__customer", "invoice", "user").order_by(
        "started_at"
    )


# Which entries count as billable and as not yet billed, for the sums below.
BILLABLE = {"is_billable": True, "task__is_billable": True}
UNBILLED = {**BILLABLE, "invoice__isnull": True}


def _sums(entries):
    """Total, billable and unbilled time of ``entries``, summed in the database."""
    return entries.annotate(
        total=booked_time(), billable=booked_time(**BILLABLE), unbilled=booked_time(**UNBILLED)
    ).order_by()


def _add(target: Totals, sums: dict) -> None:
    target.total += sums["total"] or timedelta()
    target.billable += sums["billable"] or timedelta()
    target.unbilled += sums["unbilled"] or timedelta()


def _buckets(entries, rng: DateRange) -> list[Bucket]:
    """Hours per day for ranges up to a month, per month otherwise."""
    by_day = rng.days <= 31
    keys: list = []
    day = rng.start
    while day <= rng.end:
        key = day if by_day else (day.year, day.month)
        if key not in keys:
            keys.append(key)
        day += timedelta(days=1)
    totals = {key: [timedelta(), timedelta()] for key in keys}
    trunc = (TruncDate if by_day else TruncMonth)("started_at", tzinfo=timezone.get_current_timezone())
    for row in _sums(entries.annotate(bucket=trunc).values("bucket")):
        bucket = row["bucket"]
        key = bucket if by_day else (bucket.year, bucket.month)
        if key in totals:
            totals[key][0] += row["total"] or timedelta()
            totals[key][1] += row["billable"] or timedelta()
    longest = max((t for t, _ in totals.values()), default=timedelta()) or timedelta(hours=1)
    buckets = []
    for key, (total, billable) in totals.items():
        label = f"{key:%d.}" if by_day else f"{MONTHS[key[1] - 1]} {key[0] % 100:02d}"
        buckets.append(Bucket(label, total, billable, round(total / longest * 100)))
    return buckets


def _retainers(today: date, customer_id: int | None) -> list[Retainer]:
    agreements = (
        BillingAgreement.objects.filter(kind=BillingAgreement.Kind.RETAINER, valid_from__lte=today)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=today))
        .select_related("customer")
        .order_by("customer__name")
    )
    if customer_id:
        agreements = agreements.filter(customer_id=customer_id)
    result = []
    for agreement in agreements:
        period = period_containing(today, agreement.period)
        since, until = _bounds(period.start, period.end)
        used = TimeEntry.objects.filter(
            task__project__customer=agreement.customer,
            is_billable=True,
            task__is_billable=True,
            ended_at__isnull=False,
            started_at__gte=since,
            started_at__lt=until,
        ).aggregate(t=booked_time())["t"]
        result.append(Retainer(agreement, period.label, used or timedelta()))
    return result


def build_report(rng: DateRange, customer_id: int | None = None, today: date | None = None) -> Report:
    today = today or timezone.localdate()
    since, until = _bounds(rng.start, rng.end)
    entries = TimeEntry.objects.filter(ended_at__isnull=False, started_at__gte=since, started_at__lt=until)
    if customer_id:
        entries = entries.filter(task__project__customer_id=customer_id)

    # One row per task with its sums and what its hourly rate falls back to, instead of every entry.
    per_task = list(
        _sums(
            entries.values(
                "task_id",
                "task__hourly_rate",
                "task__project_id",
                "task__project__hourly_rate",
                "task__project__customer_id",
                "task__project__customer__default_hourly_rate",
            )
        )
    )
    project_objects = Project.objects.select_related("customer").in_bulk({r["task__project_id"] for r in per_task})

    totals = Totals()
    customers: dict[int, Row] = {}
    projects: dict[int, Row] = {}
    for row in per_task:
        project = project_objects[row["task__project_id"]]
        _add(totals, row)
        _add(customers.setdefault(project.customer_id, Row(obj=project.customer)), row)
        _add(projects.setdefault(project.pk, Row(obj=project)), row)

    invoices = Invoice.objects.filter(period_end__gte=rng.start, period_end__lte=rng.end, status__in=BILLED_STATUSES)
    if customer_id:
        invoices = invoices.filter(customer_id=customer_id)
    invoiced_by_customer = dict(invoices.values_list("customer").annotate(s=Sum("total_net")).order_by())
    for pk, amount in invoiced_by_customer.items():
        if pk in customers:
            customers[pk].invoiced = amount
    sums = {status: amount for status, amount in invoices.values_list("status").annotate(s=Sum("total_net")).order_by()}

    booked = dict(
        Project.objects.filter(pk__in=projects).annotate(b=booked_time("tasks__time_entries__")).values_list("pk", "b")
    )
    for pk, row in projects.items():
        row.booked_all_time = booked.get(pk) or timedelta()

    # What the unbilled time would bring at the hourly rate. Retainer customers are left
    # out, since their time is mostly covered by the fixed price.
    retainer_customers = set(
        BillingAgreement.objects.filter(kind=BillingAgreement.Kind.RETAINER, valid_from__lte=rng.end)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=rng.start))
        .values_list("customer_id", flat=True)
    )
    fallback = AppSettings.load().default_hourly_rate
    unbilled_value = Decimal("0")
    for row in per_task:
        if not row["unbilled"] or row["task__project__customer_id"] in retainer_customers:
            continue
        rates = ("task__hourly_rate", "task__project__hourly_rate", "task__project__customer__default_hourly_rate")
        rate = next((row[r] for r in rates if row[r] is not None), fallback)
        if rate is not None:
            unbilled_value += to_hours(row["unbilled"]) * rate

    return Report(
        range=rng,
        totals=totals,
        customers=sorted(customers.values(), key=lambda r: r.total, reverse=True),
        projects=sorted(projects.values(), key=lambda r: r.total, reverse=True),
        buckets=_buckets(entries, rng),
        invoiced=sum(sums.values(), Decimal("0")),
        paid=sums.get(Invoice.Status.PAID, Decimal("0")),
        open=sum((sums.get(s, Decimal("0")) for s in OPEN_STATUSES), Decimal("0")),
        drafts=sums.get(Invoice.Status.DRAFT, Decimal("0")),
        unbilled_value=unbilled_value.quantize(CENT),
        unbilled_value_skips_retainers=bool(retainer_customers & set(customers)),
        retainers=_retainers(today, customer_id),
    )
