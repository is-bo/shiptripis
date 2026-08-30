"""Activate an immutable pre-launch policy with every payment rail disabled.

The historical Phase 4 seed intentionally described the complete provider
contract, but enabled Stripe and Chargily before external credentials and
provider verification existed. A fresh production database must not advertise
either rail as available during pre-launch. Version 5 copies the complete
locked lifecycle policy and changes only the provider availability switches.
"""

from __future__ import annotations

from copy import deepcopy

from django.db import migrations
from django.utils import timezone


def _expected_from_phase4(BusinessSettingsVersion):
    phase4 = BusinessSettingsVersion.objects.get(version=4)
    policy = deepcopy(phase4.policy)
    payments = policy["payments"]
    payments["providers"]["stripe_enabled"] = False
    payments["providers"]["chargily_enabled"] = False
    payments["providers"]["mock_enabled"] = False
    payments["chargily"]["new_checkouts_enabled"] = False
    payments["payout"]["auto_stripe_enabled"] = False
    return {
        "canonical_currency": phase4.canonical_currency,
        "commission_rate_bps": phase4.commission_rate_bps,
        "pricing_version": "v1-lifecycle-1-prelaunch",
        "policy": policy,
    }


def seed_prelaunch_provider_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    expected = _expected_from_phase4(BusinessSettingsVersion)
    settings_version = BusinessSettingsVersion.objects.filter(version=5).first()
    if settings_version is not None:
        mismatches = [
            field
            for field, expected_value in expected.items()
            if getattr(settings_version, field) != expected_value
        ]
        if mismatches:
            raise RuntimeError(
                "Business settings version 5 already exists with incompatible "
                f"immutable fields: {', '.join(mismatches)}. Reconcile it before "
                "applying the pre-launch provider migration."
            )

    BusinessSettingsVersion.objects.filter(status="active").exclude(version=5).update(
        status="retired"
    )
    if settings_version is None:
        settings_version = BusinessSettingsVersion.objects.create(
            version=5,
            status="active",
            activated_at=timezone.now(),
            **expected,
        )
    elif settings_version.status != "active":
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            status="active",
            activated_at=timezone.now(),
        )


def unseed_prelaunch_provider_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    BusinessSettingsVersion.objects.filter(version=5).update(status="retired")
    BusinessSettingsVersion.objects.filter(version=4).update(
        status="active",
        activated_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0007_seed_phase4_admin_groups")]

    operations = [
        migrations.RunPython(
            seed_prelaunch_provider_settings,
            unseed_prelaunch_provider_settings,
        )
    ]
