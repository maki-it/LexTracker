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
    path("account/", include("accounts.account_urls")),
    path("users/", include("accounts.user_urls")),
    path("customers/", include("customers.urls")),
    path("projects/", include("projects.urls")),
    path("tasks/", include("tracking.urls")),
    path("billing/", include("billing.urls")),
    path("reports/", include("reports.urls")),
    path("messages/", include("inbox.urls")),
    path("reminders/", include("reminders.urls")),
    path("settings/lexware/", include("lexware.urls")),
    path("settings/email/", include("mailer.urls")),
    path("setup/", include("setup.urls")),
    path("mcp/", include("mcpserver.urls")),
    path("portal/", include("portal.urls")),
    path("", include("core.urls")),
]
