from django.contrib import admin

from tracking.models import TimeEntry


@admin.register(TimeEntry)
class TimeEntryAdmin(admin.ModelAdmin):
    list_display = ("started_at", "ended_at", "task", "user", "is_billable", "duration")
    list_filter = ("is_billable", "user", "task__project__customer")
    search_fields = ("description", "task__name", "task__project__name")
    list_select_related = ("task", "task__project", "user")
    date_hierarchy = "started_at"
    autocomplete_fields = ("task",)
