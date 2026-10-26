from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin
from mailer.models import SSL_PORT, STARTTLS_PORT, MailSettings


class MailSettingsForm(StyledFormMixin, forms.ModelForm):
    password = forms.CharField(
        label=_("Passwort"),
        required=False,
        strip=False,
        max_length=200,
        # Never send a stored password back to the browser.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "new-password"}),
    )
    remove_password = forms.BooleanField(label=_("Gespeichertes Passwort entfernen"), required=False)

    class Meta:
        model = MailSettings
        fields = ["host", "port", "security", "username", "from_address", "from_name"]

    field_order = ["host", "port", "security", "username", "password", "remove_password"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.encrypted_password:
            self.fields["password"].help_text = _("Leer lassen, um das gespeicherte Passwort zu behalten.")
        else:
            del self.fields["remove_password"]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("host") and not cleaned.get("from_address"):
            self.add_error("from_address", _("Ohne Absenderadresse kann die App keine E-Mails verschicken."))
        if cleaned.get("host"):
            self._check_port_and_security(cleaned.get("port"), cleaned.get("security"))
        return cleaned

    def _check_port_and_security(self, port: int | None, security: str | None) -> None:
        """Catch the usual mix-up before it turns into a TLS error: 587 speaks STARTTLS, 465 SSL/TLS."""
        Security = MailSettings.Security
        if port == STARTTLS_PORT and security == Security.SSL:
            self.add_error(
                "security",
                _(
                    "Port 587 nutzt STARTTLS statt SSL/TLS. "
                    "Wähle „STARTTLS“ oder, wenn dein Anbieter SSL/TLS verlangt, Port 465."
                ),
            )
        elif port == SSL_PORT and security == Security.STARTTLS:
            self.add_error(
                "security",
                _(
                    "Port 465 erwartet SSL/TLS von Anfang an. "
                    "Wähle „SSL/TLS“ oder, wenn dein Anbieter STARTTLS verlangt, Port 587."
                ),
            )

    def save(self, commit=True):
        if self.cleaned_data.get("password"):
            self.instance.set_password(self.cleaned_data["password"])
        elif self.cleaned_data.get("remove_password"):
            self.instance.set_password("")
        return super().save(commit)


class TestMailForm(StyledFormMixin, forms.Form):
    to = forms.EmailField(label=_("Testmail an"))
