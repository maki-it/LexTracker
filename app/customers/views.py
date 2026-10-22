from asgiref.sync import sync_to_async
from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from core.models import AppSettings
from customers.forms import CustomerForm
from customers.lexware import LEXWARE_FIELDS, push_to_lexware
from customers.models import Customer
from customers.sync import sync_and_record
from lexware.client import LexwareError, client_from_settings


async def _customer_list_context(request: HttpRequest) -> dict:
    show_archived = request.GET.get("archiviert") == "1"
    customers = Customer.objects.all() if show_archived else Customer.objects.filter(is_archived=False)
    return {
        "customers": [c async for c in customers],
        "show_archived": show_archived,
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

    form = CustomerForm(request.POST or None, instance=customer)
    if request.method == "POST" and await sync_to_async(form.is_valid)():
        try:
            if customer.lexware_id and any(f in LEXWARE_FIELDS for f in form.changed_data):
                async with client_from_settings() as client:
                    await push_to_lexware(client, customer)
        except LexwareError as exc:
            form.add_error(None, f"Die Änderung konnte nicht in Lexware gespeichert werden: {exc}")
        else:
            await customer.asave()
            messages.success(request, f"{customer.name} gespeichert.")
            return redirect("customers:list")
    return render(
        request,
        "customers/edit.html",
        {"form": form, "customer": customer, "lexware_fields": LEXWARE_FIELDS},
    )
