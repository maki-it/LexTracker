import csv
import io
from urllib.parse import urlencode
from uuid import UUID

from asgiref.sync import sync_to_async
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.formats import get_format
from django.utils.translation import gettext as _
from django.utils.translation import pgettext
from django.views.decorators.http import require_GET

from billing.calculation import to_hours
from core.i18n import full_date
from core.ids import parse_uuid
from customers.models import Customer
from reports.queries import build_report, entries_in
from reports.ranges import presets, selected_range


def _customer_id(request: HttpRequest) -> UUID | None:
    return parse_uuid(request.GET.get("customer", ""))


@require_GET
async def overview(request: HttpRequest) -> HttpResponse:
    today = timezone.localdate()
    rng = selected_range(request.GET, today)
    customer_id = _customer_id(request)
    report = await sync_to_async(build_report)(rng, customer_id, today)
    # The range as query string, for the export and the customer filter.
    range_query = urlencode({"range": rng.key} if rng.key else {"from": rng.start, "to": rng.end})
    return render(
        request,
        "reports/overview.html",
        {
            "report": report,
            "presets": presets(today),
            "customers": [c async for c in Customer.objects.filter(is_archived=False).order_by("name")],
            "customer_id": customer_id,
            "range_query": range_query,
            "customer_query": f"&customer={customer_id}" if customer_id else "",
        },
    )


def _decimal(value) -> str:
    # Spreadsheets expect the decimal separator of their settings: a comma in German, a point in English.
    return str(value).replace(".", get_format("DECIMAL_SEPARATOR"))


def _entries_csv(rng, customer_id: UUID | None) -> str:
    out = io.StringIO()
    out.write("﻿")  # BOM, so Excel reads the file as UTF-8
    # Translators: the field separator of the CSV export. Spreadsheets with German settings expect ";".
    writer = csv.writer(out, delimiter=pgettext("csv delimiter", ";"))
    writer.writerow(
        [
            _("Datum"),
            _("Beginn"),
            _("Ende"),
            _("Stunden"),
            _("Kunde"),
            _("Kundennummer"),
            _("Projekt"),
            _("Aufgabe"),
            _("Beschreibung"),
            _("Abrechenbar"),
            _("Abgerechnet"),
            _("Rechnungsnummer"),
            _("Benutzer"),
        ]
    )
    for entry in entries_in(rng.start, rng.end, customer_id):
        start, end = timezone.localtime(entry.started_at), timezone.localtime(entry.ended_at)
        customer = entry.task.project.customer
        billable = entry.is_billable and entry.task.is_billable
        writer.writerow(
            [
                full_date(start),
                f"{start:%H:%M}",
                f"{end:%H:%M}",
                _decimal(to_hours(entry.duration)),
                customer.name,
                customer.customer_number,
                entry.task.project.name,
                entry.task.name,
                entry.description,
                _("ja") if billable else _("nein"),
                _("ja") if entry.invoice_id else _("nein"),
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
