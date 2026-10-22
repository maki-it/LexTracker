from django.contrib import admin

from billing.models import BillingAgreement, Invoice


@admin.register(BillingAgreement)
class BillingAgreementAdmin(admin.ModelAdmin):
    list_display = ("customer", "kind", "period", "included_hours", "fixed_price", "valid_from", "valid_until")
    list_filter = ("kind", "period")
    list_select_related = ("customer",)


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("customer", "period_start", "period_end", "total_net", "lexware_id", "created_at")
    list_select_related = ("customer",)
    readonly_fields = ("lexware_id",)
