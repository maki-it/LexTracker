from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import StyledFormMixin

# Lexware stores the country as ISO 3166 code. The countries offered first, the rest of Europe after them.
COUNTRIES = {
    "DE": _("Deutschland"),
    "AT": _("Österreich"),
    "CH": _("Schweiz"),
    "BE": _("Belgien"),
    "BG": _("Bulgarien"),
    "DK": _("Dänemark"),
    "EE": _("Estland"),
    "FI": _("Finnland"),
    "FR": _("Frankreich"),
    "GR": _("Griechenland"),
    "IE": _("Irland"),
    "IT": _("Italien"),
    "HR": _("Kroatien"),
    "LV": _("Lettland"),
    "LI": _("Liechtenstein"),
    "LT": _("Litauen"),
    "LU": _("Luxemburg"),
    "MT": _("Malta"),
    "NL": _("Niederlande"),
    "NO": _("Norwegen"),
    "PL": _("Polen"),
    "PT": _("Portugal"),
    "RO": _("Rumänien"),
    "SE": _("Schweden"),
    "SK": _("Slowakei"),
    "SI": _("Slowenien"),
    "ES": _("Spanien"),
    "CZ": _("Tschechien"),
    "HU": _("Ungarn"),
    "GB": _("Vereinigtes Königreich"),
    "CY": _("Zypern"),
    "US": _("USA"),
}


# The first countries stay on top; the rest follows in alphabetical order of the language.
FIRST_COUNTRIES = ("DE", "AT", "CH")


def country_choices() -> list[tuple[str, str]]:
    first = [(code, COUNTRIES[code]) for code in FIRST_COUNTRIES]
    rest = sorted(((c, n) for c, n in COUNTRIES.items() if c not in FIRST_COUNTRIES), key=lambda item: str(item[1]))
    return [*first, *rest]


# Lexware stores the salutation as text, so these are the values it gets; the labels are translated.
SALUTATIONS = {"Herr": _("Herr"), "Frau": _("Frau")}


class ContactForm(StyledFormMixin, forms.Form):
    """A customer changes its own contact in Lexware Office."""

    name = forms.CharField(label=_("Name"), max_length=255, help_text=_("Firmenname oder Vor- und Nachname."))
    supplement = forms.CharField(label=_("Adresszusatz"), max_length=255, required=False)
    street = forms.CharField(label=_("Straße und Hausnummer"), max_length=255)
    zip = forms.CharField(label=_("PLZ"), max_length=20)
    city = forms.CharField(label=_("Ort"), max_length=255)
    countryCode = forms.ChoiceField(label=_("Land"), choices=COUNTRIES.items())
    email = forms.EmailField(label=_("E-Mail"), required=False)
    phone = forms.CharField(label=_("Telefon"), max_length=50, required=False)
    # The contact person of a company. Left out for contacts that are persons.
    person_salutation = forms.ChoiceField(label=_("Anrede"), required=False)
    person_first_name = forms.CharField(label=_("Vorname"), max_length=100, required=False)
    person_last_name = forms.CharField(label=_("Nachname"), max_length=100, required=False)
    person_email = forms.EmailField(label=_("E-Mail des Ansprechpartners"), required=False)
    person_phone = forms.CharField(label=_("Telefon des Ansprechpartners"), max_length=50, required=False)
    # The contact's version in Lexware when the form was loaded, to notice changes made in the meantime.
    version = forms.IntegerField(widget=forms.HiddenInput)

    PERSON_NAMES = ("salutation", "first_name", "last_name", "email", "phone")

    def __init__(self, *args, with_person: bool = True, **kwargs):
        super().__init__(*args, **kwargs)
        self.with_person = with_person
        choices = [("", "–"), *SALUTATIONS.items()]
        salutation = self.initial.get("person_salutation")
        if salutation and salutation not in SALUTATIONS:
            choices.insert(1, (salutation, salutation))
        self.fields["person_salutation"].choices = choices
        if not with_person:
            for name in self.PERSON_NAMES:
                del self.fields[f"person_{name}"]
        # Keep a country that is not in the list selectable.
        countries = country_choices()
        country = self.initial.get("countryCode")
        if country and country not in COUNTRIES:
            countries.insert(0, (country, country))
        self.fields["countryCode"].choices = countries

    @property
    def address(self) -> dict:
        return {key: self.cleaned_data[key] for key in ("supplement", "street", "zip", "city", "countryCode")}

    @property
    def person(self) -> dict:
        return {name: self.cleaned_data[f"person_{name}"] for name in self.PERSON_NAMES}
