"""Seed business settings version 3: the Phase 3 payment policy.

Version 2 carried matching, pricing, ranking and reservation. Version 3 is
version 2 plus a `payments` object, activated in its place. Nothing in version
2 changes — settings revisions are immutable, so Phase 3 is a new revision
rather than an edit, and every Offer or Deal already pointing at version 2
keeps the economics it agreed to.

The seeded values are the specification's recommendation:

* `timing_mode = posting_deposit` — the intended V1 default
* `deposit = clamp(10% of the recommended sender total, EUR 3, EUR 7)`
* both real providers enabled, mock explicitly off
* `eur_dzd_rate_micros` is a placeholder that an operator must set before
  Chargily is used for real money; it is stored at micro precision so an
  attempt's FX snapshot is exactly reproducible

Rollback re-activates version 2 rather than deleting version 3: economic
revisions are append-only once orders reference them through PROTECT.
"""

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
        # These maxima must remain a subset of
        # `apps.matching.public_contract.PUBLIC_DISTANCE_BAND_MAXIMA`, or the
        # published `distance_band_base_cents` would resolve a carried distance
        # more finely than the privacy band admits. Activation refuses a
        # revision that breaks it.
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

PHASE3_PAYMENTS = {
    # Intended V1 setting. `after_acceptance` remains supported so the platform
    # can be switched without a code change.
    "timing_mode": "posting_deposit",
    "posting_deposit": {
        "percent_bps": 1_000,  # 10%
        "min_eur_cents": 300,  # EUR 3.00
        "max_eur_cents": 700,  # EUR 7.00
        "expiry_grace_seconds": 0,
    },
    "providers": {
        "stripe_enabled": True,
        "chargily_enabled": True,
        # Never true in a deployment that handles real money. The provider
        # registry also requires PAYMENTS_ALLOW_MOCK_PROVIDER, and production
        # settings refuse to boot with that set.
        "mock_enabled": False,
    },
    "chargily": {
        # PLACEHOLDER. An operator must set the real rate through a new
        # settings revision before Chargily takes live money. Stored as
        # DZD-per-EUR x 1_000_000, so 150.000000 DZD = EUR 1.
        "eur_dzd_rate_micros": 150_000_000,
        # The incident switch: stops new checkouts while webhooks, refunds and
        # reconciliation keep working for money already in flight.
        "new_checkouts_enabled": True,
        "min_amount_dzd": 75,
    },
    "checkout": {"attempt_ttl_seconds": 3_600},
    "guest": {"link_ttl_seconds": 259_200},  # 72 hours
    "payout": {
        # Phase 4 enforces this window. Phase 3 only schedules against it.
        "protection_window_seconds": 172_800,  # 48 hours
        # Automatic Stripe transfers stay off until a real platform capability
        # is verified. Manual payout is the safe default.
        "auto_stripe_enabled": False,
    },
}

PHASE3_POLICY = {**PHASE2_POLICY, "payments": PHASE3_PAYMENTS}


def seed_phase3_payment_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    expected = {
        "canonical_currency": "EUR",
        "commission_rate_bps": 2_500,
        "pricing_version": "v1-payments-1",
        "policy": PHASE3_POLICY,
    }
    settings_version = BusinessSettingsVersion.objects.filter(version=3).first()
    if settings_version is not None:
        mismatches = [
            field
            for field, expected_value in expected.items()
            if getattr(settings_version, field) != expected_value
        ]
        if mismatches:
            raise RuntimeError(
                "Business settings version 3 already exists with incompatible "
                f"immutable fields: {', '.join(mismatches)}. Reconcile it before "
                "applying the Phase 3 migration."
            )
    BusinessSettingsVersion.objects.filter(status="active").exclude(
        version=3
    ).update(status="retired")
    if settings_version is None:
        settings_version = BusinessSettingsVersion.objects.create(
            version=3,
            status="active",
            activated_at=timezone.now(),
            **expected,
        )
    if settings_version.status != "active":
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            status="active",
            activated_at=timezone.now(),
        )


def unseed_phase3_payment_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    # Append-only: retire rather than delete, and hand activation back to the
    # Phase 2 revision so a rollback leaves exactly one active row.
    BusinessSettingsVersion.objects.filter(version=3).update(status="retired")
    BusinessSettingsVersion.objects.filter(version=2).update(
        status="active",
        activated_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0004_seed_phase2_business_settings")]

    operations = [
        migrations.RunPython(
            seed_phase3_payment_settings,
            unseed_phase3_payment_settings,
        )
    ]
