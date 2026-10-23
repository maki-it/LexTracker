from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("zeiten/", views.entries, name="entries"),
    path("rechnungen/", views.invoices, name="invoices"),
    # The invoice number may hold a slash, so it is a path; the action after it is matched from the end.
    path("rechnungen/<path:number>/zeiten/", views.invoice_entries, name="invoice_entries"),
    path("rechnungen/<path:number>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("kontakt/", views.contact, name="contact"),
]
