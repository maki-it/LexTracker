from django.urls import path

from . import views

app_name = 'projects'

urlpatterns = [
  path('categories/', views.get_categories, name='get_categories'),
  path('categories/<uuid:category_id>', views.get_categories, name='get_category_with_selected'),
  path('activities/', views.get_activities, name='get_activities'),
  path('activities/create', views.create_activity, name='create_activity'),
  path('activities/<uuid:activity_id>', views.get_activity, name='get_activity'),
  path('activities/<uuid:activity_id>/update', views.update_activity, name='update_activity'),
  path('activities/<uuid:activity_id>/delete', views.delete_activity, name='delete_activity'),
]
