"""The portal for customer logins. Everything is limited to the user's customer.

It is read-only, except that a login may be allowed to change the customer's own contact in Lexware.
"""

import logging
from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_http_methods

from billing.models import Invoice
from billing.periods import Period, period_containing
from billing.views import STATUS_FILTERS
from core.shortcuts import arender
from customers.lexware import apply_billing_address, apply_to_contact, billing_address
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


# The status filters the customer can pick. Drafts and deleted invoices never show up here.
INVOICE_STATUS_FILTERS = {key: STATUS_FILTERS[key] for key in ("offen", "ueberfaellig", "bezahlt", "storniert")}


@require_GET
async def invoices(request: HttpRequest) -> HttpResponse:
    user = request.user
    if not user.portal_invoices:
        raise PermissionDenied
    queryset = Invoice.objects.filter(customer_id=user.customer_id).exclude(status__in=HIDDEN_INVOICE_STATUSES)
    status = request.GET.get("status", "")
    if status in INVOICE_STATUS_FILTERS:
        queryset = queryset.filter(status__in=INVOICE_STATUS_FILTERS[status][1])
    else:
        status = ""
    today = timezone.localdate()
    # All invoices unless a range is picked, by invoice date (the creation day for invoices without one).
    date_range = selected_range(request.GET, today) if {"zeitraum", "von", "bis"} & set(request.GET) else None
    if date_range:
        span = (date_range.start, date_range.end)
        queryset = queryset.filter(
            Q(voucher_date__range=span) | Q(voucher_date__isnull=True, created_at__date__range=span)
        )
    rows = [i async for i in queryset.order_by("-period_end", "-created_at")]
    context = {
        "invoices": rows,
        "status": status,
        "status_filters": [(key, label) for key, (label, _) in INVOICE_STATUS_FILTERS.items()],
        "range": date_range,
        "presets": presets(today),
    }
    return render(request, "portal/invoices.html", context)


@require_GET
async def invoice_pdf(request: HttpRequest, invoice_pk: int) -> HttpResponse:
    """The invoice PDF, fetched from Lexware on each download."""
    user = request.user
    if not user.portal_invoices:
        raise PermissionDenied
    invoice = await (
        Invoice.objects.filter(customer_id=user.customer_id, pk=invoice_pk, lexware_id__isnull=False)
        .exclude(status__in=HIDDEN_INVOICE_STATUSES)
        .afirst()
    )
    if invoice is None:
        raise Http404
    try:
        async with client_from_settings() as client:
            pdf = await client.get_invoice_pdf(invoice.lexware_id)
    except LexwareError:
        logger.exception("Invoice PDF %s could not be fetched", invoice.lexware_id)
        messages.error(request, "Die Rechnung kann gerade nicht heruntergeladen werden. Bitte versuche es später.")
        return redirect("portal:invoices")
    response = HttpResponse(pdf, content_type="application/pdf")
    name = f"Rechnung-{invoice.voucher_number or invoice.pk}.pdf"
    # ?ansehen=1 opens it in the browser instead of downloading it.
    response["Content-Disposition"] = content_disposition_header(request.GET.get("ansehen") != "1", name)
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
            form = ContactForm(request.POST or None, initial=initial)
            if request.method == "POST" and form.is_valid():
                if form.cleaned_data["version"] != initial["version"]:
                    # Keep what the customer typed, but with the new version, so saving again overwrites.
                    data = request.POST.copy()
                    data["version"] = initial["version"]
                    form = ContactForm(data, initial=initial)
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
