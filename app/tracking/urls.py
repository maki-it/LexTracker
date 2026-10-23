from django.urls import path

from tracking import views

app_name = "tracking"

urlpatterns = [
    path("", views.entry_list, name="list"),
    path("neu/", views.entry_form, name="create"),
    path("<int:pk>/", views.entry_form, name="edit"),
    path("<int:pk>/loeschen/", views.entry_delete, name="delete"),
    path("timer/", views.timer, name="timer"),
    path("timer/start/", views.timer_start, name="timer_start"),
    path("timer/stop/", views.timer_stop, name="timer_stop"),
    path("aufgaben/", views.task_search, name="task_search"),
]
