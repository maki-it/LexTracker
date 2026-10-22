from django.contrib import admin

from projects.models import Project, Task


class TaskInline(admin.TabularInline):
    model = Task
    extra = 0
    fields = ("name", "status", "is_billable", "hourly_rate", "estimated_hours")


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ("name", "customer", "status", "hourly_rate", "budget_hours", "start_date", "end_date")
    list_filter = ("status", "customer")
    search_fields = ("name", "customer__name")
    list_select_related = ("customer",)
    inlines = [TaskInline]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "status", "is_billable", "hourly_rate", "estimated_hours")
    list_filter = ("status", "is_billable", "project__customer")
    search_fields = ("name", "project__name")
    list_select_related = ("project", "project__customer")
