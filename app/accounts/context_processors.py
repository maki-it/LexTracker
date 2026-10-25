from django.http import HttpRequest

from accounts.models import User
from core import i18n


def preferences(request: HttpRequest) -> dict:
    """The signed-in user's display settings, for ``base.html`` and ``|date:date_format``."""
    user = getattr(request, "user", None)
    date_format = getattr(user, "date_format", User.DateFormat.NUMERIC)
    return {
        "theme": getattr(user, "theme", User.Theme.SYSTEM),
        "date_format": str(i18n.date_format(date_format)),
        "datetime_format": str(i18n.datetime_format(date_format)),
        "duration_format": getattr(user, "duration_format", User.DurationFormat.CLOCK),
    }
