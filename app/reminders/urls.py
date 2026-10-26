from django.urls import path

from reminders import views

app_name = "reminders"

urlpatterns = [
    path("", views.reminder_list, name="list"),
    path("new/", views.reminder_form, name="create"),
    path("<uuid:pk>/edit/", views.reminder_form, name="edit"),
    path("<uuid:pk>/done/", views.reminder_done, name="done"),
    path("<uuid:pk>/reopen/", views.reminder_reopen, name="reopen"),
    path("<uuid:pk>/delete/", views.reminder_delete, name="delete"),
]
