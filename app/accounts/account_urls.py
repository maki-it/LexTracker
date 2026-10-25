from django.urls import path

from accounts import views

app_name = "account"

urlpatterns = [
    path("", views.account, name="settings"),
    path("password/", views.password_change, name="password"),
    path("two-factor/setup/", views.mfa_setup, name="mfa_setup"),
    path("two-factor/", views.mfa_manage, name="mfa_manage"),
    path("tokens/", views.token_create, name="token_create"),
    path("tokens/<uuid:pk>/revoke/", views.token_revoke, name="token_revoke"),
]
