from django.urls import path

from tracking import views

app_name = "tracking"

urlpatterns = [
    path("", views.entry_list, name="list"),
    path("new/", views.entry_form, name="create"),
    path("<uuid:pk>/", views.entry_form, name="edit"),
    path("<uuid:pk>/delete/", views.entry_delete, name="delete"),
    path("timer/", views.timer, name="timer"),
    path("timer/start/", views.timer_start, name="timer_start"),
    path("timer/stop/", views.timer_stop, name="timer_stop"),
    path("picker/", views.week_picker, name="week_picker"),
    path("search/", views.task_search, name="task_search"),
]
