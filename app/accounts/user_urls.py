from django.urls import path

from accounts import user_views

app_name = "users"

urlpatterns = [
    path("", user_views.user_list, name="list"),
    path("new/", user_views.user_form, name="create"),
    path("<uuid:pk>/", user_views.user_form, name="edit"),
    path("<uuid:pk>/delete/", user_views.user_delete, name="delete"),
    path("<uuid:pk>/invite/", user_views.invite_link, name="invite"),
]
