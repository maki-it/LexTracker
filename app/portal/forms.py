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


SALUTATIONS = ("Herr", "Frau")


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
    # The contact person of a company. Left out for contacts that are persons.
    person_salutation = forms.ChoiceField(label="Anrede", required=False)
    person_first_name = forms.CharField(label="Vorname", max_length=100, required=False)
    person_last_name = forms.CharField(label="Nachname", max_length=100, required=False)
    person_email = forms.EmailField(label="E-Mail des Ansprechpartners", required=False)
    person_phone = forms.CharField(label="Telefon des Ansprechpartners", max_length=50, required=False)
    # The contact's version in Lexware when the form was loaded, to notice changes made in the meantime.
    version = forms.IntegerField(widget=forms.HiddenInput)

    PERSON_NAMES = ("salutation", "first_name", "last_name", "email", "phone")

    def __init__(self, *args, with_person: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.with_person = with_person
        choices = [("", "–"), *((s, s) for s in SALUTATIONS)]
        salutation = self.initial.get("person_salutation")
        if salutation and salutation not in SALUTATIONS:
            choices.insert(1, (salutation, salutation))
        self.fields["person_salutation"].choices = choices
        if not with_person:
            for name in self.PERSON_NAMES:
                del self.fields[f"person_{name}"]
        # Keep a country that is not in the list selectable.
        country = self.initial.get("countryCode")
        if country and country not in COUNTRIES:
            self.fields["countryCode"].choices = [(country, country), *COUNTRIES.items()]

    @property
    def address(self) -> dict:
        return {key: self.cleaned_data[key] for key in ("supplement", "street", "zip", "city", "countryCode")}

    @property
    def person(self) -> dict:
        return {name: self.cleaned_data[f"person_{name}"] for name in self.PERSON_NAMES}
