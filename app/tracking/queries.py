from django.db.models import DurationField, ExpressionWrapper, F, Q, Sum

from customers.models import Customer
from projects.models import Project


def booked_time(prefix: str = "", **filters) -> Sum:
    """Sum of finished time entries; running timers count as zero.

    ``prefix`` is the path to the entries, e.g. "time_entries__" when annotating tasks.
    Extra ``filters`` are applied to the entries, without the prefix.
    """
    return Sum(
        ExpressionWrapper(F(f"{prefix}ended_at") - F(f"{prefix}started_at"), output_field=DurationField()),
        filter=Q(**{f"{prefix}ended_at__isnull": False}, **{f"{prefix}{k}": v for k, v in filters.items()}),
    )


async def entry_filter(request) -> dict:
    """The customer or project filter of a time entry list (``?kunde=`` or ``?projekt=``).

    Returns the queryset filters plus what the template needs to show the active filter.
    """
    project_id = request.GET.get("projekt", "")
    customer_id = request.GET.get("kunde", "")
    if project_id.isdigit():
        project = await Project.objects.select_related("customer").filter(pk=int(project_id)).afirst()
        if project:
            return {"filters": {"task__project": project}, "label": f"{project.customer.name} · {project.name}"}
    if customer_id.isdigit():
        customer = await Customer.objects.filter(pk=int(customer_id)).afirst()
        if customer:
            return {"filters": {"task__project__customer": customer}, "label": customer.name}
    return {"filters": {}, "label": ""}
