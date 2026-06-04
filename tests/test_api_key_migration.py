import hashlib

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

LEGACY_KEY = "legacy-plaintext-key-abcdef0123456789"


class ApiKeyBackfillMigrationTests(TransactionTestCase):
    """Exercise the upgrade path, not just fresh-DB creation.

    Simulates a database that already applied 0001 (plaintext `key`),
    then runs 0002 and checks prefix/key_hash are backfilled so existing
    keys keep authenticating.
    """

    migrate_from = [("api", "0001_initial")]
    migrate_to = [("api", "0002_hash_api_keys")]

    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)  # roll back to the old schema

    def tearDown(self):
        # Leave the DB at the latest migration for the rest of the suite.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)

    def test_existing_plaintext_key_is_backfilled(self):
        old_apps = MigrationExecutor(connection).loader.project_state(
            self.migrate_from
        ).apps
        OldAPIKey = old_apps.get_model("api", "APIKey")
        obj = OldAPIKey.objects.create(name="legacy", key=LEGACY_KEY)

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.migrate_to)  # run the data migration

        new_apps = executor.loader.project_state(self.migrate_to).apps
        NewAPIKey = new_apps.get_model("api", "APIKey")
        migrated = NewAPIKey.objects.get(pk=obj.pk)

        self.assertEqual(
            migrated.key_hash, hashlib.sha256(LEGACY_KEY.encode()).hexdigest()
        )
        self.assertEqual(migrated.prefix, LEGACY_KEY[:8])
        # The plaintext `key` column is gone after the upgrade.
        self.assertFalse(hasattr(migrated, "key"))
