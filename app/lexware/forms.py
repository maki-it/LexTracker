from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin


class ApiKeyForm(StyledFormMixin, forms.Form):
    api_key = forms.CharField(
        label=_("API-Schlüssel"),
        max_length=200,
        strip=True,
        # Never send a stored key back to the browser.
        widget=forms.PasswordInput(render_value=False, attrs={"autocomplete": "off", "spellcheck": "false"}),
        help_text=_(
            "Erstellst du in Lexware Office unter Erweiterungen > Public API (app.lexware.de/addons/public-api)."
        ),
    )
