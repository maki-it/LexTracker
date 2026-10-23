from django import forms

from core.forms import StyledFormMixin
from mailer.models import MailSettings


class MailSettingsForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(
        label="Passwort",
        required=False,
        strip=False,
        max_length=200,
        # Never send a stored password back to the browser.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    remove_password = forms.BooleanField(label="Gespeichertes Passwort entfernen", required=False)

    class Meta:
        model = MailSettings
        fields = ["host", "port", "security", "username", "from_address", "from_name", "base_url"]

    field_order = ["host", "port", "security", "username", "password", "remove_password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.encrypted_password:
            self.fields["password"].help_text = "Leer lassen, um das gespeicherte Passwort zu behalten."
        else:
            del self.fields["remove_password"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("host") and not cleaned.get("from_address"):
            self.add_error("from_address", "Ohne Absenderadresse kann die App keine E-Mails verschicken.")
        return cleaned

    def save(self, commit=True):
        if self.cleaned_data.get("password"):
            self.instance.set_password(self.cleaned_data["password"])
        elif self.cleaned_data.get("remove_password"):
            self.instance.set_password("")
        return super().save(commit)


class TestMailForm(StyledFormMixin, forms.Form):
    to = forms.EmailField(label="Testmail an")
