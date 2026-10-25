"""The portal for customer logins. Everything is limited to the user's customer.

It is read-only, except that a login may be allowed to change the customer's own contact in Lexware.
"""

import logging
import re
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods

from billing.models import Invoice
from billing.periods import Period, period_containing
from billing.views import STATUS_FILTERS
from core.ids import parse_uuid
from core.shortcuts import arender
from customers.lexware import (
    apply_billing_address,
    apply_contact_person,
    apply_to_contact,
    billing_address,
    contact_person,
)
from customers.models import Customer
from lexware.client import LexwareError, client_from_settings
from lexware.schemas import Contact
from portal.forms import COUNTRIES, ContactForm
from projects.models import Project
from reports.ranges import presets, selected_range
from tracking.models import TimeEntry
from tracking.queries import booked_time

logger = logging.getLogger(__name__)

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
    project_id = parse_uuid(request.GET.get("project", ""))
    if project_id:
        queryset = queryset.filter(task__project_id=project_id)
    rows = [e async for e in queryset.select_related("task", "task__project", "invoice").order_by("-started_at")]
    for entry in rows:
        # Entries of a draft are not billed yet from the customer's side: the draft is not shown to them.
        if entry.invoice and entry.invoice.status in HIDDEN_INVOICE_STATUSES:
            entry.invoice = None
    context = {
        "entries": rows,
        "total": sum((e.duration for e in rows), timedelta()),
        "range": date_range,
        "presets": presets(today),
        "projects": [p async for p in Project.objects.filter(customer_id=user.customer_id).order_by("name")],
        "project_id": project_id,
    }
    return render(request, "portal/entries.html", context)


# The status filters the customer can pick. Drafts and deleted invoices never show up here.
INVOICE_STATUS_FILTERS = {key: STATUS_FILTERS[key] for key in ("open", "overdue", "paid", "voided")}


