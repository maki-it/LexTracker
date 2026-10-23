from django.urls import path

from setup import views

app_name = "setup"

urlpatterns = [
    path("", views.account, name="account"),
    path("lexware/", views.lexware, name="lexware"),
    path("fertig/", views.done, name="done"),
]
