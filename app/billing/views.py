from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from billing.calculation import active_agreement, build_draft, unbilled
from billing.forms import BillingAgreementForm, PeriodForm
from billing.models import BillingAgreement, Invoice
from billing.periods import Period, period_containing, recent_periods
from billing.services import create_invoice
from billing.sync import sync_and_record
from core.models import AppSettings
from core.shortcuts import arender
from customers.models import Customer
from lexware.client import LexwareError, client_from_settings
from tracking.models import TimeEntry
from tracking.queries import booked_time


async def _get_customer(pk: int) -> Customer:
    try:
        return await Customer.objects.aget(pk=pk)
    except Customer.DoesNotExist as exc:
        raise Http404 from exc


INVOICES_PER_PAGE = 50

# The status filters on the invoice list. "Offen" includes payments that are on their way.
STATUS_FILTERS = {
    "entwurf": ("Entwürfe", [Invoice.Status.DRAFT]),
    "offen": ("Offen", [Invoice.Status.OPEN, Invoice.Status.TRANSFERRED, Invoice.Status.SEPADEBIT]),
    "ueberfaellig": ("Überfällig", [Invoice.Status.OVERDUE]),
    "bezahlt": ("Bezahlt", [Invoice.Status.PAID]),
    "storniert": ("Storniert", [Invoice.Status.VOIDED]),
    "geloescht": ("In Lexware gelöscht", [Invoice.Status.DELETED]),
}


async def _invoice_counts() -> dict[str, int]:
    by_status = {
        row["status"]: row["n"] async for row in Invoice.objects.values("status").annotate(n=Count("pk")).order_by()
    }
    return {key: sum(by_status.get(s, 0) for s in statuses) for key, (_, statuses) in STATUS_FILTERS.items()}


@require_GET
async def overview(request: HttpRequest) -> HttpResponse:
    """Customers with time that has not been billed yet."""
    query = request.GET.get("q", "").strip()
    show_all = request.GET.get("alle") == "1"
    customers = (
        Customer.objects.filter(is_archived=False)
        .annotate(
            unbilled=booked_time(
                "projects__tasks__time_entries__", invoice__isnull=True, is_billable=True, task__is_billable=True
            )
        )
        .order_by("name")
    )
    if query:
        customers = customers.filter(Q(name__icontains=query) | Q(customer_number__icontains=query))
    if not show_all:
        customers = customers.filter(unbilled__gt=timedelta(0))
    customers = [c async for c in customers]
    context = {
        "customers": customers,
        "query": query,
        "show_all": show_all,
        "unbilled_total": sum((c.unbilled or timedelta(0) for c in customers), timedelta(0)),
        "counts": await _invoice_counts(),
    }
    return render(request, "billing/overview.html", context)


@require_GET
async def invoice_list(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status not in STATUS_FILTERS:
        status = ""
    try:
        page = max(1, int(request.GET.get("seite", 1)))
    except ValueError:
        page = 1
    invoices = Invoice.objects.select_related("customer").annotate(entry_count=Count("time_entries"))
    if status:
        invoices = invoices.filter(status__in=STATUS_FILTERS[status][1])
    if query:
        invoices = invoices.filter(Q(customer__name__icontains=query) | Q(voucher_number__icontains=query))
    offset = (page - 1) * INVOICES_PER_PAGE
    # One more than fits on the page tells whether there is a next page.
    rows = [i async for i in invoices[offset : offset + INVOICES_PER_PAGE + 1]]
    app_settings = await AppSettings.aload()
    counts = await _invoice_counts()
    context = {
        "invoices": rows[:INVOICES_PER_PAGE],
        "has_next": len(rows) > INVOICES_PER_PAGE,
        "page": page,
        "query": query,
        "status": status,
        # Only filters that would show something, plus the one in use.
        "filters": [
            (key, label, counts[key]) for key, (label, _) in STATUS_FILTERS.items() if counts[key] or key == status
        ],
        "app_settings": app_settings,
        "lexware_configured": bool(settings.LEXWARE_API_KEY),
    }
    return render(request, "billing/invoices.html", context)


@require_POST
async def invoice_sync(request: HttpRequest) -> HttpResponse:
    try:
        result = await sync_and_record()
    except LexwareError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, f"Rechnungsstatus abgeglichen: {result.summary}")
    return redirect(_invoice_list_url(request))


