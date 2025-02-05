from django.contrib import admin

from .models import Project, Category, Activity

# Register your models here.

class CategoryInline(admin.TabularInline):
  model = Category.projects.through
  verbose_name_plural = 'Categories'
  extra = 0


class ActivityInline(admin.TabularInline):
  model = Activity
  verbose_name_plural = 'Activities'
  extra = 0


class ActivityAdmin(admin.ModelAdmin):
  list_display = ('started_at', 'ended_at', 'project__customer', 'project', 'category', 'is_chargeable')
  list_filter = ('project', 'category', 'is_chargeable', 'started_at', 'project__customer')
  search_fields = ('project__title', 'category__title', 'notes')
  ordering = ('started_at',)
  readonly_fields = ('id',)

  class Meta:
    verbose_name_plural = 'Activities'


class CategoryAdmin(admin.ModelAdmin):
  list_display = ('title', 'description', 'assigned_projects')
  list_filter = ('created_at', 'updated_at', 'projects')
  search_fields = ('title',)
  ordering = ('projects', 'title')
  inlines = [CategoryInline]

  class Meta:
    verbose_name_plural = 'Categories'

  @staticmethod
  def assigned_projects(obj):
    return obj.projects.count()


class ProjectAdmin(admin.ModelAdmin):
    list_display = ('title', 'customer', 'start_date', 'end_date', 'is_archived')
    list_filter = ('customer', 'start_date', 'end_date', 'is_archived')
    search_fields = ('id', 'title', 'customer__name')
    ordering = ('-start_date', 'customer')
    readonly_fields = ('duration', 'id', 'created_at', 'updated_at')
    inlines = [ActivityInline, CategoryInline]

admin.site.register(Project, ProjectAdmin)
admin.site.register(Category, CategoryAdmin)
admin.site.register(Activity, ActivityAdmin)

