from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from customers.models import Customer
from customers.sync import sync_customers
from lexware.client import LexwareError, client_from_settings


async def _customer_list_context(request: HttpRequest) -> dict:
    show_archived = request.GET.get("archiviert") == "1"
    customers = Customer.objects.all() if show_archived else Customer.objects.filter(is_archived=False)
    return {
        "customers": [c async for c in customers],
        "show_archived": show_archived,
        "lexware_configured": bool(settings.LEXWARE_API_KEY),
    }


@require_GET
async def customer_list(request: HttpRequest) -> HttpResponse:
    return render(request, "customers/list.html", await _customer_list_context(request))


@require_POST
async def import_from_lexware(request: HttpRequest) -> HttpResponse:
    """Run the import and return the refreshed customer table (htmx swaps it in)."""
    result, error = None, None
    try:
        async with client_from_settings() as client:
            result = await sync_customers(client)
    except LexwareError as exc:
        error = str(exc)

    context = await _customer_list_context(request)
    return render(request, "customers/_table.html", {**context, "result": result, "error": error})
