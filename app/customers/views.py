from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.db.models import Count, Q
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import AppSettings
from core.shortcuts import arender
from customers.forms import CustomerForm
from customers.lexware import LEXWARE_FIELDS, push_to_lexware
from customers.models import Category, Customer
from customers.sync import sync_and_record
from lexware.client import LexwareError, client_from_settings

# The archive filter on the customer list: key in the URL, label.
VIEWS = {"aktiv": "Aktiv", "archiviert": "Archiviert", "alle": "Alle"}


def _query_string(**params) -> str:
    return urlencode({k: v for k, v in params.items() if v})


async def _customer_list_context(request: HttpRequest) -> dict:
    view = request.GET.get("ansicht", "aktiv")
    if view not in VIEWS:
        view = "aktiv"
    query = request.GET.get("q", "").strip()
    category = request.GET.get("kategorie", "")
    category = int(category) if category.isdigit() else None

    customers = Customer.objects.prefetch_related("categories")
    if query:
        customers = customers.filter(
            Q(name__icontains=query)
            | Q(customer_number__icontains=query)
            | Q(email__icontains=query)
            | Q(notes__icontains=query)
        )
    if category:
        customers = customers.filter(categories=category)
    counts = await customers.aaggregate(
        aktiv=Count("pk", filter=Q(is_archived=False), distinct=True),
        archiviert=Count("pk", filter=Q(is_archived=True), distinct=True),
        alle=Count("pk", distinct=True),
    )
    if view == "aktiv":
        customers = customers.filter(is_archived=False)
    elif view == "archiviert":
        customers = customers.filter(is_archived=True)

    ansicht = "" if view == "aktiv" else view
    return {
        "customers": [c async for c in customers.order_by("is_archived", "name")],
        "query": query,
        "category": category,
        "view": view,
        # Links keep the other filters.
        "view_links": [
            (key, label, counts[key], _query_string(ansicht="" if key == "aktiv" else key, q=query, kategorie=category))
            for key, label in VIEWS.items()
        ],
        "category_links": [
            (c, _query_string(ansicht=ansicht, q=query, kategorie=c.pk)) async for c in Category.objects.all()
        ],
        "all_categories_link": _query_string(ansicht=ansicht, q=query),
        "list_query": _query_string(ansicht=ansicht, q=query, kategorie=category),
        "ansicht": ansicht,
        "lexware_configured": bool(settings.LEXWARE_API_KEY),
        "app_settings": await AppSettings.aload(),
    }


@require_GET
async def customer_list(request: HttpRequest) -> HttpResponse:
    return render(request, "customers/list.html", await _customer_list_context(request))


@require_POST
async def import_from_lexware(request: HttpRequest) -> HttpResponse:
    """Run the import and return the refreshed customer table (htmx swaps it in)."""
    result, error = None, None
    try:
        result = await sync_and_record()
    except LexwareError as exc:
        error = str(exc)

    context = await _customer_list_context(request)
    return render(request, "customers/_table.html", {**context, "result": result, "error": error})


@require_http_methods(["GET", "POST"])
async def customer_edit(request: HttpRequest, pk: int) -> HttpResponse:
    try:
        customer = await Customer.objects.aget(pk=pk)
    except Customer.DoesNotExist as exc:
        raise Http404 from exc

    form = await sync_to_async(CustomerForm)(request.POST or None, instance=customer)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        try:
            if customer.lexware_id and any(f in LEXWARE_FIELDS for f in form.changed_data):
                async with client_from_settings() as client:
                    await push_to_lexware(client, customer)
        except LexwareError as exc:
            form.add_error(None, f"Die Änderung konnte nicht in Lexware gespeichert werden: {exc}")
        else:
            await customer.asave()
            await sync_to_async(form.save_categories)()
            messages.success(request, f"{customer.name} gespeichert.")
            return redirect("customers:list")
    return await arender(
        request,
        "customers/edit.html",
        {"form": form, "customer": customer, "lexware_fields": LEXWARE_FIELDS},
    )
