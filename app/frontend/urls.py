from django.urls import path, include

from . import views

app_name = 'frontend'
urlpatterns = [
  path('', views.time_tracker, name='time_tracker'),
  path('history', views.history, name='history'),
  path('reports', views.reports, name='reports'),
  path('forms/activity', views.activity_form, name='activity_form'),
  path('forms/activity/<uuid:activity_id>', views.activity_form, name='update_activity_form'),
]
