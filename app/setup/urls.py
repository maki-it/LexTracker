from django.urls import path

from setup import views

app_name = "setup"

urlpatterns = [
    path("", views.account, name="account"),
    path("lexware/", views.lexware, name="lexware"),
    path("email/", views.mail, name="mail"),
    path("backup/", views.backup, name="backup"),
    path("done/", views.done, name="done"),
]
