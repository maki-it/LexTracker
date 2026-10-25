from django.db.models import DurationField, F, Func, Q, Sum

from core.ids import parse_uuid
from customers.models import Customer
from projects.models import Project


class Duration(Func):
    """``end - start`` in SQLite itself, to the millisecond.

    Django subtracts datetimes on SQLite with a Python function called for every row, which made
    sums over many entries slow (see loadtest/). The result is in microseconds, as Django stores durations.
    """

    template = "(CAST(ROUND((julianday(%(expressions)s)) * 86400000) AS INTEGER) * 1000)"
    arg_joiner = ") - julianday("
    output_field = DurationField()


def booked_time(prefix: str = "", **filters) -> Sum:
    """Sum of finished time entries; running timers count as zero.

    ``prefix`` is the path to the entries, e.g. "time_entries__" when annotating tasks.
    Extra ``filters`` are applied to the entries, without the prefix.
    """
    return Sum(
        Duration(F(f"{prefix}ended_at"), F(f"{prefix}started_at")),
        filter=Q(**{f"{prefix}ended_at__isnull": False}, **{f"{prefix}{k}": v for k, v in filters.items()}),
    )


async def entry_filter(request) -> dict:
    """The customer or project filter of a time entry list (``?customer=`` or ``?project=``).

    Returns the queryset filters plus what the template needs to show the active filter.
    """
    project_id = parse_uuid(request.GET.get("project", ""))
    customer_id = parse_uuid(request.GET.get("customer", ""))
    if project_id:
        project = await Project.objects.select_related("customer").filter(pk=project_id).afirst()
        if project:
            return {"filters": {"task__project": project}, "label": f"{project.customer.name} · {project.name}"}
    if customer_id:
        customer = await Customer.objects.filter(pk=customer_id).afirst()
        if customer:
            return {"filters": {"task__project__customer": customer}, "label": customer.name}
    return {"filters": {}, "label": ""}