@require_POST
async def invoice_release(request: HttpRequest, invoice_pk: int) -> HttpResponse:
    """Let the time of a voided invoice be billed again."""
    try:
        invoice = await Invoice.objects.aget(pk=invoice_pk, status=Invoice.Status.VOIDED)
    except Invoice.DoesNotExist as exc:
        raise Http404 from exc
    released = await TimeEntry.objects.filter(invoice=invoice).aupdate(invoice=None)
    messages.success(request, f"{released} Zeiteinträge wieder zur Abrechnung freigegeben.")
    return redirect(_invoice_list_url(request))


def _invoice_list_url(request: HttpRequest) -> str:
    # Back to the list with the filter the form was sent from.
    query = request.POST.get("return_query", "")
    url = reverse("billing:invoices")
    return f"{url}?{query}" if query and "//" not in query else url


MAX_PERIOD_OPTIONS = 8


@dataclass(frozen=True)
class PeriodOption:
    start: date
    end: date
    label: str
    open_time: timedelta

    @property
    def key(self) -> str:
        return f"{self.start}/{self.end}"


def _period_options(customer: Customer, agreement: BillingAgreement | None, today: date) -> list[PeriodOption]:
    """Recent periods plus older ones with open time, newest first, each with its open time.

    Without a retainer, "Alle offenen" comes first: the range from the first to the last open entry.
    """
    is_retainer = agreement is not None and agreement.kind == BillingAgreement.Kind.RETAINER
    period = agreement.period if is_retainer else Period.MONTH
    open_by_day: dict[date, timedelta] = defaultdict(timedelta)
    for started_at, ended_at in unbilled(customer).values_list("started_at", "ended_at"):
        open_by_day[timezone.localtime(started_at).date()] += ended_at - started_at

    periods = recent_periods(today, period)
    older = sorted({period_containing(day, period) for day in open_by_day} - set(periods), reverse=True)
    periods = (periods + older)[:MAX_PERIOD_OPTIONS]

    def option(start: date, end: date, label: str) -> PeriodOption:
        open_time = sum((t for day, t in open_by_day.items() if start <= day <= end), timedelta())
        return PeriodOption(start, end, label, open_time)

    options = [option(p.start, p.end, p.label) for p in periods]
    if open_by_day and not is_retainer:
        options.insert(0, option(min(open_by_day), max(open_by_day), "Alle offenen"))
    return options


def _default_period(options: list[PeriodOption]) -> PeriodOption:
    """The last completed period if it has open time, otherwise all open time, otherwise that period."""
    periods = [o for o in options if o.label != "Alle offenen"]
    last_completed = periods[1]
    if last_completed.open_time:
        return last_completed
    return next((o for o in options if o.open_time), last_completed)


def _selected_period(request: HttpRequest, options) -> tuple[PeriodForm, date | None, date | None]:
    data = request.POST if request.method == "POST" else request.GET
    if "start" not in data:
        default = _default_period(options)
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
    options = await sync_to_async(_period_options)(customer, current, today)
    period_form, start, end = _selected_period(request, options)
    draft = await sync_to_async(build_draft)(customer, start, end) if start else None
    context = {
        "customer": customer,
        "agreements": [a async for a in customer.billing_agreements.all()],
        "period_options": options,
        "period_form": period_form,
        "selected_period": f"{start}/{end}",
        "draft": draft,
        "invoices": [i async for i in customer.invoices.annotate(entry_count=Count("time_entries"))[:10]],
    }
    if request.htmx and request.htmx.target == "preview":
        # The pills are swapped too, so the one matching the chosen dates is marked.
        return render(request, "billing/_preview.html", {**context, "oob": True})
    template = "billing/customer.html"
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
