from django import forms
from django.contrib.auth.forms import PasswordChangeForm

from accounts.models import ApiToken, User
from core.forms import StyledFormMixin


class LoginForm(forms.Form):
    username = forms.CharField(label="Benutzername", max_length=150, widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput)


class CodeForm(forms.Form):
    code = forms.CharField(
        label="Code",
        max_length=20,
        widget=forms.TextInput(
            attrs={"autofocus": True, "autocomplete": "one-time-code", "inputmode": "numeric", "class": "input"}
        ),
    )


class PreferencesForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "theme", "date_format", "duration_format"]


class StyledPasswordChangeForm(StyledFormMixin, PasswordChangeForm):
    pass


class ConfirmPasswordForm(forms.Form):
    password = forms.CharField(
        label="Aktuelles Passwort",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password", "class": "input"}),
    )

    def __init__(self, user, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user

    def clean_password(self):
        password = self.cleaned_data["password"]
        if not self.user.check_password(password):
            raise forms.ValidationError("Das Passwort ist falsch.")
        return password


class ApiTokenForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ApiToken
        fields = ["name"]
