from django.urls import path

from mcpserver import views

app_name = "mcp"

urlpatterns = [
    path("", views.endpoint, name="endpoint"),
]
