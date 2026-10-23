from django.urls import path

from core import views

app_name = "core"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("health/", views.health, name="health"),
    path("einstellungen/", views.app_settings, name="settings"),
    path("einstellungen/sicherungen/", views.backup_list, name="backups"),
    path("einstellungen/sicherungen/neu/", views.backup_create, name="backup_create"),
    path("einstellungen/sicherungen/hochladen/", views.backup_upload, name="backup_upload"),
    path("einstellungen/sicherungen/<str:name>/", views.backup_download, name="backup_download"),
    path("einstellungen/sicherungen/<str:name>/loeschen/", views.backup_delete, name="backup_delete"),
    path("einstellungen/sicherungen/<str:name>/wiederherstellen/", views.backup_restore, name="backup_restore"),
]
