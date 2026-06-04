import secrets

from django.db import models


def generate_key() -> str:
    return secrets.token_urlsafe(32)


class APIKey(models.Model):
    """A key that grants access to the JSON API.

    Create/disable keys from the Django admin. The key value is generated
    automatically and shown in the admin so it can be copied once.
    """

    name = models.CharField(max_length=100, help_text="Who/what this key is for.")
    key = models.CharField(
        max_length=64, unique=True, db_index=True, editable=False, default=generate_key
    )
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        state = "active" if self.active else "disabled"
        return f"{self.name} ({state})"
