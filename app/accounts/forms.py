from django import forms
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.db.models import Q

from accounts.models import ApiToken, User
from core.forms import StyledFormMixin
from projects.models import Project


class LoginForm(forms.Form):
    username = forms.CharField(label="Benutzername", max_length=150, widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput)


class LinkRequestForm(forms.Form):
    identifier = forms.CharField(
        label="Benutzername oder E-Mail-Adresse",
        max_length=254,
        widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username", "class": "input"}),
    )


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
        fields = [
            "first_name",
            "last_name",
            "email",
            "theme",
            "date_format",
            "duration_format",
            "list_page_size",
            "weekly_report",
            "timer_reminder",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Customers do not book time, so there is nothing to report or remind them of.
        if self.instance.is_customer:
            del self.fields["weekly_report"]
            del self.fields["timer_reminder"]
        else:
            self.fields["email"].help_text = "Für Wochenbericht, Erinnerungen und Links zum Anmelden."


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


class ProjectChoices(forms.ModelMultipleChoiceField):
    def label_from_instance(self, project: Project) -> str:
        return f"{project.customer.name} · {project.name}"


class UserForm(StyledFormMixin, forms.ModelForm):
    """An administrator creates or edits a login for an employee or a customer."""

    PORTAL_FIELDS = ["portal_budget", "portal_entries", "portal_descriptions", "portal_invoices", "portal_contact"]
    BOOKING_FIELDS = ["bookable_customers", "bookable_projects"]

    class Meta:
        model = User
        fields = [
            "username",
            "first_name",
            "last_name",
            "email",
            "role",
            "customer",
            "bookable_customers",
            "bookable_projects",
            "portal_budget",
            "portal_entries",
            "portal_descriptions",
            "portal_invoices",
            "portal_contact",
            "is_active",
        ]
        labels = {"is_active": "aktiv", "bookable_customers": "Kunden", "bookable_projects": "Einzelne Projekte"}
        widgets = {
            "bookable_customers": forms.CheckboxSelectMultiple,
            "bookable_projects": forms.CheckboxSelectMultiple,
        }
        field_classes = {"bookable_projects": ProjectChoices}
        help_texts = {
            "username": "Damit meldet sich die Person an.",
            "customer": "Wessen Projekte, Zeiten und Rechnungen dieser Zugang sieht.",
            "is_active": "Deaktivierte Benutzer können sich nicht mehr anmelden.",
            "bookable_customers": "Mit allen Projekten, auch künftigen.",
            "bookable_projects": "Zusätzlich zu den Kunden oben.",
        }

    def __init__(self, *args, acting_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.acting_user = acting_user
        self.fields["customer"].queryset = self.fields["customer"].queryset.filter(is_archived=False)
        self.fields["customer"].empty_label = "– kein Kunde –"
        self.fields["customer"].widget.attrs["data-searchable"] = ""
        # Keep what is unlocked selectable even if it is archived or done by now.
        unlocked = self.instance.pk
        customers = self.fields["bookable_customers"].queryset
        self.fields["bookable_customers"].queryset = (
            customers.filter(Q(is_archived=False) | Q(bookable_by=unlocked)).distinct().order_by("name")
        )
        self.fields["bookable_projects"].queryset = (
            Project.objects.filter(~Q(status=Project.Status.DONE) | Q(bookable_by=unlocked))
            .distinct()
            .select_related("customer")
            .order_by("customer__name", "name")
        )
        # A new user already has an ID, so ask the state whether it is saved.
        if self.instance._state.adding:
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
            # The customer access settings are hidden for other roles and not sent: keep what is stored.
            for name in self.PORTAL_FIELDS:
                cleaned[name] = getattr(self.instance, name)
        if role and role != User.Role.EMPLOYEE:
            # Same for what an employee may book on.
            for name in self.BOOKING_FIELDS:
                cleaned[name] = [] if self.instance._state.adding else getattr(self.instance, name).all()
        if not cleaned.get("portal_entries"):
            # The greyed-out box is not sent. Keep the stored choice so it is back when the entries are.
            cleaned["portal_descriptions"] = self.instance.portal_descriptions
        if not self.instance._state.adding and self.instance == self.acting_user:
            # Do not lock yourself out.
            if role != User.Role.ADMIN:
                self.add_error("role", "Du kannst dir selbst die Administratorrolle nicht nehmen.")
            if cleaned.get("is_active") is False:
                self.add_error("is_active", "Du kannst dich nicht selbst deaktivieren.")
        return cleaned


class InviteForm(StyledFormMixin, SetPasswordForm):
    pass
