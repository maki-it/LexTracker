from django.urls import path

from projects import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("neu/", views.project_form, name="create"),
    path("vorlagen/", views.template_list, name="templates"),
    path("vorlagen/neu/", views.template_form, name="template_create"),
    path("vorlagen/<uuid:pk>/bearbeiten/", views.template_form, name="template_edit"),
    path("vorlagen/<uuid:pk>/loeschen/", views.template_delete, name="template_delete"),
    path("<uuid:pk>/", views.project_detail, name="detail"),
    path("<uuid:pk>/bearbeiten/", views.project_form, name="edit"),
    path("<uuid:pk>/loeschen/", views.project_delete, name="delete"),
    path("<uuid:pk>/aufgaben/", views.task_create, name="task_create"),
    path("<uuid:pk>/aufgaben/vorlagen/", views.task_from_templates, name="task_from_templates"),
    path("<uuid:pk>/aufgaben/<uuid:task_pk>/als-vorlage/", views.task_save_as_template, name="task_save_as_template"),
    path("<uuid:pk>/aufgaben/<uuid:task_pk>/status/", views.task_set_status, name="task_status"),
    path("<uuid:pk>/aufgaben/<uuid:task_pk>/bearbeiten/", views.task_edit, name="task_edit"),
    path("<uuid:pk>/aufgaben/<uuid:task_pk>/loeschen/", views.task_delete, name="task_delete"),
]
