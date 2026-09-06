"""Build the keyset-history index without blocking PostgreSQL chat writes."""

from django.db import migrations, models


def _index():
    return models.Index(fields=("match", "id"), name="chat_match_id_idx")


def add_index(apps, schema_editor):
    options = {"concurrently": True} if schema_editor.connection.vendor == "postgresql" else {}
    schema_editor.add_index(apps.get_model("chat", "ChatMessage"), _index(), **options)


def remove_index(apps, schema_editor):
    options = {"concurrently": True} if schema_editor.connection.vendor == "postgresql" else {}
    schema_editor.remove_index(apps.get_model("chat", "ChatMessage"), _index(), **options)


class Migration(migrations.Migration):
    atomic = False
    dependencies = [("chat", "0001_initial")]
    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunPython(add_index, remove_index)],
            state_operations=[migrations.AddIndex(model_name="chatmessage", index=_index())],
        )
    ]
