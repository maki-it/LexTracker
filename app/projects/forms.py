from time import sleep

from django import forms
from projects.models import Activity, Project, Category
from lexoffice.models import Customer


class TrackActivityForm(forms.ModelForm):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.fields['project'].queryset = Project.objects.filter(is_archived=False).order_by('customer__number', 'title')

  class Meta:
    model = Activity
    exclude = ['id', 'user']


class ProjectForm(forms.ModelForm):
  class Meta:
    model = Project
    exclude = ['id', 'created_at', 'updated_at']


class CategoryForm(forms.ModelForm):
  class Meta:
    model = Category
    exclude = ['id', 'created_at', 'updated_at']


class UnbilledActivitySelectionForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.none(), required=True)
    activities = forms.ModelMultipleChoiceField(
        queryset=Activity.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        required=True,
        label="Unbilled Activities"
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['customer'].queryset = Customer.objects.filter(
            projects__activities__billed=False,
            projects__activities__ended_at__isnull=False,
            projects__activities__category__is_chargeable=True
        ).distinct()
        data = kwargs.get('data') or (args[0] if args else None)
        customer_id = None
        if data:
            customer_id = data.get('customer')
        if customer_id:
            try:
                customer = Customer.objects.get(pk=customer_id)
                self.fields['activities'].queryset = Activity.objects.filter(
                    project__customer=customer, billed=False, ended_at__isnull=False, category__is_chargeable=True
                ).order_by('started_at')
            except Customer.DoesNotExist:
                self.fields['activities'].queryset = Activity.objects.none()
        else:
            self.fields['activities'].queryset = Activity.objects.none()


class RevertBilledActivityForm(forms.ModelForm):
    class Meta:
        model = Activity
        fields = ['billed']
