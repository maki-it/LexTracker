from asgiref.sync import async_to_sync
from django.contrib import admin, messages
from django.utils.translation import ngettext

from .utils import api_client, save_customer
from .models import Customer


@admin.action(description="Re-Sync selected customers from Lexoffice API")
def sync_customers(modeladmin, request, queryset):
  """Sync the selected customers from Lexoffice API"""
  for customer in queryset:
    customer = async_to_sync(api_client.get_customers)(customer.id)
    async_to_sync(save_customer)(customer)
  modeladmin.message_user(
    request,
    ngettext(
      '%d customer synced.',
      '%d customers synced.',
      len(queryset),
    ) % len(queryset), messages.SUCCESS)


class CustomerAdmin(admin.ModelAdmin):
  list_display = ('number', 'name', 'type', 'is_archived')
  list_filter = ('type', 'is_archived', 'created_at', 'updated_at')
  search_fields = ('name', 'number')
  ordering = ('number',)
  readonly_fields = ('version', 'created_at', 'updated_at', 'id', 'organization_id',)

  actions = [sync_customers]

  def has_change_permission(self, request, obj=None):
    return False

  def has_add_permission(self, request, obj=None):
    return False

admin.site.register(Customer, CustomerAdmin)
