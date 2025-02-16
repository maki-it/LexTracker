from django import forms

from projects.models import Settings


class SettingsForm(forms.ModelForm):
    class Meta:
        model = Settings
        fields = ['show_empty_days', 'date_format', 'time_format', 'time_step']
        widgets = {
            'show_empty_days': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'date_format': forms.Select(attrs={'class': 'form-select'}),
            'time_format': forms.Select(attrs={'class': 'form-select'}),
            'time_step': forms.Select(attrs={'class': 'form-select'}),
        }
