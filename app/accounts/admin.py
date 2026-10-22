from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import ApiToken, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "customer", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = (*BaseUserAdmin.fieldsets, ("Rolle", {"fields": ("role", "customer")}))
    add_fieldsets = (*BaseUserAdmin.add_fieldsets, ("Rolle", {"fields": ("role", "customer")}))


@admin.register(ApiToken)
class ApiTokenAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "hint", "created_at", "last_used_at")
    readonly_fields = ("hint", "created_at", "last_used_at")
    fields = ("user", "name", *readonly_fields)

    def has_add_permission(self, request):
        # Keys are created in the account settings, where the key is shown once.
        return False
