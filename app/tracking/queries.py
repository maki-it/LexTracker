from django.db.models import DurationField, ExpressionWrapper, F, Q, Sum


def booked_time(prefix: str = "", **filters) -> Sum:
    """Sum of finished time entries; running timers count as zero.

    ``prefix`` is the path to the entries, e.g. "time_entries__" when annotating tasks.
    Extra ``filters`` are applied to the entries, without the prefix.
    """
    return Sum(
        ExpressionWrapper(F(f"{prefix}ended_at") - F(f"{prefix}started_at"), output_field=DurationField()),
        filter=Q(**{f"{prefix}ended_at__isnull": False}, **{f"{prefix}{k}": v for k, v in filters.items()}),
    )
