from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("time/", views.entries, name="entries"),
    path("invoices/", views.invoices, name="invoices"),
    # The invoice number may hold a slash, so it is a path; the action after it is matched from the end.
    path("invoices/<path:number>/time/", views.invoice_entries, name="invoice_entries"),
    path("invoices/<path:number>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("contact/", views.contact, name="contact"),
]
