from django import forms
from django.db.models import Q

from billing.models import BillingAgreement
from core.forms import StyledFormMixin


class BillingAgreementForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = BillingAgreement
        fields = ["kind", "period", "included_hours", "fixed_price", "overage_rate", "valid_from", "valid_until"]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "valid_until": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        }

    def __init__(self, *args, customer, **kwargs):
        super().__init__(*args, **kwargs)
        self.customer = customer

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("kind") == BillingAgreement.Kind.RETAINER:
            for name in ("included_hours", "fixed_price"):
                if cleaned.get(name) is None:
                    self.add_error(name, "Für einen Retainer erforderlich.")
        start, end = cleaned.get("valid_from"), cleaned.get("valid_until")
        if start and end and end < start:
            self.add_error("valid_until", "Das Ende liegt vor dem Beginn.")
        elif start and self._overlapping(start, end).exists():
            self.add_error("valid_from", "Für diesen Zeitraum gilt schon eine andere Vereinbarung.")
        return cleaned

    def _overlapping(self, start, end):
        # Only one agreement may apply to a day, otherwise billing would be ambiguous.
        others = self.customer.billing_agreements.exclude(pk=self.instance.pk)
        others = others.filter(Q(valid_until__isnull=True) | Q(valid_until__gte=start))
        return others.filter(valid_from__lte=end) if end else others


class PeriodForm(forms.Form):
    start = forms.DateField(label="Von", widget=forms.DateInput(attrs={"type": "date", "class": "input"}))
    end = forms.DateField(label="Bis", widget=forms.DateInput(attrs={"type": "date", "class": "input"}))

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("start") and cleaned.get("end") and cleaned["end"] < cleaned["start"]:
            raise forms.ValidationError("Das Ende liegt vor dem Beginn.")
        return cleaned
