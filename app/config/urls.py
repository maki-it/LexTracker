from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # The admin has its own login without the second factor, so send it to ours.
    path("admin/login/", RedirectView.as_view(pattern_name="accounts:login", query_string=True)),
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("konto/", include("accounts.account_urls")),
    path("kunden/", include("customers.urls")),
    path("projekte/", include("projects.urls")),
    path("zeiten/", include("tracking.urls")),
    path("abrechnung/", include("billing.urls")),
    path("auswertungen/", include("reports.urls")),
    path("", include("core.urls")),
]
