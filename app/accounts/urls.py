from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/code/", views.login_code, name="login_code"),
    path("login/link/", views.login_link_request, name="login_link_request"),
    path("login/link/<str:key>/", views.login_link, name="login_link"),
    path("password/forgot/", views.password_forgot, name="password_forgot"),
    path("password/reset/<uidb64>/<token>/", views.password_reset, name="password_reset"),
    path("language/", views.set_language, name="set_language"),
    path("logout/", views.logout_view, name="logout"),
    path("invite/<uidb64>/<token>/", views.invite, name="invite"),
]
