"""The date ranges a report can cover."""

from dataclasses import dataclass
from datetime import date, timedelta

from billing.periods import Period, period_containing


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
        DateRange("monat", "Dieser Monat", month.start, month.end),
        DateRange("vormonat", "Letzter Monat", last_month.start, last_month.end),
        DateRange("quartal", "Dieses Quartal", quarter.start, quarter.end),
        DateRange("vorquartal", "Letztes Quartal", last_quarter.start, last_quarter.end),
        DateRange("jahr", "Dieses Jahr", year.start, year.end),
        DateRange("vorjahr", "Letztes Jahr", last_year.start, last_year.end),
    ]


def selected_range(params, today: date) -> DateRange:
    """The range from ``?zeitraum=`` or ``?von=``/``?bis=``; this month by default."""
    options = presets(today)
    try:
        start, end = date.fromisoformat(params.get("von", "")), date.fromisoformat(params.get("bis", ""))
    except ValueError:
        pass
    else:
        if start <= end:
            return DateRange("", f"{start:%d.%m.%Y} – {end:%d.%m.%Y}", start, end)
    return next((r for r in options if r.key == params.get("zeitraum")), options[0])
