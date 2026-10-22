from django.http import HttpRequest

from accounts.models import User


def preferences(request: HttpRequest) -> dict:
    """The signed-in user's display settings, for ``base.html`` and ``|date:date_format``."""
    user = getattr(request, "user", None)
    date_format = getattr(user, "date_format", User.DateFormat.NUMERIC)
    return {
        "theme": getattr(user, "theme", User.Theme.SYSTEM),
        "date_format": date_format,
        "datetime_format": f"{date_format}, H:i",
        "duration_format": getattr(user, "duration_format", User.DurationFormat.CLOCK),
    }
