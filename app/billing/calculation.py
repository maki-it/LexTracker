"""Turn unbilled time entries into invoice lines."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Q
from django.utils import timezone

from billing.models import BillingAgreement
from billing.periods import periods_between
from core.models import AppSettings
from customers.models import Customer
from tracking.models import TimeEntry

CENT = Decimal("0.01")


def to_hours(duration: timedelta) -> Decimal:
    return (Decimal(duration.total_seconds()) / 3600).quantize(CENT, ROUND_HALF_UP)


def _german_number(value: Decimal) -> str:
    """``Decimal("2.50")`` becomes ``"2,5"`` for text on the invoice."""
    return f"{value.normalize():f}".replace(".", ",")


@dataclass
class Line:
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    description: str = ""
    # The time behind the line, shown in the preview. Not sent to Lexware.
    entries: list[TimeEntry] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return (self.quantity * self.unit_price).quantize(CENT, ROUND_HALF_UP)


@dataclass
class Draft:
    customer: Customer
    start: date
    end: date
    agreement: BillingAgreement | None
    # Used when neither task, project nor customer has a rate.
    fallback_rate: Decimal | None = None
    lines: list[Line] = field(default_factory=list)
    entries: list[TimeEntry] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def total(self) -> Decimal:
        return sum((line.total for line in self.lines), Decimal("0"))

    @property
    def duration(self) -> timedelta:
        return sum((e.duration for e in self.entries), timedelta())

    @property
    def can_be_invoiced(self) -> bool:
        return bool(self.lines) and not self.problems


def unbilled(customer: Customer):
    """The customer's finished, billable time that has not been billed yet."""
    return TimeEntry.objects.filter(
        task__project__customer=customer,
        is_billable=True,
        task__is_billable=True,
        invoice__isnull=True,
        ended_at__isnull=False,
    )


def unbilled_entries(customer: Customer, start: date, end: date) -> list[TimeEntry]:
    tz = timezone.get_current_timezone()
    return list(
        unbilled(customer)
        .filter(
            started_at__gte=datetime.combine(start, time.min, tzinfo=tz),
            started_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
        )
        .select_related("task", "task__project", "task__project__customer")
        .order_by("started_at")
    )


def active_agreement(customer: Customer, start: date, end: date) -> BillingAgreement | None:
    return (
        customer.billing_agreements.filter(valid_from__lte=end)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=start))
        .order_by("-valid_from")
        .first()
    )


def _hourly_lines(entries: list[TimeEntry], draft: Draft, label_prefix: str = "", rate: Decimal | None = None):
    """Group entries by project, task and rate into lines of hours."""
    groups: dict[tuple, list[TimeEntry]] = defaultdict(list)
    for entry in entries:
        entry_rate = next(
            (r for r in (rate, entry.task.effective_hourly_rate, draft.fallback_rate) if r is not None), None
        )
        if entry_rate is None:
            problem = f"Für „{entry.task.project.name} · {entry.task.name}“ ist kein Stundensatz hinterlegt."
            if problem not in draft.problems:
                draft.problems.append(problem)
            continue
        groups[(entry.task.project.name, entry.task.name, entry_rate)].append(entry)
    for (project, task, entry_rate), group in groups.items():
        duration = sum((e.duration for e in group), timedelta())
        draft.lines.append(
            Line(f"{label_prefix}{project} · {task}", to_hours(duration), "Stunden", entry_rate, entries=group)
        )


def _part(entry: TimeEntry, duration: timedelta) -> TimeEntry:
    """An unsaved copy of ``entry`` that lasts ``duration``, for splitting it between lines."""
    part = TimeEntry(task=entry.task, started_at=entry.started_at, description=entry.description)
    part.ended_at = entry.started_at + duration
    return part


def _period_key(day: date, periods):
    return next(p for p in periods if p.start <= day <= p.end)


def build_draft(customer: Customer, start: date, end: date) -> Draft:
    """Calculate the invoice for ``customer`` and the period from ``start`` to ``end`` (inclusive)."""
    agreement = active_agreement(customer, start, end)
    entries = unbilled_entries(customer, start, end)
    app_settings = AppSettings.load()
    draft = Draft(
        customer,
        start,
        end,
        agreement,
        fallback_rate=app_settings.default_hourly_rate,
        entries=entries,
    )

    if agreement is None or agreement.kind == BillingAgreement.Kind.HOURLY:
        _hourly_lines(entries, draft)
        return draft

    # Retainer: every period in the range costs the fixed price and includes a number of
    # hours. Hours are used up in the order they were worked; the rest is billed extra.
    periods = periods_between(start, end, agreement.period)
    included = timedelta(hours=float(agreement.included_hours))
    by_period: dict = defaultdict(list)
    for entry in entries:
        by_period[_period_key(timezone.localtime(entry.started_at).date(), periods)].append(entry)

    for period in periods:
        retainer = Line(
            f"Retainer {period.label}",
            Decimal("1"),
            "Pauschale",
            agreement.fixed_price,
            description=f"Enthält {_german_number(agreement.included_hours)} Stunden.",
        )
        draft.lines.append(retainer)
        remaining = included
        overage: list[TimeEntry] = []
        for entry in by_period[period]:
            if entry.duration <= remaining:
                remaining -= entry.duration
                retainer.entries.append(entry)
                continue
            # Split the entry: the part beyond the remaining contingent is billed extra.
            if remaining:
                retainer.entries.append(_part(entry, remaining))
            overage.append(_part(entry, entry.duration - remaining))
            remaining = timedelta()
        _hourly_lines(overage, draft, label_prefix=f"Mehrstunden {period.label}: ", rate=agreement.overage_rate)
    return draft
