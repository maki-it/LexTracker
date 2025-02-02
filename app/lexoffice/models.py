from django.db import models

# Create your models here.

class Customer(models.Model):
  class CustomerType(models.TextChoices):
    PERSON = 'person', "Person"
    COMPANY = 'company', "Company"

  id = models.UUIDField(primary_key=True)
  organization_id = models.UUIDField()
  number = models.PositiveIntegerField(verbose_name="Cost center number", default=0)
  version = models.PositiveIntegerField(default=0, verbose_name="Revision")  # Number of changes to the customer
  type = models.CharField(choices=CustomerType.choices, default=CustomerType.COMPANY, max_length=10)
  name = models.CharField(max_length=255, blank=True, null=True, default=None, db_index=True)
  is_archived = models.BooleanField(default=False)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
    return f"{self.number} - {self.name}"

  class Meta:
    constraints = [
      models.UniqueConstraint(fields=['organization_id', 'number'], name='unique_cost_center_number'),
      models.UniqueConstraint(fields=['organization_id', 'id'], name='unique_customer_id'),
    ]
