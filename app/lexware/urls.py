from django.urls import path

from lexware import views

app_name = "lexware"

urlpatterns = [
    path("schluessel/", views.save_key, name="save_key"),
    path("pruefen/", views.test_key, name="test_key"),
    path("entfernen/", views.remove_key, name="remove_key"),
]
