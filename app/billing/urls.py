from django.urls import path

from billing import views

app_name = "billing"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("invoices/", views.invoice_list, name="invoices"),
    path("invoices/sync/", views.invoice_sync, name="invoice_sync"),
    path("invoices/<uuid:invoice_pk>/release/", views.invoice_release, name="invoice_release"),
    path("customer/<uuid:pk>/", views.customer_billing, name="customer"),
    path("customer/<uuid:pk>/time/", views.customer_entries, name="customer_entries"),
    path("customer/<uuid:pk>/invoice/", views.invoice_create, name="invoice_create"),
    path("customer/<uuid:pk>/agreement/", views.agreement_form, name="agreement_create"),
    path("customer/<uuid:pk>/agreement/<uuid:agreement_pk>/", views.agreement_form, name="agreement_edit"),
]
