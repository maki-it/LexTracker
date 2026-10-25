from django.urls import path

from lexware import views

app_name = "lexware"

urlpatterns = [
    path("key/", views.save_key, name="save_key"),
    path("check/", views.test_key, name="test_key"),
    path("remove/", views.remove_key, name="remove_key"),
]
