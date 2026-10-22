from django.urls import path

from reports import views

app_name = "reports"

urlpatterns = [
    path("", views.overview, name="overview"),
    path("zeiten.csv", views.entries_csv, name="entries_csv"),
]
