from django.urls import path

from billing import views

app_name = "billing"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("rechnungen/", views.invoice_list, name="invoices"),
    path("rechnungen/abgleichen/", views.invoice_sync, name="invoice_sync"),
    path("rechnungen/<uuid:invoice_pk>/freigeben/", views.invoice_release, name="invoice_release"),
    path("kunde/<uuid:pk>/", views.customer_billing, name="customer"),
    path("kunde/<uuid:pk>/rechnung/", views.invoice_create, name="invoice_create"),
    path("kunde/<uuid:pk>/vereinbarung/", views.agreement_form, name="agreement_create"),
    path("kunde/<uuid:pk>/vereinbarung/<uuid:agreement_pk>/", views.agreement_form, name="agreement_edit"),
]
