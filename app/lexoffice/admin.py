import asyncio

from asgiref.sync import sync_to_async, async_to_sync
from django.contrib import admin

from .utils import api_client, save_customer
from .models import Customer
from .views import sync_customer

@admin.action(description="Sync selected customers from Lexoffice API")
async def sync_customers(modeladmin, request, queryset):
  """Sync the selected customers from Lexoffice API"""
  for customer in queryset:
    customer = await sync_to_async(api_client.get_customers)(customer.id)
    await sync_to_async(save_customer)(customer)
  #modeladmin.message_user(request, f"{len(queryset)} Customers synced successfully")

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
