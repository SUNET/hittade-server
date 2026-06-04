from django.test import TestCase

from api.models import APIKey

# The API key is sent in this header (see api.views.ApiKeyAuth).
HEADER = "X-API-Key"


class ApiKeyAuthTests(TestCase):
    # /api/hosts now requires a valid API key.
    URL = "/api/hosts"

    @classmethod
    def setUpTestData(cls):
        cls.active, cls.active_raw = APIKey.generate(name="active key")
        cls.disabled, cls.disabled_raw = APIKey.generate(
            name="disabled key", active=False
        )

    def _get(self, key=None):
        headers = {HEADER: key} if key is not None else {}
        return self.client.get(self.URL, headers=headers)

    def test_missing_key_is_rejected(self):
        self.assertEqual(self._get().status_code, 401)

    def test_invalid_key_is_rejected(self):
        self.assertEqual(self._get("not-a-real-key").status_code, 401)

    def test_disabled_key_is_rejected(self):
        self.assertEqual(self._get(self.disabled_raw).status_code, 401)

    def test_valid_key_is_accepted(self):
        response = self._get(self.active_raw)
        self.assertEqual(response.status_code, 200)
        # /api/hosts is paginated; with no hosts the items list is empty.
        self.assertEqual(response.json()["items"], [])

    def test_valid_key_stamps_last_used(self):
        self.assertIsNone(self.active.last_used)
        self._get(self.active_raw)
        self.active.refresh_from_db()
        self.assertIsNotNone(self.active.last_used)

    def test_plaintext_is_not_stored(self):
        # The raw key must never be persisted: only its SHA-256 hash is.
        self.assertEqual(self.active.key_hash, APIKey.hash_key(self.active_raw))
        self.assertNotEqual(self.active.key_hash, self.active_raw)
        self.assertTrue(self.active_raw.startswith(self.active.prefix))
