from django import forms

from core.models import AppSettings


class StyledFormMixin:
    """Give every widget the app's input styling."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput | forms.CheckboxSelectMultiple):
                widget.attrs.setdefault("class", "size-4 accent-primary")
            else:
                widget.attrs.setdefault("class", "input")


class AppSettingsForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = AppSettings
        fields = [
            "default_hourly_rate",
            "time_rounding",
            "login_max_attempts",
            "login_lockout_minutes",
            "lexware_sync_interval",
            "lexware_sync_from",
            "lexware_sync_until",
            "invoice_sync_interval",
            "invoice_sync_from",
            "invoice_sync_until",
        ]
        widgets = {
            name: forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
            for name in ["lexware_sync_from", "lexware_sync_until", "invoice_sync_from", "invoice_sync_until"]
        }
