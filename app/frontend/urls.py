from django.urls import path, include

from . import views

app_name = 'frontend'
urlpatterns = [
  path('', views.index, name='index'),
  path('tracker/', views.time_tracker, name='time_tracker'),
  path('settings/', views.settings, name='settings'),
]
