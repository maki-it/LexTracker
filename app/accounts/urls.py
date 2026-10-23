from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/code/", views.login_code, name="login_code"),
    path("login/link/", views.login_link_request, name="login_link_request"),
    path("login/link/<str:key>/", views.login_link, name="login_link"),
    path("passwort/vergessen/", views.password_forgot, name="password_forgot"),
    path("passwort/neu/<uidb64>/<token>/", views.password_reset, name="password_reset"),
    path("logout/", views.logout_view, name="logout"),
    path("einladung/<uidb64>/<token>/", views.invite, name="invite"),
]
