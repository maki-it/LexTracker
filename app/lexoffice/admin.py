import asyncio

from asgiref.sync import sync_to_async
from django.contrib import admin, messages

from .utils import api_client, save_customer
from .models import Customer


@admin.action(description="Re-Sync selected customers from Lexoffice API")
async def sync_customers(modeladmin, request, queryset):
  """Sync the selected customers from Lexoffice API"""
  for customer in queryset:
    customer = await api_client.get_customers(customer.id)
    await save_customer(customer)
  await sync_to_async(modeladmin.message_user)(request, f"{len(queryset)} Customers synced successfully")


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
