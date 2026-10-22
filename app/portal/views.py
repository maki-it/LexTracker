"""The read-only portal for customer logins. Everything is limited to the user's customer."""

from datetime import timedelta

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from billing.models import Invoice
from billing.periods import Period, period_containing
from customers.models import Customer
from projects.models import Project
from reports.ranges import presets, selected_range
from tracking.models import TimeEntry
from tracking.queries import booked_time

# Drafts may still change and deleted invoices were never sent.
HIDDEN_INVOICE_STATUSES = [Invoice.Status.DRAFT, Invoice.Status.DELETED]


def _customer_entries(user):
    return TimeEntry.objects.filter(task__project__customer_id=user.customer_id, ended_at__isnull=False)


@require_GET
async def overview(request: HttpRequest) -> HttpResponse:
    user = request.user
    month = period_containing(timezone.localdate(), Period.MONTH)
    projects = [
        p
        async for p in Project.objects.filter(customer_id=user.customer_id)
        .exclude(status=Project.Status.PLANNED)
        .annotate(
            booked=booked_time("tasks__time_entries__"),
            booked_month=booked_time("tasks__time_entries__", started_at__date__gte=month.start),
        )
        .order_by("status", "name")
    ]
    for project in projects:
        project.budget_share = (
            round(project.booked.total_seconds() / 3600 / float(project.budget_hours) * 100)
            if project.budget_hours and project.booked
            else None
        )
    context = {
        "customer": await Customer.objects.aget(pk=user.customer_id),
        "projects": projects,
        "month_total": sum((p.booked_month or timedelta() for p in projects), timedelta()),
        "month": month,
        "open_invoices": await Invoice.objects.filter(
            customer_id=user.customer_id, status__in=[Invoice.Status.OPEN, Invoice.Status.OVERDUE]
        ).acount()
        if user.portal_invoices
        else None,
    }
    return render(request, "portal/overview.html", context)


@require_GET
async def entries(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not user.portal_entries:
        raise PermissionDenied
    today = timezone.localdate()
    date_range = selected_range(request.GET, today)
    queryset = _customer_entries(user).filter(
        started_at__date__gte=date_range.start, started_at__date__lte=date_range.end
    )
    project_id = request.GET.get("projekt", "")
    if project_id.isdigit():
        queryset = queryset.filter(task__project_id=int(project_id))
    rows = [e async for e in queryset.select_related("task", "task__project").order_by("-started_at")]
    context = {
        "entries": rows,
        "total": sum((e.duration for e in rows), timedelta()),
        "range": date_range,
        "presets": presets(today),
        "projects": [p async for p in Project.objects.filter(customer_id=user.customer_id).order_by("name")],
        "project_id": int(project_id) if project_id.isdigit() else None,
    }
    return render(request, "portal/entries.html", context)


@require_GET
async def invoices(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not user.portal_invoices:
        raise PermissionDenied
    rows = [
        i
        async for i in Invoice.objects.filter(customer_id=user.customer_id)
        .exclude(status__in=HIDDEN_INVOICE_STATUSES)
        .order_by("-period_end")
    ]
    return render(request, "portal/invoices.html", {"invoices": rows})
