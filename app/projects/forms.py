from django import forms

from projects.models import Activity, Project, Category
from lexoffice.models import Customer


class TrackActivityForm(forms.ModelForm):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.fields['project'].queryset = Project.objects.filter(is_archived=False).order_by('customer__number', 'title')

  class Meta:
    model = Activity
    exclude = ['id', 'user']


class ProjectForm(forms.ModelForm):
  class Meta:
    model = Project
    exclude = ['id', 'created_at', 'updated_at']


class CategoryForm(forms.ModelForm):
  class Meta:
    model = Category
    exclude = ['id', 'created_at', 'updated_at']
