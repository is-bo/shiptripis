from django.db import migrations
from django.utils import timezone


PHASE2_POLICY = {
    "canonical_currency": "EUR",
    "money_unit": "minor_units",
    "rounding": "integer_cents_explicit_ceiling",
    "matching": {
        "max_pickup_detour_meters": 15_000,
        "max_dropoff_detour_meters": 15_000,
        "max_total_added_distance_meters": 30_000,
        "max_total_added_duration_seconds": 3_600,
        "candidate_scan_limit": 200,
        "result_limit": 50,
        "spatial_fallback_enabled": True,
    },
    "pricing": {
        "volumetric_divisor": 5_000,
        "weight_increment_kg": "0.5",
        "weight_rate_cents_per_kg": 250,
        "global_floor_cents": 700,
        "recommendation_multiplier_bps": 12_000,
        "reward_rounding_increment_cents": 50,
        "detour_adjustment_cents_per_km": 25,
        "distance_bands": [
            {"max_meters": 100_000, "base_cents": 400},
            {"max_meters": 300_000, "base_cents": 600},
            {"max_meters": 750_000, "base_cents": 900},
            {"max_meters": 1_500_000, "base_cents": 1_200},
            {"max_meters": 3_000_000, "base_cents": 1_600},
            {"max_meters": 5_000_000, "base_cents": 2_000},
            {"max_meters": None, "base_cents": 2_400},
        ],
        "urgency_adjustments": [
            {"max_slack_minutes": 1_440, "cents": 300},
            {"max_slack_minutes": 4_320, "cents": 150},
        ],
    },
    "ranking": {
        "weights": {
            "route_fit": 30,
            "detour": 25,
            "time_fit": 20,
            "verification": 10,
            "freshness": 5,
            "neutral_reputation": 10,
        },
        "boost_points_per_weight": 25,
        "max_boost_points": 200,
    },
    "reservation": {"payment_grace_seconds": 3_600},
}


def seed_phase2_business_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    expected = {
        "canonical_currency": "EUR",
        "commission_rate_bps": 2_500,
        "pricing_version": "v1-matching-pricing-1",
        "policy": PHASE2_POLICY,
    }
    settings_version = BusinessSettingsVersion.objects.filter(version=2).first()
    if settings_version is not None:
        mismatches = [
            field
            for field, expected_value in expected.items()
            if getattr(settings_version, field) != expected_value
        ]
        if mismatches:
            raise RuntimeError(
                "Business settings version 2 already exists with incompatible "
                f"immutable fields: {', '.join(mismatches)}. Reconcile it before "
                "applying the Phase 2 migration."
            )
    BusinessSettingsVersion.objects.filter(status="active").exclude(
        version=2
    ).update(status="retired")
    if settings_version is None:
        settings_version = BusinessSettingsVersion.objects.create(
            version=2,
            status="active",
            activated_at=timezone.now(),
            **expected,
        )
    if settings_version.status != "active":
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            status="active",
            activated_at=timezone.now(),
        )


def unseed_phase2_business_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    # Economic revisions are append-only once offers or deals can reference
    # them through PROTECT foreign keys. Rollback changes activation state but
    # never deletes an auditable pricing revision.
    BusinessSettingsVersion.objects.filter(version=2).update(status="retired")
    BusinessSettingsVersion.objects.filter(version=1).update(
        status="active",
        activated_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0003_seed_v1_business_settings")]

    operations = [
        migrations.RunPython(
            seed_phase2_business_settings,
            unseed_phase2_business_settings,
        )
    ]
