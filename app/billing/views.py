from datetime import date

from asgiref.sync import sync_to_async
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from billing.calculation import active_agreement, build_draft
from billing.forms import BillingAgreementForm, PeriodForm
from billing.models import BillingAgreement, Invoice
from billing.periods import Period, recent_periods
from billing.services import create_invoice
from core.shortcuts import arender
from customers.models import Customer
from lexware.client import LexwareError, client_from_settings
from tracking.queries import booked_time


async def _get_customer(pk: int) -> Customer:
    try:
        return await Customer.objects.aget(pk=pk)
    except Customer.DoesNotExist as exc:
        raise Http404 from exc


@require_GET
async def overview(request: HttpRequest) -> HttpResponse:
    customers = (
        Customer.objects.filter(is_archived=False)
        .annotate(
            unbilled=booked_time(
                "projects__tasks__time_entries__", invoice__isnull=True, is_billable=True, task__is_billable=True
            )
        )
        .order_by("name")
    )
    invoices = Invoice.objects.select_related("customer")[:20]
    return render(
        request,
        "billing/overview.html",
        {"customers": [c async for c in customers], "invoices": [i async for i in invoices]},
    )


def _period_options(agreement: BillingAgreement | None, today: date):
    period = agreement.period if agreement and agreement.kind == BillingAgreement.Kind.RETAINER else Period.MONTH
    return recent_periods(today, period)


def _selected_period(request: HttpRequest, options) -> tuple[PeriodForm, date | None, date | None]:
    data = request.POST if request.method == "POST" else request.GET
    if "start" not in data:
        # Default: the last completed period.
        default = options[1]
        data = {"start": default.start.isoformat(), "end": default.end.isoformat()}
    form = PeriodForm(data)
    if form.is_valid():
        return form, form.cleaned_data["start"], form.cleaned_data["end"]
    return form, None, None


@require_GET
async def customer_billing(request: HttpRequest, pk: int) -> HttpResponse:
    customer = await _get_customer(pk)
    today = timezone.localdate()
    current = await sync_to_async(active_agreement)(customer, today, today)
    options = _period_options(current, today)
    period_form, start, end = _selected_period(request, options)
    draft = await sync_to_async(build_draft)(customer, start, end) if start else None
    context = {
        "customer": customer,
        "agreements": [a async for a in customer.billing_agreements.all()],
        "period_options": options,
        "period_form": period_form,
        "draft": draft,
        "invoices": [i async for i in customer.invoices.all()[:10]],
    }
    template = "billing/_preview.html" if request.htmx and request.htmx.target == "preview" else "billing/customer.html"
    return render(request, template, context)


@require_POST
async def invoice_create(request: HttpRequest, pk: int) -> HttpResponse:
    customer = await _get_customer(pk)
    period_form = PeriodForm(request.POST)
    if not period_form.is_valid():
        messages.error(request, "Bitte einen gültigen Zeitraum wählen.")
        return redirect("billing:customer", pk=pk)
    start, end = period_form.cleaned_data["start"], period_form.cleaned_data["end"]
    try:
        async with client_from_settings() as client:
            invoice = await create_invoice(client, customer, start, end)
    except LexwareError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Rechnungsentwurf über {invoice.total_net} € netto in Lexware angelegt.")
    return redirect(f"{reverse('billing:customer', args=[pk])}?start={start}&end={end}")


@require_http_methods(["GET", "POST"])
async def agreement_form(request: HttpRequest, pk: int, agreement_pk: int | None = None) -> HttpResponse:
    customer = await _get_customer(pk)
    agreement = None
    if agreement_pk:
        try:
            agreement = await customer.billing_agreements.aget(pk=agreement_pk)
        except BillingAgreement.DoesNotExist as exc:
            raise Http404 from exc
    initial = None if agreement else {"valid_from": timezone.localdate().replace(day=1)}
    form = BillingAgreementForm(request.POST or None, instance=agreement, initial=initial, customer=customer)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        form.instance.customer = customer
        await sync_to_async(form.save)()
        messages.success(request, "Abrechnungsvereinbarung gespeichert.")
        return redirect("billing:customer", pk=pk)
    return await arender(request, "billing/agreement_form.html", {"form": form, "customer": customer})
