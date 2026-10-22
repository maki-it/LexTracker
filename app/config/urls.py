from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("kunden/", include("customers.urls")),
    path("projekte/", include("projects.urls")),
    path("zeiten/", include("tracking.urls")),
    path("abrechnung/", include("billing.urls")),
    path("", include("core.urls")),
]
