import hashlib
import secrets

from django.db import models


def generate_key() -> str:
    """Kept for the historical 0001_initial migration, which references it as
    the default of the old plaintext ``key`` column. Not used by current code.
    """
    return secrets.token_urlsafe(32)


def hash_key(raw: str) -> str:
    """Hash a raw API key for storage/lookup.

    API keys are high-entropy random tokens, so a fast SHA-256 is sufficient
    (unlike low-entropy passwords, which need a slow KDF).
    """
    return hashlib.sha256(raw.encode()).hexdigest()


class APIKey(models.Model):
    """A key that grants access to the JSON API.

    Only the SHA-256 hash of the key is stored. The plaintext key is shown
    once, at creation time, and cannot be recovered afterwards.
    """

    name = models.CharField(max_length=100, help_text="Who/what this key is for.")
    prefix = models.CharField(
        max_length=8,
        editable=False,
        help_text="First characters of the key, shown for identification.",
    )
    key_hash = models.CharField(max_length=64, unique=True, editable=False)
    active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        state = "active" if self.active else "disabled"
        return f"{self.name} ({self.prefix}..., {state})"

    @staticmethod
    def hash_key(raw: str) -> str:
        return hash_key(raw)

    def set_new_key(self) -> str:
        """Generate a fresh key, set prefix/hash on this instance, return the plaintext."""
        raw = secrets.token_urlsafe(32)
        self.prefix = raw[:8]
        self.key_hash = hash_key(raw)
        return raw

    @classmethod
    def generate(cls, name: str, **kwargs) -> tuple["APIKey", str]:
        """Create and save a key, returning (instance, plaintext).

        The plaintext is only available from this return value; only its
        hash is persisted.
        """
        obj = cls(name=name, **kwargs)
        raw = obj.set_new_key()
        obj.save()
        return obj, raw
