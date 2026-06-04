from django.contrib import admin, messages

from .models import APIKey


@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ("name", "prefix", "active", "created", "last_used")
    list_filter = ("active",)
    search_fields = ("name", "prefix")
    readonly_fields = ("prefix", "created", "last_used")

    def get_fields(self, request, obj=None):
        # On the add form there is no key yet: only ask for name + active.
        if obj is None:
            return ("name", "active")
        return ("name", "prefix", "active", "created", "last_used")

    def save_model(self, request, obj, form, change):
        if change:
            obj.save()
            return
        # Creating: generate the key, store only its hash, and show the
        # plaintext once -- it cannot be retrieved again.
        raw = obj.set_new_key()
        obj.save()
        self.message_user(
            request,
            f"API key for '{obj.name}' created. Copy it now — it will not "
            f"be shown again: {raw}",
            level=messages.WARNING,
        )
