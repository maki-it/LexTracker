from django.urls import path

from . import views

app_name = 'projects'

urlpatterns = [
  path('categories/', views.get_categories, name='get_categories'),
]
