from django import forms
from django.utils import timezone
from django.utils.translation import gettext
from django.utils.translation import gettext_lazy as _

from core import branding
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
    logo = forms.FileField(
        label=_("Logo"),
        required=False,
        widget=forms.FileInput(attrs={"accept": "image/png,image/jpeg,image/webp,image/svg+xml"}),
    )
    remove_logo = forms.BooleanField(label=_("Eigenes Logo entfernen"), required=False)

    class Meta:
        model = AppSettings
        fields = [
            "app_name",
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

    logo_changed = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Not a lazy string with %, which would be translated when the module is imported.
        self.fields["logo"].help_text = gettext(
            "PNG, JPEG, WebP oder SVG, höchstens %(size)s KB. Quadratische Bilder passen am besten."
        ) % {"size": branding.LOGO_MAX_SIZE // 1024}

    def clean_logo(self):
        file = self.cleaned_data.get("logo")
        if not file:
            return None
        # The file is read once here and stored by ``clean``.
        return branding.read_logo(file)

    def clean(self):
        cleaned = super().clean()
        logo = cleaned.get("logo")
        if logo:
            self.instance.logo_data, self.instance.logo_type = logo
        elif cleaned.get("remove_logo"):
            self.instance.logo_data, self.instance.logo_type = None, ""
        else:
            return cleaned
        self.instance.logo_updated_at = timezone.now()
        self.logo_changed = True
        return cleaned

    @property
    def saved_fields(self) -> list[str]:
        """The model fields to write: the ones on the page, and the logo if it was replaced or removed."""
        fields = [name for name in self.fields if name not in ("logo", "remove_logo")]
        return [*fields, "logo_data", "logo_type", "logo_updated_at"] if self.logo_changed else fields
