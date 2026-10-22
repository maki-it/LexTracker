from django.urls import path

from accounts import views

app_name = "account"

urlpatterns = [
    path("", views.account, name="settings"),
    path("passwort/", views.password_change, name="password"),
    path("zwei-faktor/einrichten/", views.mfa_setup, name="mfa_setup"),
    path("zwei-faktor/", views.mfa_manage, name="mfa_manage"),
]
