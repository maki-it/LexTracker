import uuid

from django.db import models
from django.utils import timezone

from lexoffice.models import Customer


# Create your models here.

class Project(models.Model):
  """
  A project is a collection of activities, e.g. website development, marketing campaign, etc.
  """
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
  customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
  title = models.CharField(max_length=255)
  description = models.TextField(blank=True, null=True, default=None)

  start_date = models.DateField(default=timezone.now)
  end_date = models.DateField(blank=True, null=True, default=None)
  is_archived = models.BooleanField(default=False)

  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
    return self.title

  @property
  def duration(self) -> int | None:
    if self.end_date is None:
      return None
    return self.end_date - self.start_date

  @property
  def is_finished(self) -> bool:
    return bool(self.end_date)

  def save(self, *args, **kwargs):
    # Check if end_date is after start_date
    if self.end_date and self.end_date < self.start_date:
      raise ValueError("End date must be after start date")

    # Set end_date to current date if project is archived
    if self.is_archived and not self.end_date:
      self.end_date = timezone.now().date()

    super(Project, self).save(*args, **kwargs)


class Category(models.Model):
  """
  A category defines the type of activity, e.g. development, design, training, administration, etc.
  """
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
  projects = models.ManyToManyField(Project, related_name='categories')
  title = models.CharField(max_length=255)
  description = models.TextField(blank=True, null=True, default=None)
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)

  def __str__(self):
    return self.title

class Activity(models.Model):
  """
  An activity is a task that is part of a project, e.g. design a logo, develop a website, etc.
  """
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
  project = models.ForeignKey(Project, on_delete=models.CASCADE)
  category = models.ForeignKey(Category, on_delete=models.CASCADE)
  notes = models.TextField(blank=True, null=True, default=None)
  started_at = models.DateTimeField(auto_now_add=True)
  ended_at = models.DateTimeField(blank=True, null=True, default=None)
  is_chargeable = models.BooleanField(default=True)  # Is this activity chargeable to the customer?

  def __str__(self):
    return self.title

  @property
  def is_finished(self) -> bool:
    return bool(self.ended_at)

  def save(self, *args, **kwargs):
    # Check if ended_at is after started_at
    if self.ended_at and self.ended_at < self.started_at:
      raise ValueError("End date must be after start date")

    super(Activity, self).save(*args, **kwargs)
