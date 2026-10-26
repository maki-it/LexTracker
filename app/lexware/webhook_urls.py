from django.urls import path

from lexware import views

app_name = "webhooks"

urlpatterns = [
    path("lexware/<str:token>/", views.webhook, name="lexware"),
]
