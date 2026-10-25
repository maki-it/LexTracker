from django.urls import path

from mailer import views

app_name = "mailer"

urlpatterns = [
    path("", views.mail_settings, name="settings"),
    path("test/", views.test_mail, name="test"),
    path("<uuid:pk>/retry/", views.retry, name="retry"),
]
