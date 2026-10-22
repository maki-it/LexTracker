from django.urls import path

from billing import views

app_name = "billing"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("kunde/<int:pk>/", views.customer_billing, name="customer"),
    path("kunde/<int:pk>/rechnung/", views.invoice_create, name="invoice_create"),
    path("kunde/<int:pk>/vereinbarung/", views.agreement_form, name="agreement_create"),
    path("kunde/<int:pk>/vereinbarung/<int:agreement_pk>/", views.agreement_form, name="agreement_edit"),
]
