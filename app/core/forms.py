from django import forms

from core.models import AppSettings


class StyledFormMixin:
    """Give every widget the app's input styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "size-4 accent-primary")
            else:
                widget.attrs.setdefault("class", "input")


class AppSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = ["default_hourly_rate", "lexware_sync_interval"]
