from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("robots.txt", views.robots, name="robots"),
    path("manifest.webmanifest", views.manifest, name="manifest"),
    path("branding/logo/", views.logo, name="logo"),
    path("markdown/preview/", views.markdown_preview, name="markdown_preview"),
    path("markdown/<str:target>/<uuid:pk>/toggle/", views.markdown_toggle, name="markdown_toggle"),
    path("settings/", views.app_settings, name="settings"),
    path("settings/jobs/", views.job_list, name="jobs"),
    path("settings/backups/", views.backup_list, name="backups"),
    path("settings/backups/new/", views.backup_create, name="backup_create"),
    path("settings/backups/upload/", views.backup_upload, name="backup_upload"),
    path("settings/backups/<str:name>/", views.backup_download, name="backup_download"),
    path("settings/backups/<str:name>/delete/", views.backup_delete, name="backup_delete"),
    path("settings/backups/<str:name>/restore/", views.backup_restore, name="backup_restore"),
]