@require_GET
async def invoices(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not user.portal_invoices:
        raise PermissionDenied
    queryset = _visible_invoices(user)
    status = request.GET.get("status", "")
    if status in INVOICE_STATUS_FILTERS:
        queryset = queryset.filter(status__in=INVOICE_STATUS_FILTERS[status][1])
    else:
        status = ""
    today = timezone.localdate()
    # All invoices unless a range is picked, by invoice date (the creation day for invoices without one).
    date_range = selected_range(request.GET, today) if {"range", "from", "to"} & set(request.GET) else None
    if date_range:
        span = (date_range.start, date_range.end)
        queryset = queryset.filter(
            Q(voucher_date__range=span) | Q(voucher_date__isnull=True, created_at__date__range=span)
        )
    if user.portal_entries:
        # Only invoices created here have time entries; one EXISTS check per row keeps the list a single query.
        queryset = queryset.annotate(has_entries=Exists(TimeEntry.objects.filter(invoice=OuterRef("pk"))))
    rows = [i async for i in queryset.order_by("-period_end", "-created_at")]
    context = {
        "invoices": rows,
        "status": status,
        "status_filters": [(key, label) for key, (label, _) in INVOICE_STATUS_FILTERS.items()],
        "range": date_range,
        "presets": presets(today),
    }
    return render(request, "portal/invoices.html", context)


def _visible_invoices(user):
    return Invoice.objects.filter(customer_id=user.customer_id).exclude(status__in=HIDDEN_INVOICE_STATUSES)


async def _invoice_by_number(request: HttpRequest, number: str, **extra) -> Invoice:
    """The customer's invoice with this number.

    Invoices are addressed by their number, which Lexware assigns once and never reuses, so it is unique per
    customer in practice. The database does not enforce that, so on a clash the newest invoice wins.
    """
    queryset = _visible_invoices(request.user).exclude(voucher_number="").filter(**extra)
    matches = [i async for i in queryset.filter(voucher_number=number).order_by("-voucher_date", "-pk")[:2]]
    if len(matches) > 1:
        logger.warning("Customer %s has several invoices numbered %s", request.user.customer_id, number)
    if matches:
        return matches[0]
    raise Http404


@require_GET
async def invoice_entries(request: HttpRequest, number: str) -> HttpResponse:
    """The time entries that went into one invoice."""
    user = request.user
    if not (user.portal_invoices and user.portal_entries):
        raise PermissionDenied
    invoice = await _invoice_by_number(request, number)
    rows = [
        e
        async for e in _customer_entries(user)
        .filter(invoice=invoice)
        .select_related("task", "task__project")
        .order_by("started_at")
    ]
    context = {"invoice": invoice, "entries": rows, "total": sum((e.duration for e in rows), timedelta())}
    return render(request, "portal/invoice_entries.html", context)


@require_GET
async def invoice_pdf(request: HttpRequest, number: str) -> HttpResponse:
    """The invoice PDF, fetched from Lexware on each download."""
    user = request.user
    if not user.portal_invoices:
        raise PermissionDenied
    invoice = await _invoice_by_number(request, number, lexware_id__isnull=False)
    try:
        async with client_from_settings() as client:
            pdf = await client.get_invoice_pdf(invoice.lexware_id)
    except LexwareError:
        logger.exception("Invoice PDF %s could not be fetched", invoice.lexware_id)
        messages.error(request, "Die Rechnung kann gerade nicht heruntergeladen werden. Bitte versuche es später.")
        return redirect("portal:invoices")
    response = HttpResponse(pdf, content_type="application/pdf")
    # Numbers are free-form in Lexware and may hold a slash.
    name = re.sub(r"[\\/]", "-", f"Rechnung-{invoice.voucher_number}.pdf")
    # ?inline=1 opens it in the browser instead of downloading it.
    response["Content-Disposition"] = content_disposition_header(request.GET.get("inline") != "1", name)
    return response


def _contact_initial(contact: dict) -> dict:
    current = Contact.model_validate(contact)
    address = billing_address(contact)
    return {
        "name": current.name,
        "email": current.email,
        "phone": current.phone,
        "version": current.version,
        **address,
        "countryCode": address["countryCode"] or "DE",
        **{f"person_{key}": value for key, value in contact_person(contact).items()},
    }


@require_http_methods(["GET", "POST"])
async def contact(request: HttpRequest) -> HttpResponse:
    """The customer changes its own contact in Lexware Office: name, billing address, e-mail and phone.

    The contact is read fresh from Lexware on every visit and before saving. If its version changed
    since the form was loaded, nothing is saved and the customer is asked to check the current data.
    """
    user = request.user
    if not user.portal_contact:
        raise PermissionDenied
    customer = await Customer.objects.aget(pk=user.customer_id)
    if not customer.lexware_id or customer.lexware_deleted:
        return render(request, "portal/contact.html", {"customer": customer, "unavailable": True})

    form, conflict = None, None
    try:
        async with client_from_settings() as client:
            raw = await client.get_contact(customer.lexware_id)
            initial = _contact_initial(raw)
            with_person = raw.get("company") is not None
            form = ContactForm(request.POST or None, initial=initial, with_person=with_person)
            if request.method == "POST" and form.is_valid():
                if form.cleaned_data["version"] != initial["version"]:
                    # Keep what the customer typed, but with the new version, so saving again overwrites.
                    data = request.POST.copy()
                    data["version"] = initial["version"]
                    form = ContactForm(data, initial=initial, with_person=with_person)
                    form.add_error(
                        None,
                        "Deine Kontaktdaten wurden in der Zwischenzeit geändert. "
                        "Bitte prüfe deine Eingaben und speichere erneut.",
                    )
                    conflict = initial
                else:
                    customer.name = form.cleaned_data["name"]
                    customer.email = form.cleaned_data["email"]
                    customer.phone = form.cleaned_data["phone"]
                    apply_to_contact(raw, customer)
                    apply_billing_address(raw, form.address)
                    if with_person:
                        apply_contact_person(raw, form.person)
                    customer.lexware_version = await client.update_contact(customer.lexware_id, raw)
                    customer.lexware_synced_at = timezone.now()
                    await customer.asave(
                        update_fields=["name", "email", "phone", "lexware_version", "lexware_synced_at", "updated_at"]
                    )
                    logger.info("Customer login %s changed the Lexware contact of customer %s", user.pk, customer.pk)
                    messages.success(request, "Deine Kontaktdaten sind gespeichert.")
                    return redirect("portal:contact")
    except LexwareError:
        logger.exception("Lexware contact %s could not be read or saved", customer.lexware_id)
        if form is None:
            return render(request, "portal/contact.html", {"customer": customer, "lexware_error": True})
        form.add_error(None, "Deine Änderung konnte gerade nicht gespeichert werden. Bitte versuche es später.")
    context = {"customer": customer, "form": form, "conflict": conflict, "countries": COUNTRIES}
    return await arender(request, "portal/contact.html", context)
