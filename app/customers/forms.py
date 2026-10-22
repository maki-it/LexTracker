from django import forms

from core.forms import StyledFormMixin
from customers.models import Customer


class CustomerForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["name", "email", "phone", "default_hourly_rate", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 4})}
