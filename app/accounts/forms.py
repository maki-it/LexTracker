from django import forms


class LoginForm(forms.Form):
    username = forms.CharField(label="Benutzername", max_length=150, widget=forms.TextInput(attrs={"autofocus": True}))
    password = forms.CharField(label="Passwort", strip=False, widget=forms.PasswordInput)
