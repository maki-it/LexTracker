from django.urls import path

from projects import views

app_name = "projects"

urlpatterns = [
    path("", views.project_list, name="list"),
    path("new/", views.project_form, name="create"),
    path("templates/", views.template_list, name="templates"),
    path("templates/new/", views.template_form, name="template_create"),
    path("templates/<uuid:pk>/edit/", views.template_form, name="template_edit"),
    path("templates/<uuid:pk>/delete/", views.template_delete, name="template_delete"),
    path("<uuid:pk>/", views.project_detail, name="detail"),
    path("<uuid:pk>/edit/", views.project_form, name="edit"),
    path("<uuid:pk>/delete/", views.project_delete, name="delete"),
    path("<uuid:pk>/tasks/", views.task_create, name="task_create"),
    path("<uuid:pk>/tasks/templates/", views.task_from_templates, name="task_from_templates"),
    path("<uuid:pk>/tasks/<uuid:task_pk>/as-template/", views.task_save_as_template, name="task_save_as_template"),
    path("<uuid:pk>/tasks/<uuid:task_pk>/status/", views.task_set_status, name="task_status"),
    path("<uuid:pk>/tasks/<uuid:task_pk>/edit/", views.task_edit, name="task_edit"),
    path("<uuid:pk>/tasks/<uuid:task_pk>/delete/", views.task_delete, name="task_delete"),
]
