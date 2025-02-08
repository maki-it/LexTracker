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
