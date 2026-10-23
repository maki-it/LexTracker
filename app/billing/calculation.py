"""Turn unbilled time entries into invoice lines."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import Max, Min, Q
from django.utils import timezone

from billing.models import BillingAgreement
from billing.periods import periods_between
from core.models import AppSettings
from customers.models import Customer
from projects.models import Project
from tracking.models import TimeEntry

CENT = Decimal("0.01")


def to_hours(duration: timedelta) -> Decimal:
    return (Decimal(duration.total_seconds()) / 3600).quantize(CENT, ROUND_HALF_UP)


def _german_number(value: Decimal) -> str:
    """``Decimal("2.50")`` becomes ``"2,5"`` for text on the invoice."""
    return f"{value.normalize():f}".replace(".", ",")


def _span(start: date, end: date) -> str:
    """A single day as ``05.10.2026``, a range as ``05.10.2026 to 28.10.2026`` (with an en dash)."""
    if start == end:
        return f"{start:%d.%m.%Y}"
    return f"{start:%d.%m.%Y} – {end:%d.%m.%Y}"


def _worked_span(entries: list[TimeEntry]) -> str:
    days = [timezone.localtime(e.started_at).date() for e in entries]
    return _span(min(days), max(days))


@dataclass
class Line:
    # What the customer reads on the invoice: a short name of the service, and the details below it.
    name: str
    quantity: Decimal
    unit: str
    unit_price: Decimal
    description: str = ""
    # A retainer's fixed price, as opposed to hours billed at a rate.
    fixed: bool = False
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
        # Prefetched, not joined: each task, project and user is loaded once, not once per entry.
        .prefetch_related("user", "task__project__customer")
        .order_by("started_at")
    )


def active_agreement(customer: Customer, start: date, end: date) -> BillingAgreement | None:
    return (
        customer.billing_agreements.filter(valid_from__lte=end)
        .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=start))
        .order_by("-valid_from")
        .first()
    )


def _hourly_lines(entries: list[TimeEntry], draft: Draft, rate: Decimal | None = None, extra: str = ""):
    """Group entries by project, task and rate into lines of hours.

    A line is named after the task. The project and the days worked go into the description,
    followed by ``extra`` if given. ``extra`` also marks the lines as extra hours.
    """
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
        description = [f"Projekt: {project}", f"Zeitraum: {_worked_span(group)}"]
        if extra:
            description.append(extra)
        draft.lines.append(
            Line(
                f"{task} (Mehrstunden)" if extra else task,
                to_hours(duration),
                "Stunden",
                entry_rate,
                description="\n".join(description),
                entries=group,
            )
        )


def _part(entry: TimeEntry, duration: timedelta) -> TimeEntry:
    """An unsaved copy of ``entry`` that lasts ``duration``, for splitting it between lines."""
    part = TimeEntry(
        pk=entry.pk,
        user=entry.user,
        task=entry.task,
        started_at=entry.started_at,
        description=entry.description,
    )
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
            description=f"Enthält {_german_number(agreement.included_hours)} Stunden.\nZeitraum: "
            f"{_span(period.start, period.end)}",
            fixed=True,
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
        _hourly_lines(
            overage,
            draft,
            rate=agreement.overage_rate,
            extra=f"Über das Kontingent des Retainers {period.label} hinaus.",
        )
    return draft


def open_draft(customer: Customer) -> Draft | None:
    """The invoice for all of the customer's open time at once, or ``None`` if there is none."""
    bounds = unbilled(customer).aggregate(first=Min("started_at"), last=Max("started_at"))
    if bounds["first"] is None:
        return None
    return build_draft(customer, timezone.localtime(bounds["first"]).date(), timezone.localtime(bounds["last"]).date())


@dataclass
class EntryRow:
    """One time entry of a draft and what becomes of it on the invoice."""

    entry: TimeEntry
    # The part inside a retainer's included hours, and the part billed at ``rate``.
    included: timedelta = timedelta()
    billed: timedelta = timedelta()
    rate: Decimal | None = None

    @property
    def amount(self) -> Decimal | None:
        return None if self.rate is None else (to_hours(self.billed) * self.rate).quantize(CENT, ROUND_HALF_UP)

    @property
    def has_rate(self) -> bool:
        """False if the entry stays off the invoice because no rate is set."""
        return self.rate is not None or bool(self.included)


@dataclass
class ProjectRows:
    project: Project
    rows: list[EntryRow] = field(default_factory=list)
    # Of the draft's lines, so it adds up to what the invoice shows.
    amount: Decimal = Decimal("0")

    @property
    def duration(self) -> timedelta:
        return sum((r.entry.duration for r in self.rows), timedelta())

    @property
    def included(self) -> timedelta:
        return sum((r.included for r in self.rows), timedelta())

    @property
    def without_rate(self) -> int:
        return sum(1 for r in self.rows if not r.has_rate)


def entries_by_project(draft: Draft) -> list[ProjectRows]:
    """The draft's time entries by project, with the line each one ends up on.

    An entry that a retainer splits between its included hours and extra hours is one row.
    """
    rows = {e.pk: EntryRow(e) for e in draft.entries}
    amounts: dict[int, Decimal] = defaultdict(Decimal)
    for line in draft.lines:
        for entry in line.entries:
            row = rows[entry.pk]
            if line.fixed:
                row.included += entry.duration
            else:
                row.billed += entry.duration
                row.rate = line.unit_price
        if line.entries and not line.fixed:
            amounts[line.entries[0].task.project_id] += line.total
    projects: dict[int, ProjectRows] = {}
    for row in rows.values():
        project = row.entry.task.project
        group = projects.setdefault(project.pk, ProjectRows(project, amount=amounts[project.pk]))
        group.rows.append(row)
    return sorted(projects.values(), key=lambda g: g.project.name.lower())
