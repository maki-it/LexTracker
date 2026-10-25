from django.urls import path

from setup import views

app_name = "setup"

urlpatterns = [
    path("", views.account, name="account"),
    path("zwei-faktor/", views.two_factor, name="mfa"),
    path("lexware/", views.lexware, name="lexware"),
    path("e-mail/", views.mail, name="mail"),
    path("datensicherung/", views.backup, name="backup"),
    path("fertig/", views.done, name="done"),
]
