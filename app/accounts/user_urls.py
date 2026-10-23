from django.urls import path

from accounts import user_views

app_name = "users"

urlpatterns = [
    path("", user_views.user_list, name="list"),
    path("neu/", user_views.user_form, name="create"),
    path("<int:pk>/", user_views.user_form, name="edit"),
    path("<int:pk>/loeschen/", user_views.user_delete, name="delete"),
    path("<int:pk>/einladung/", user_views.invite_link, name="invite"),
]
