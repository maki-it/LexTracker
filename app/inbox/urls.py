from django.urls import path

from inbox import views

app_name = "inbox"

urlpatterns = [
    path("", views.panel, name="panel"),
    path("all/", views.all_messages, name="all"),
    path("bell/", views.bell, name="bell"),
    path("read/", views.read_all, name="read_all"),
    path("<uuid:pk>/open/", views.open_message, name="open"),
    path("<uuid:pk>/read/", views.read, name="read"),
    path("<uuid:pk>/delete/", views.delete, name="delete"),
]
