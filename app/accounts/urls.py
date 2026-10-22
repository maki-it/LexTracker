from django.urls import path

from accounts import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("login/code/", views.login_code, name="login_code"),
    path("logout/", views.logout_view, name="logout"),
]
