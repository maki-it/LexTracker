from django.urls import path

from lexware import views

app_name = "lexware"

urlpatterns = [
    path("key/", views.save_key, name="save_key"),
    path("check/", views.test_key, name="test_key"),
    path("remove/", views.remove_key, name="remove_key"),
    path("webhooks/enable/", views.enable_webhooks, name="enable_webhooks"),
    path("webhooks/disable/", views.disable_webhooks, name="disable_webhooks"),
    path("webhooks/key/", views.save_webhook_key, name="save_webhook_key"),
    path("webhooks/key/remove/", views.remove_webhook_key, name="remove_webhook_key"),
]
