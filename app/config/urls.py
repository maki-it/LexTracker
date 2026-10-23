from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from core.views import FaviconView

urlpatterns = [
    # The admin has its own login without the second factor, so send it to ours.
    path("admin/login/", RedirectView.as_view(pattern_name="accounts:login", query_string=True)),
    path("admin/", admin.site.urls),
    # Browsers ask for /favicon.ico on their own, e.g. for the admin or a JSON response.
    path("favicon.ico", FaviconView.as_view()),
    path("accounts/", include("accounts.urls")),
    path("konto/", include("accounts.account_urls")),
    path("benutzer/", include("accounts.user_urls")),
    path("kunden/", include("customers.urls")),
    path("projekte/", include("projects.urls")),
    path("zeiten/", include("tracking.urls")),
    path("abrechnung/", include("billing.urls")),
    path("auswertungen/", include("reports.urls")),
    path("einstellungen/lexware/", include("lexware.urls")),
    path("einrichtung/", include("setup.urls")),
    path("mcp/", include("mcpserver.urls")),
    path("portal/", include("portal.urls")),
    path("", include("core.urls")),
]
