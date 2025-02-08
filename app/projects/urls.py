from django.urls import path

from . import views

app_name = 'projects'

urlpatterns = [
  path('categories/', views.get_categories, name='get_categories'),
  path('activities/', views.get_activities, name='get_activities'),
  path('activities/<uuid:activity_id>', views.get_activity, name='get_activity'),
  path('activities/update/<uuid:activity_id>', views.update_activity, name='update_activity'),
  path('activities/delete/<uuid:activity_id>', views.delete_activity, name='delete_activity'),
  path('save_activity', views.save_activity, name='save_activity'),
]
