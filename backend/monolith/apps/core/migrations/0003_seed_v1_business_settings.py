from django.db import migrations
from django.utils import timezone


def seed_v1_business_settings(apps, schema_editor):
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    BusinessSettingsVersion.objects.create(
        version=1,
        status="active",
        canonical_currency="EUR",
        commission_rate_bps=2500,
        pricing_version="v1",
        policy={
            "canonical_currency": "EUR",
            "money_unit": "minor_units",
            "rounding": "ceil_platform_fee_to_cent",
        },
        activated_at=timezone.now(),
    )


def unseed_v1_business_settings(apps, schema_editor):
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    BusinessSettingsVersion.objects.filter(version=1).delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0002_businesssettingsversion")]

    operations = [
        migrations.RunPython(
            seed_v1_business_settings,
            unseed_v1_business_settings,
        )
    ]
