from django.contrib import admin

from .models import Project, Category, Activity, Settings, Invoice
from .forms import RevertBilledActivityForm

# Register your models here.

class ActivityInline(admin.TabularInline):
  model = Activity
  verbose_name_plural = 'Activities'
  extra = 0


class ActivityAdmin(admin.ModelAdmin):
  list_display = ('started_at', 'ended_at', 'project__customer', 'project', 'category', 'is_chargeable', 'billed', 'lexware_invoice_id')
  list_filter = ('project', 'category', 'is_chargeable', 'started_at', 'project__customer', 'billed')
  search_fields = ('project__title', 'category__title', 'notes', 'lexware_invoice_id')
  ordering = ('started_at',)
  readonly_fields = ('id', 'lexware_invoice_id', 'lexware_invoice_url')
  actions = ['mark_unbilled']

  def get_readonly_fields(self, request, obj=None):
    ro = list(self.readonly_fields)
    if obj and obj.billed:
      ro += [f.name for f in self.model._meta.fields if f.name not in self.readonly_fields]
    return ro

  def mark_unbilled(self, request, queryset):
    updated = queryset.update(billed=False, lexware_invoice_id=None, lexware_invoice_url=None)
    self.message_user(request, f"{updated} activities marked as unbilled.")
  mark_unbilled.short_description = "Mark selected activities as unbilled"

  class Meta:
    verbose_name_plural = 'Activities'


class CategoryAdmin(admin.ModelAdmin):
  list_display = ('title', 'description', 'is_chargeable', 'assigned_projects')
  list_filter = ('created_at', 'updated_at', 'projects')
  search_fields = ('title',)
  ordering = ('projects', 'title')

  class Meta:
    verbose_name_plural = 'Categories'

  @staticmethod
  def assigned_projects(obj):
    return obj.projects.count()


class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'customer', 'start_date', 'end_date', 'is_archived', 'duration', 'assigned_categories')
    list_filter = ('customer', 'start_date', 'end_date', 'is_archived')
    search_fields = ('id', 'title', 'customer__name')
    ordering = ('-start_date', 'customer')
    readonly_fields = ('duration', 'id', 'created_at', 'updated_at')

    @staticmethod
    def assigned_categories(obj):
        return obj.categories.count()


class SettingsAdmin(admin.ModelAdmin):
  list_display = ('user', 'updated_at')
  list_filter = ('updated_at',)
  search_fields = ('user__username',)
  ordering = ('user', 'updated_at')
  readonly_fields = ('updated_at',)


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('lexware_invoice_id', 'customer', 'created_at', 'total_amount', 'finalized')
    search_fields = ('lexware_invoice_id', 'customer__name')
    readonly_fields = ('lexware_invoice_id', 'lexware_invoice_url', 'created_at')
    list_filter = ('customer', 'finalized')


admin.site.register(Project, ProjectAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Activity, ActivityAdmin)
admin.site.register(Settings, SettingsAdmin)
admin.site.register(Invoice, InvoiceAdmin)
