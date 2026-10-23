from django.urls import path

from portal import views

app_name = "portal"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("zeiten/", views.entries, name="entries"),
    path("rechnungen/", views.invoices, name="invoices"),
    path("rechnungen/<int:invoice_pk>/zeiten/", views.invoice_entries, name="invoice_entries"),
    path("rechnungen/<int:invoice_pk>/pdf/", views.invoice_pdf, name="invoice_pdf"),
    path("kontakt/", views.contact, name="contact"),
]
