from django.urls import path

from push import views

app_name = "push"

urlpatterns = [
    path("sw.js", views.service_worker, name="sw"),
    path("key/", views.public_key, name="key"),
    path("subscribe/", views.subscribe, name="subscribe"),
    path("<uuid:pk>/topics/", views.device_topics, name="topics"),
    path("<uuid:pk>/test/", views.device_test, name="test"),
    path("<uuid:pk>/remove/", views.device_remove, name="remove"),
]
