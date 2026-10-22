from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from accounts.models import User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("username", "email", "first_name", "last_name", "role", "customer", "is_active")
    list_filter = ("role", "is_active", "is_staff")
    fieldsets = (*BaseUserAdmin.fieldsets, ("Rolle", {"fields": ("role", "customer")}))
    add_fieldsets = (*BaseUserAdmin.add_fieldsets, ("Rolle", {"fields": ("role", "customer")}))
