from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm

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


class UserForm(StyledFormMixin, forms.ModelForm):
    """An administrator creates or edits a login for an employee or a customer."""

    PORTAL_FIELDS = ["portal_budget", "portal_entries", "portal_descriptions", "portal_invoices"]

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "customer",
            "portal_budget",
            "portal_entries",
            "portal_descriptions",
            "portal_invoices",
            "is_active",
        ]
        labels = {"is_active": "aktiv"}
        help_texts = {
            "username": "Damit meldet sich die Person an.",
            "customer": "Nur für Kunden: wessen Projekte, Zeiten und Rechnungen sie sieht.",
            "is_active": "Deaktivierte Benutzer können sich nicht mehr anmelden.",
        }

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields["customer"].queryset = self.fields["customer"].queryset.filter(is_archived=False)
        self.fields["customer"].empty_label = "– kein Kunde –"
        if self.instance.pk is None:
            del self.fields["is_active"]
        # Descriptions belong to the time entries; static/js/app.js greys the box out without them.
        self.fields["portal_descriptions"].widget.attrs["data-requires"] = "portal_entries"

    def clean(self):
        cleaned = super().clean()
        role = cleaned.get("role")
        if role == User.Role.CUSTOMER and not cleaned.get("customer"):
            self.add_error("customer", "Ein Kundenzugang braucht einen Kunden.")
        elif role and role != User.Role.CUSTOMER:
            cleaned["customer"] = None
        if not cleaned.get("portal_entries"):
            # The greyed-out box is not sent. Keep the stored choice so it is back when the entries are.
            cleaned["portal_descriptions"] = self.instance.portal_descriptions
        if self.instance.pk and self.instance == self.acting_user:
            # Do not lock yourself out.
            if role != User.Role.ADMIN:
                self.add_error("role", "Du kannst dir selbst die Administratorrolle nicht nehmen.")
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "Du kannst dich nicht selbst deaktivieren.")
        return cleaned


class InviteForm(StyledFormMixin, SetPasswordForm):
    pass
