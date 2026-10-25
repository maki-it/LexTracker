from django import forms
from django.utils.translation import gettext_lazy as _

from core.models import AppSettings

# Help text for text fields that are shown with the |markdown template filter.
MARKDOWN_HELP = _("Markdown möglich: **fett**, *kursiv*, [Linktext](https://example.com), Listen mit „- “.")


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
            "invoice_detail",
            "login_max_attempts",
            "login_lockout_minutes",
            "login_link_enabled",
            "lexware_sync_interval",
            "lexware_sync_from",
            "lexware_sync_until",
            "invoice_sync_interval",
            "invoice_sync_from",
            "invoice_sync_until",
            "backup_enabled",
            "backup_time",
            "backup_keep",
            "weekly_report_enabled",
            "weekly_report_weekday",
            "weekly_report_time",
            "timer_reminder_hours",
            "overdue_notice",
            "overdue_notice_days",
            "invite_by_mail",
        ]
        widgets = {
            name: forms.TimeInput(attrs={"type": "time"}, format="%H:%M")
            for name in [
                "lexware_sync_from",
                "lexware_sync_until",
                "invoice_sync_from",
                "invoice_sync_until",
                "backup_time",
                "weekly_report_time",
            ]
        }
