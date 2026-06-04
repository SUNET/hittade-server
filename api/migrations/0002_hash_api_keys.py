import hashlib

from django.db import migrations, models


def backfill_hashes(apps, schema_editor):
    """Populate prefix/key_hash from the existing plaintext key values.

    The old key was a high-entropy token; hashing it with the same SHA-256
    used at auth time means existing keys keep working after this migration.
    """
    APIKey = apps.get_model("api", "APIKey")
    for obj in APIKey.objects.all():
        raw = obj.key or ""
        obj.prefix = raw[:8]
        obj.key_hash = hashlib.sha256(raw.encode()).hexdigest()
        obj.save(update_fields=["prefix", "key_hash"])


def noop_reverse(apps, schema_editor):
    # Plaintext keys cannot be recovered from hashes; the key column is
    # restored empty by the reverse of RemoveField. Nothing to recompute.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("api", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="apikey",
            name="prefix",
            field=models.CharField(
                default="",
                editable=False,
                help_text="First characters of the key, shown for identification.",
                max_length=8,
            ),
            preserve_default=False,
        ),
        # Added non-unique first so existing rows can be backfilled before the
        # unique constraint is applied.
        migrations.AddField(
            model_name="apikey",
            name="key_hash",
            field=models.CharField(default="", editable=False, max_length=64),
            preserve_default=False,
        ),
        migrations.RunPython(backfill_hashes, noop_reverse),
        migrations.AlterField(
            model_name="apikey",
            name="key_hash",
            field=models.CharField(editable=False, max_length=64, unique=True),
        ),
        migrations.RemoveField(
            model_name="apikey",
            name="key",
        ),
    ]
