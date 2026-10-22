from django.urls import path

from projects import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("neu/", views.project_form, name="create"),
    path("<int:pk>/", views.project_detail, name="detail"),
    path("<int:pk>/bearbeiten/", views.project_form, name="edit"),
    path("<int:pk>/aufgaben/", views.task_create, name="task_create"),
    path("<int:pk>/aufgaben/<int:task_pk>/status/", views.task_set_status, name="task_status"),
]
