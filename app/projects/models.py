import uuid
from datetime import timedelta, datetime

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch.dispatcher import receiver
from django.utils import timezone

from lexoffice.models import Customer


# Create your models here.

class Project(models.Model):
  """
  A project is a collection of activities, e.g. website development, marketing campaign, etc.
  """
  id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
  customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='projects')
  categories = models.ManyToManyField('Category', related_name='projects')
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
  def is_completed(self) -> bool:
    if not self.end_date:
      return False

    if self.end_date < timezone.now().date():
      return True
    return False

  def clean(self):
    # Check if end_date is after start_date
    if self.end_date and self.end_date < self.start_date:
      raise ValueError("End time must be after start time")

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
  title = models.CharField(max_length=255)
  description = models.TextField(blank=True, null=True, default=None)
  is_chargeable = models.BooleanField(default=True)
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
  # New fields for billing
  billed = models.BooleanField(default=False, db_index=True)
  lexware_invoice_id = models.CharField(max_length=64, blank=True, null=True)
  lexware_invoice_url = models.URLField(blank=True, null=True)

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
      raise ValueError("End time must be after start time")

    # Check if other activity overlaps with this activity
    if Activity.objects.filter(
      user=self.user,
      started_at__lt=self.ended_at,
      ended_at__gt=self.started_at
    ).exclude(id=self.id).exists():
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


class Invoice(models.Model):
    """Stores metadata for generated invoices and links to Lexware."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='invoices')
    created_at = models.DateTimeField(auto_now_add=True)
    lexware_invoice_id = models.CharField(max_length=64, blank=True, null=True)
    lexware_invoice_url = models.URLField(blank=True, null=True)
    activities = models.ManyToManyField(Activity, related_name='invoices')
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default='EUR')
    finalized = models.BooleanField(default=False)

    def __str__(self):
        return f"Invoice {self.lexware_invoice_id or self.id} for {self.customer.name}"


DATE_FORMATS = [
  ('D, d. M', 'Wed, 31. Dec'),
  ('D, d.m', 'Wed, 31.12'),
  ('D, d. M Y', 'Wed, 31. Dec 2021'),
  ('D, d.m.Y', 'Wed, 31.12.2021'),
  ('d.m.Y', '31.12.2021'),
  ('d. M Y', '31. Dec 2021'),
  ('Y-m-d', '2021-12-31'),
  ('d/m/Y', '31/12/2021'),
  ('m/d/Y', '12/31/2021'),
  ('Y/m/d', '2021/12/31'),
  ('Y.m.d', '2021.31.12'),
  ('d.m.Y', '12.31.2021'),
  ('Y. M. d', '2021. Dec. 31'),
]

TIME_FORMATS = [
  ('H:i', '13:45'),
  ('h:i A', '1:45 PM'),
]

TIME_STEPS = [
  (1*60, '1 minute'),
  (5*60, '5 minutes'),
  (10*60, '10 minutes'),
  (15*60, '15 minutes'),
  (30*60, '30 minutes'),
  (60*60, '1 hour'),
]

TABLE_ROWS = [
  (10, '10 rows'),
  (25, '25 rows'),
  (50, '50 rows'),
  (100, '100 rows'),
]

class Settings(models.Model):
  """User settings for the time tracker"""
  user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
  updated_at = models.DateTimeField(auto_now=True)
  show_empty_days = models.BooleanField(default=False, help_text="Show days without activities in the activity list")
  date_format = models.CharField(max_length=10, choices=DATE_FORMATS, default=DATE_FORMATS[0][0])
  time_format = models.CharField(max_length=10, choices=TIME_FORMATS, default=TIME_FORMATS[0][0])
  time_step = models.PositiveSmallIntegerField(choices=TIME_STEPS, default=TIME_STEPS[3][0], help_text="Step size for time input in activity form")
  table_rows = models.PositiveSmallIntegerField(choices=TABLE_ROWS, default=TABLE_ROWS[1][0], help_text="Number of rows to show in tables")

  def __str__(self):
    return f"{self.user.username} - {self.date_format}"

  @receiver(post_save, sender=settings.AUTH_USER_MODEL)
  def create_user_settings(sender, instance=None, created=False, **kwargs):
    if created:
      Settings.objects.create(user=instance,)

  class Meta:
    verbose_name_plural = 'Settings'
