"""Unproven legacy instructions never become executable through old routes."""

from django.db import migrations


def quarantine(apps, schema_editor):
    Payout = apps.get_model("finance", "Payout")
    Payout.objects.using(schema_editor.connection.alias).filter(
        snapshot_version=0,
    ).exclude(status__in=["paid", "cancelled"]).update(
        status="blocked",
        block_reason="legacy_instruction_required",
    )


class Migration(migrations.Migration):
    dependencies = [("finance", "0017_payout_relation_guards")]
    # Safety classification cannot be unwound into inferred permission to pay.
    operations = [migrations.RunPython(quarantine, migrations.RunPython.noop)]
