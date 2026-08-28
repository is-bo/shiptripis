from datetime import timedelta

from django.db import migrations, models


def backfill_pending_expiry(apps, schema_editor):
    del schema_editor
    Allocation = apps.get_model("deals", "DealLegAllocation")
    for allocation in Allocation.objects.filter(
        status="pending_payment",
        expires_at__isnull=True,
    ).iterator(chunk_size=500):
        allocation.expires_at = allocation.reserved_at + timedelta(hours=1)
        allocation.save(update_fields=["expires_at"])


def clear_backfilled_expiry(apps, schema_editor):
    del schema_editor
    Allocation = apps.get_model("deals", "DealLegAllocation")
    Allocation.objects.filter(status="pending_payment").update(expires_at=None)


class Migration(migrations.Migration):
    dependencies = [
        ("deals", "0002_remove_dealtermssnapshot_deals_terms_new_currency_eur_and_more")
    ]

    operations = [
        migrations.AddField(
            model_name="deallegallocation",
            name="expires_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_pending_expiry, clear_backfilled_expiry),
        migrations.AddField(
            model_name="deallegallocation",
            name="release_reason",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddIndex(
            model_name="deallegallocation",
            index=models.Index(
                fields=["status", "expires_at"],
                name="deals_allocation_expiry_idx",
            ),
        ),
    ]
