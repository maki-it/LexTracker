from django.urls import path, include

from . import views

app_name = 'frontend'
urlpatterns = [
  path('', views.activities, name='activities'),
  path('reports', views.reports, name='reports'),
  path('projects', views.projects, name='projects'),
  path('customers', views.customers, name='customers'),
  path('customers/table', views.customers_table, name='customers_table'),
  path('settings', views.settings, name='settings'),
  path('forms/activity', views.activity_form, name='create_activity_form'),
  path('forms/activity/<uuid:activity_id>/<str:action>', views.activity_form, name='update_activity_form'),
  path('logout', views.logout, name='logout'),
]
