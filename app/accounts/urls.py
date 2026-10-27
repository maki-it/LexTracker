from django.urls import path

from accounts import passkey_views, views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/code/", views.login_code, name="login_code"),
    path("login/link/", views.login_link_request, name="login_link_request"),
    path("login/link/<str:key>/", views.login_link, name="login_link"),
    path("login/passkey/options/", passkey_views.passkey_options, name="passkey_options"),
    path("login/passkey/", passkey_views.passkey_login, name="passkey_login"),
    path("password/forgot/", views.password_forgot, name="password_forgot"),
    path("password/reset/<uidb64>/<token>/", views.password_reset, name="password_reset"),
    path("sso/", views.sso_start, name="sso_start"),
    path("sso/callback/", views.sso_callback, name="sso_callback"),
    path("language/", views.set_language, name="set_language"),
    path("logout/", views.logout_view, name="logout"),
    path("invite/<uidb64>/<token>/", views.invite, name="invite"),
]
