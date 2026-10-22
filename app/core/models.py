from django.db import models


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField("erstellt", auto_now_add=True)
    updated_at = models.DateTimeField("geändert", auto_now=True)

    class Meta:
        abstract = True
