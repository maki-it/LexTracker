from django import forms

from core.forms import StyledFormMixin

# Lexware stores the country as ISO 3166 code. The countries offered first, the rest of Europe after them.
COUNTRIES = {
    "DE": "Deutschland",
    "AT": "Österreich",
    "CH": "Schweiz",
    "BE": "Belgien",
    "BG": "Bulgarien",
    "DK": "Dänemark",
    "EE": "Estland",
    "FI": "Finnland",
    "FR": "Frankreich",
    "GR": "Griechenland",
    "IE": "Irland",
    "IT": "Italien",
    "HR": "Kroatien",
    "LV": "Lettland",
    "LI": "Liechtenstein",
    "LT": "Litauen",
    "LU": "Luxemburg",
    "MT": "Malta",
    "NL": "Niederlande",
    "NO": "Norwegen",
    "PL": "Polen",
    "PT": "Portugal",
    "RO": "Rumänien",
    "SE": "Schweden",
    "SK": "Slowakei",
    "SI": "Slowenien",
    "ES": "Spanien",
    "CZ": "Tschechien",
    "HU": "Ungarn",
    "GB": "Vereinigtes Königreich",
    "CY": "Zypern",
    "US": "USA",
}


class ContactForm(StyledFormMixin, forms.Form):
    """A customer changes its own contact in Lexware Office."""

    name = forms.CharField(label="Name", max_length=255, help_text="Firmenname oder Vor- und Nachname.")
    supplement = forms.CharField(label="Adresszusatz", max_length=255, required=False)
    street = forms.CharField(label="Straße und Hausnummer", max_length=255)
    zip = forms.CharField(label="PLZ", max_length=20)
    city = forms.CharField(label="Ort", max_length=255)
    countryCode = forms.ChoiceField(label="Land", choices=COUNTRIES.items())
    email = forms.EmailField(label="E-Mail", required=False)
    phone = forms.CharField(label="Telefon", max_length=50, required=False)
    # The contact's version in Lexware when the form was loaded, to notice changes made in the meantime.
    version = forms.IntegerField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep a country that is not in the list selectable.
        country = self.initial.get("countryCode")
        if country and country not in COUNTRIES:
            self.fields["countryCode"].choices = [(country, country), *COUNTRIES.items()]

    @property
    def address(self) -> dict:
        return {key: self.cleaned_data[key] for key in ("supplement", "street", "zip", "city", "countryCode")}
