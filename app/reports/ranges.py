"""The date ranges a report can cover."""

from dataclasses import dataclass
from datetime import date, timedelta

from django.utils.translation import gettext as _

from billing.periods import Period, period_containing
from core.i18n import full_date


@dataclass(frozen=True)
class DateRange:
    key: str
    label: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def presets(today: date) -> list[DateRange]:
    month = period_containing(today, Period.MONTH)
    last_month = period_containing(month.start - timedelta(days=1), Period.MONTH)
    quarter = period_containing(today, Period.QUARTER)
    last_quarter = period_containing(quarter.start - timedelta(days=1), Period.QUARTER)
    year = period_containing(today, Period.YEAR)
    last_year = period_containing(year.start - timedelta(days=1), Period.YEAR)
    return [
        DateRange("month", _("Dieser Monat"), month.start, month.end),
        DateRange("last-month", _("Letzter Monat"), last_month.start, last_month.end),
        DateRange("quarter", _("Dieses Quartal"), quarter.start, quarter.end),
        DateRange("last-quarter", _("Letztes Quartal"), last_quarter.start, last_quarter.end),
        DateRange("year", _("Dieses Jahr"), year.start, year.end),
        DateRange("last-year", _("Letztes Jahr"), last_year.start, last_year.end),
    ]


def selected_range(params, today: date) -> DateRange:
    """The range from ``?range=`` or ``?from=``/``?to=``; this month by default."""
    options = presets(today)
    try:
        start, end = date.fromisoformat(params.get("from", "")), date.fromisoformat(params.get("to", ""))
    except ValueError:
        pass
    else:
        if start <= end:
            return DateRange("", f"{full_date(start)} – {full_date(end)}", start, end)
    return next((r for r in options if r.key == params.get("range")), options[0])
