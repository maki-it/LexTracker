import csv
import io
from urllib.parse import urlencode

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from billing.calculation import to_hours
from customers.models import Customer
from reports.queries import build_report, entries_in
from reports.ranges import presets, selected_range


def _customer_id(request: HttpRequest) -> int | None:
    value = request.GET.get("kunde", "")
    return int(value) if value.isdigit() else None


@require_GET
async def overview(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    rng = selected_range(request.GET, today)
    customer_id = _customer_id(request)
    report = await sync_to_async(build_report)(rng, customer_id, today)
    # The range as query string, for the export and the customer filter.
    range_query = urlencode({"zeitraum": rng.key} if rng.key else {"von": rng.start, "bis": rng.end})
    return render(
        request,
        "reports/overview.html",
        {
            "report": report,
            "presets": presets(today),
            "customers": [c async for c in Customer.objects.filter(is_archived=False).order_by("name")],
            "customer_id": customer_id,
            "range_query": range_query,
            "customer_query": f"&kunde={customer_id}" if customer_id else "",
        },
    )


def _decimal(value) -> str:
    # Spreadsheets with German settings expect a decimal comma.
    return str(value).replace(".", ",")


def _entries_csv(rng, customer_id: int | None) -> str:
    out = io.StringIO()
    out.write("﻿")  # BOM, so Excel reads the file as UTF-8
    writer = csv.writer(out, delimiter=";")
    writer.writerow(
        [
            "Datum",
            "Beginn",
            "Ende",
            "Stunden",
            "Kunde",
            "Kundennummer",
            "Projekt",
            "Aufgabe",
            "Beschreibung",
            "Abrechenbar",
            "Abgerechnet",
            "Rechnungsnummer",
            "Benutzer",
        ]
    )
    for entry in entries_in(rng.start, rng.end, customer_id):
        start, end = timezone.localtime(entry.started_at), timezone.localtime(entry.ended_at)
        customer = entry.task.project.customer
        billable = entry.is_billable and entry.task.is_billable
        writer.writerow(
            [
                f"{start:%d.%m.%Y}",
                f"{start:%H:%M}",
                f"{end:%H:%M}",
                _decimal(to_hours(entry.duration)),
                customer.name,
                customer.customer_number,
                entry.task.project.name,
                entry.task.name,
                entry.description,
                "ja" if billable else "nein",
                "ja" if entry.invoice_id else "nein",
                entry.invoice.voucher_number if entry.invoice else "",
                entry.user.get_username(),
            ]
        )
    return out.getvalue()


@require_GET
async def entries_csv(request: HttpRequest) -> HttpResponse:
    rng = selected_range(request.GET, timezone.localdate())
    content = await sync_to_async(_entries_csv)(rng, _customer_id(request))
    response = HttpResponse(content, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="zeiten-{rng.start}-{rng.end}.csv"'
    return response
