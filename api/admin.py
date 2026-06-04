from django.contrib import admin

from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "active", "created", "last_used")
    list_filter = ("active",)
    search_fields = ("name", "key")
    readonly_fields = ("key", "created", "last_used")
