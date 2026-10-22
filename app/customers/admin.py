from django.contrib import admin

from customers.models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ("name", "customer_number", "email", "default_hourly_rate", "is_archived", "lexware_synced_at")
    list_filter = ("is_archived",)
    search_fields = ("name", "customer_number", "email")
    readonly_fields = ("lexware_id", "lexware_version", "lexware_synced_at", "created_at", "updated_at")
