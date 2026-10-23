from django.urls import path

from billing import views

app_name = "billing"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("rechnungen/", views.invoice_list, name="invoices"),
    path("rechnungen/abgleichen/", views.invoice_sync, name="invoice_sync"),
    path("rechnungen/<int:invoice_pk>/freigeben/", views.invoice_release, name="invoice_release"),
    path("kunde/<int:pk>/", views.customer_billing, name="customer"),
    path("kunde/<int:pk>/zeiten/", views.customer_entries, name="customer_entries"),
    path("kunde/<int:pk>/rechnung/", views.invoice_create, name="invoice_create"),
    path("kunde/<int:pk>/vereinbarung/", views.agreement_form, name="agreement_create"),
    path("kunde/<int:pk>/vereinbarung/<int:agreement_pk>/", views.agreement_form, name="agreement_edit"),
]
