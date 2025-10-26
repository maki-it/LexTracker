from django import forms

from projects.models import Settings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        exclude = ['user', 'id', 'created_at', 'updated_at']
        widgets = {
          'show_empty_days': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
          'date_format': forms.Select(attrs={'class': 'form-select'}),
          'time_format': forms.Select(attrs={'class': 'form-select'}),
          'time_step': forms.Select(attrs={'class': 'form-select'}),
          'table_rows': forms.Select(attrs={'class': 'form-select'}),
        }
