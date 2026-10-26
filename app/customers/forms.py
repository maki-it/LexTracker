from django import forms
from django.utils.translation import gettext_lazy as _

from core.forms import MARKDOWN_HELP, StyledFormMixin
from customers.lexware import NOTE_MAX_LENGTH
from customers.models import Category, Customer


class CustomerForm(StyledFormMixin, forms.ModelForm):
    new_categories = forms.CharField(
        label=_("Neue Kategorien"),
        required=False,
        max_length=500,
        help_text=_("Mehrere durch Komma trennen, z. B. „Stammkunde, Hosting“."),
    )

    class Meta:
        model = Customer
        fields = ["name", "email", "phone", "default_hourly_rate", "categories", "new_categories", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4}), "categories": forms.CheckboxSelectMultiple}
        help_texts = {"notes": MARKDOWN_HELP}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.fields["categories"].queryset.exists():
            # Nothing to tick yet: new categories are typed in below.
            del self.fields["categories"]
        if self.instance.lexware_id:
            self.fields["notes"].help_text = _(
                "Wird mit der Notiz des Kontakts in Lexware Office abgeglichen (höchstens %(max)d Zeichen). "
                "Markdown wird dort als Text angezeigt."
            ) % {"max": NOTE_MAX_LENGTH}

    def clean_notes(self) -> str:
        notes = self.cleaned_data["notes"]
        if self.instance.lexware_id and len(notes.strip()) > NOTE_MAX_LENGTH:
            raise forms.ValidationError(
                _("Lexware Office nimmt Notizen bis %(max)d Zeichen an, diese hat %(length)d."),
                params={"max": NOTE_MAX_LENGTH, "length": len(notes.strip())},
            )
        return notes

    def save_categories(self) -> None:
        """Set the customer's categories, creating typed-in ones. Run after the customer is saved."""
        categories = list(self.cleaned_data.get("categories") or [])
        for name in {n.strip() for n in self.cleaned_data["new_categories"].split(",") if n.strip()}:
            existing = Category.objects.filter(name__iexact=name).first()
            categories.append(existing or Category.objects.create(name=name[:100]))
        self.instance.categories.set(categories)
        # Categories no customer uses any more are removed, so the filter stays tidy.
        Category.objects.filter(customers__isnull=True).delete()
