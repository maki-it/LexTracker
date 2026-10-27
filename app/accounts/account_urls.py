from django.urls import path

from accounts import passkey_views, views

app_name = "account"

urlpatterns = [
    path("", views.account, name="settings"),
    path("password/", views.password_change, name="password"),
    path("two-factor/setup/", views.mfa_setup, name="mfa_setup"),
    path("two-factor/", views.mfa_manage, name="mfa_manage"),
    path("passkeys/options/", passkey_views.passkey_register_options, name="passkey_options"),
    path("passkeys/", passkey_views.passkey_add, name="passkey_add"),
    path("passkeys/<uuid:pk>/remove/", passkey_views.passkey_remove, name="passkey_remove"),
    path("tokens/", views.token_create, name="token_create"),
    path("tokens/<uuid:pk>/revoke/", views.token_revoke, name="token_revoke"),
]
