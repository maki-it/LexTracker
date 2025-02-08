import uuid
from datetime import timedelta, datetime

from django.conf import settings
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
  def duration(self) -> timedelta | None:
    if self.end_date is None:
      return None
    return self.end_date - self.start_date

  @property
  def is_active(self) -> bool:
    return not self.is_archived

  def clean(self):
    # Check if end_date is after start_date
    if self.end_date and self.end_date < self.start_date:
      raise ValueError("End date must be after start date")

  def save(self, *args, **kwargs):
    # Set end_date to current date if project is archived
    if self.is_archived and not self.end_date:
      self.end_date = timezone.now().date()

    super(Project, self).save(*args, **kwargs)


class Category(models.Model):
  """
  A category defines the type of activity, e.g. development, design, training, administration, etc.
  """
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
  projects = models.ManyToManyField(Project, related_name='categories', blank=True, default=None)
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
  user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
  project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='activities')
  category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='categories')
  notes = models.TextField(blank=True, null=True, default=None)
  started_at = models.DateTimeField(default=timezone.now)
  ended_at = models.DateTimeField(blank=True, null=True, default=None)
  # If the category is chargeable, the activity is chargeable by default
  is_chargeable = models.BooleanField(default=True)

  def __str__(self):
    return f"{self.project.title} - {self.category.title} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"

  @property
  def cust_name(self):
    return f"{self.project.customer.name} - {self.project.title}"

  @property
  def is_finished(self) -> bool:
    return bool(self.ended_at)

  def clean(self):
    # Check if ended_at is after started_at
    if self.ended_at and self.ended_at < self.started_at:
      raise ValueError("End date must be after start date")

    # Check if other activity overlaps with this activity
    if Activity.objects.filter(
      user=self.user,
      started_at__lt=self.ended_at,
      ended_at__gt=self.started_at
    ).exists():
      raise ValueError("Time range overlaps with another activity")

  def save(self, *args, **kwargs):
    # Round started_at and ended_at to the nearest minute
    self.started_at = self.round_minutes(self.started_at)
    if self.ended_at:
      self.ended_at = self.round_minutes(self.ended_at)

    super(Activity, self).save(*args, **kwargs)

  @staticmethod
  def round_minutes(dt: datetime) -> datetime:
    """
    Round a datetime object up or down to the nearest minute.
    :param dt:
    :return:
    """
    return dt - timedelta(seconds=dt.second, microseconds=dt.microsecond) + timedelta(seconds=60 if dt.second >= 30 else 0)
