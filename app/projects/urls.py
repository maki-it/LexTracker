from django.urls import path

from . import views

app_name = 'projects'

urlpatterns = [
  # Activities
  path('activities/', views.get_activities, name='get_activities'),
  path('activities/create', views.create_activity, name='create_activity'),
  path('activities/<uuid:activity_id>', views.get_activity, name='get_activity'),
  path('activities/<uuid:activity_id>/update', views.update_activity, name='update_activity'),
  path('activities/<uuid:activity_id>/delete', views.delete_activity, name='delete_activity'),

  # Categories
  path('categories/', views.get_categories, name='get_categories'),
  path('categories/create', views.create_category, name='create_category'),
  path('categories/<uuid:category_id>', views.get_categories, name='get_category_with_selected'),
  path('categories/<uuid:category_id>/update', views.update_category, name='update_category'),
  path('categories/<uuid:category_id>/delete', views.delete_category, name='delete_category'),

  # Projects
  path('projects/', views.get_projects, name='get_projects'),
  path('projects/create', views.create_project, name='create_project'),
  path('projects/<uuid:project_id>', views.get_project, name='get_project'),
  path('projects/<uuid:project_id>/update', views.update_project, name='update_project'),
  path('projects/<uuid:project_id>/delete', views.delete_project, name='delete_project'),

  # Statistics
  path('statistics/count_activites_per_unit/<str:unit>', views.count_activities_per_unit, name='count_activities_per_unit'),
  path('statistics/chargeable_activities', views.chargeable_activities, name='chargeable_activities'),
]
