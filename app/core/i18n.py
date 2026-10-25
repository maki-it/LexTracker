"""Texts that are translated later, in the language of whoever reads them.

Jobs run in the scheduler, which has no request and so no language. They build messages with ``fmt`` and
hand them over lazily; the code that stores the message for a user turns them into text in that user's language.
"""

from django.utils import dateformat
from django.utils.functional import Promise, lazy
from django.utils.translation import pgettext


def _fill(message, **values) -> str:
    return str(message) % {name: str(value) if isinstance(value, Promise) else value for name, value in values.items()}


fmt = lazy(_fill, str)
"""``fmt(_("%(count)d new"), count=3)``: the translation with the values filled in, once the text is needed."""


def _date_format(user_format: str) -> str:
    # Translators: the long date format "31. Dezember 2026" without the full stop that German puts after the day.
    return pgettext("long date format", "j. F Y") if user_format == "j. F Y" else user_format


date_format = lazy(_date_format, str)
"""The date format a user picked (``User.date_format``), worded for the language it is shown in."""


def _datetime_format(user_format: str) -> str:
    return f"{_date_format(user_format)}, H:i"


datetime_format = lazy(_datetime_format, str)
"""``date_format`` plus the time of day."""


def short_date(value) -> str:
    """Day and month in the order of the language: ``31.12.`` or ``31 Dec``."""
    # Translators: Django date format for a day and month without the year.
    return dateformat.format(value, pgettext("date format", "d.m."))


def full_date(value) -> str:
    """Day, month and year in the order of the language: ``31.12.2026`` or ``31 Dec 2026``."""
    # Translators: Django date format for a full date.
    return dateformat.format(value, pgettext("date format", "d.m.Y"))
