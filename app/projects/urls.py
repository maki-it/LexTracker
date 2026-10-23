from django.urls import path

from projects import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("neu/", views.project_form, name="create"),
    path("vorlagen/", views.template_list, name="templates"),
    path("vorlagen/neu/", views.template_form, name="template_create"),
    path("vorlagen/<int:pk>/bearbeiten/", views.template_form, name="template_edit"),
    path("vorlagen/<int:pk>/loeschen/", views.template_delete, name="template_delete"),
    path("<int:pk>/", views.project_detail, name="detail"),
    path("<int:pk>/bearbeiten/", views.project_form, name="edit"),
    path("<int:pk>/loeschen/", views.project_delete, name="delete"),
    path("<int:pk>/aufgaben/", views.task_create, name="task_create"),
    path("<int:pk>/aufgaben/vorlagen/", views.task_from_templates, name="task_from_templates"),
    path("<int:pk>/aufgaben/<int:task_pk>/als-vorlage/", views.task_save_as_template, name="task_save_as_template"),
    path("<int:pk>/aufgaben/<int:task_pk>/status/", views.task_set_status, name="task_status"),
    path("<int:pk>/aufgaben/<int:task_pk>/bearbeiten/", views.task_edit, name="task_edit"),
    path("<int:pk>/aufgaben/<int:task_pk>/loeschen/", views.task_delete, name="task_delete"),
]
