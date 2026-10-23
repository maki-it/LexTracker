from django.urls import path

from inbox import views

app_name = "inbox"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("alle/", views.all_messages, name="all"),
    path("glocke/", views.bell, name="bell"),
    path("gelesen/", views.read_all, name="read_all"),
    path("<uuid:pk>/oeffnen/", views.open_message, name="open"),
    path("<uuid:pk>/gelesen/", views.read, name="read"),
    path("<uuid:pk>/loeschen/", views.delete, name="delete"),
]
