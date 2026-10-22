"""Billing periods (month, quarter, year) and their date ranges."""

from dataclasses import dataclass
from datetime import date, timedelta

from billing.models import BillingAgreement

Period = BillingAgreement.Period


@dataclass(frozen=True, order=True)
class BillingPeriod:
    start: date
    end: date
    label: str


def period_containing(day: date, period: str) -> BillingPeriod:
    if period == Period.YEAR:
        return BillingPeriod(date(day.year, 1, 1), date(day.year, 12, 31), str(day.year))
    months = 3 if period == Period.QUARTER else 1
    first_month = (day.month - 1) // months * months + 1
    start = date(day.year, first_month, 1)
    next_start = date(start.year + 1, 1, 1) if first_month + months > 12 else date(start.year, first_month + months, 1)
    label = f"Q{(first_month - 1) // 3 + 1}/{day.year}" if months == 3 else f"{day.month:02d}/{day.year}"
    return BillingPeriod(start, next_start - timedelta(days=1), label)


def periods_between(start: date, end: date, period: str) -> list[BillingPeriod]:
    """All periods that overlap the range from ``start`` to ``end``."""
    result = []
    current = period_containing(start, period)
    while current.start <= end:
        result.append(current)
        current = period_containing(current.end + timedelta(days=1), period)
    return result


def recent_periods(today: date, period: str, count: int = 4) -> list[BillingPeriod]:
    """The current period and the ones before it, newest first."""
    result = [period_containing(today, period)]
    while len(result) < count:
        result.append(period_containing(result[-1].start - timedelta(days=1), period))
    return result
