from django.urls import path

from . import views

app_name = 'frontend'
urlpatterns = [
  path('login', views.login_view, name='login'),
  path('logout', views.logout, name='logout'),
  path('', views.activities, name='activities'),
  path('reports', views.reports, name='reports'),
  path('reports/table', views.reports_table, name='reports_activities_table'),
  path('projects', views.projects, name='projects'),
  path('projects/categories', views.projects, name='categories'),
  path('projects/table/projects', views.projects_table, name='projects_table'),
  path('projects/table/categories', views.categories_table, name='categories_table'),
  path('customers', views.customers, name='customers'),
  path('customers/table', views.customers_table, name='customers_table'),
  path('settings', views.settings, name='settings'),
  path('forms/activity', views.activity_form, name='create_activity_form'),
  path('forms/activity/<uuid:activity_id>/<str:action>', views.activity_form, name='update_activity_form'),
  path('forms/project', views.project_form, name='create_project_form'),
  path('forms/project/<uuid:project_id>/<str:action>', views.project_form, name='update_project_form'),
  path('forms/category', views.category_form, name='create_category_form'),
  path('forms/category/<uuid:category_id>/<str:action>', views.category_form, name='update_category_form'),
]
