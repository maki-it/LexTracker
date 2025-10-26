from django.urls import path

from .views import sync_customers, sync_customer

app_name = 'lexoffice'

urlpatterns = [
  path('sync', sync_customers, name='sync_customers'),
  path('sync/<uuid:customer_id>', sync_customer, name='sync_customer'),
]
