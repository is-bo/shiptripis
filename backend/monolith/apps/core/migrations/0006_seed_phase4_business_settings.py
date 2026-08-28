"""Seed business settings version 4: the Phase 4 lifecycle policy.

Version 3 carried matching, pricing, ranking, reservation and payments.
Version 4 is version 3 plus `handover`, `cancellation`, `disputes`, `ratings`
and `boost`, activated in its place. Nothing in version 3 changes -- settings
revisions are immutable, so Phase 4 is a new revision rather than an edit, and
every Offer, Deal or PaymentOrder already pointing at version 3 keeps the
economics it agreed to.

The policy is written out in full rather than imported from the Phase 3
migration. A migration must keep working against the code it shipped with, so
each revision states its own complete value exactly as migration 0005 restated
the Phase 2 policy.

The seeded values are the specification's locked rules:

* 30-minute delivery-code safety buffer (`handover.delivery_code_buffer_seconds`)
* 48-hour payout protection, unchanged, still read from
  `payments.payout.protection_window_seconds` so there is one source of truth
  shared by the Phase 3 payout scheduler and the Phase 4 release gate
* 24-hour sender cancellation cutoff, 10% traveler compensation capped at EUR 15
* 14-day bidirectional rating review window with blind reveal
* ranking-only sender boost packages

Rollback re-activates version 3 rather than deleting version 4: economic
revisions are append-only once orders reference them through PROTECT. A
deployment rolled back to version 3 keeps taking payments and refuses Phase 4
behaviour with a fail-closed `phase4_policy_unavailable`.
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
    "timing_mode": "posting_deposit",
    "posting_deposit": {
        "percent_bps": 1_000,
        "min_eur_cents": 300,
        "max_eur_cents": 700,
        "expiry_grace_seconds": 0,
    },
    "providers": {
        "stripe_enabled": True,
        "chargily_enabled": True,
        "mock_enabled": False,
    },
    "chargily": {
        "eur_dzd_rate_micros": 150_000_000,
        "new_checkouts_enabled": True,
        "min_amount_dzd": 75,
    },
    "checkout": {"attempt_ttl_seconds": 3_600},
    "guest": {"link_ttl_seconds": 259_200},
    "payout": {
        # Phase 4 now enforces this window through the release gate; Phase 3
        # already scheduled against it. Unchanged from version 3 on purpose.
        "protection_window_seconds": 172_800,
        "auto_stripe_enabled": False,
    },
}

PHASE4_HANDOVER = {
    # Locked V1 rule: the delivery code is unavailable for exactly 30 minutes
    # after pickup confirmation -- to the sender, to the recipient's email and
    # to nobody else, because the traveler never has a retrieval path at all.
    "delivery_code_buffer_seconds": 1_800,
    # Eight Crockford base32 characters: 32**8 == 2**40 possibilities.
    "code_length": 8,
    "max_failed_attempts": 5,
    "attempt_lockout_seconds": 900,
    "max_lockouts": 3,
    "attempt_window_seconds": 3_600,
    "max_attempts_per_window": 12,
}

PHASE4_CANCELLATION = {
    # Sender cancels more than 24 hours before the agreed pickup: full refund.
    "sender_free_cutoff_seconds": 86_400,
    # Inside the cutoff: 10% of the traveler reward, capped at EUR 15.
    "sender_late_compensation_bps": 1_000,
    "sender_late_compensation_cap_eur_cents": 1_500,
    # The platform takes nothing from a late sender cancellation at launch. The
    # traveler is compensated and every remaining cent goes back to the sender.
    "sender_late_platform_fee_bps": 0,
}

PHASE4_DISPUTES = {
    "max_evidence_items": 20,
    "max_evidence_bytes": 26_214_400,
    "allowed_evidence_content_types": [
        "image/jpeg",
        "image/png",
        "image/webp",
        "video/mp4",
        "video/quicktime",
    ],
    # A partial split shares the money that is not returned to the sender
    # between the traveler and the platform in the originally agreed ratio.
    "partial_split_fee_mode": "proportional",
}

PHASE4_RATINGS = {
    "review_window_seconds": 1_209_600,
    "max_comment_length": 1_000,
    "allowed_tags": [
        "communication",
        "punctual",
        "careful_handling",
        "clear_instructions",
        "friendly",
        "late",
        "poor_communication",
        "damaged",
    ],
}

PHASE4_BOOST = {
    "enabled": True,
    "max_active_per_request": 3,
    "packages": [
        {
            "code": "boost_24h",
            "label": "24 hours",
            "duration_seconds": 86_400,
            "price_eur_cents": 199,
            "ranking_weight": 2,
        },
        {
            "code": "boost_72h",
            "label": "3 days",
            "duration_seconds": 259_200,
            "price_eur_cents": 449,
            "ranking_weight": 4,
        },
        {
            "code": "boost_7d",
            "label": "7 days",
            "duration_seconds": 604_800,
            "price_eur_cents": 899,
            "ranking_weight": 6,
        },
    ],
}

PHASE4_POLICY = {
    **PHASE2_POLICY,
    "payments": PHASE3_PAYMENTS,
    "handover": PHASE4_HANDOVER,
    "cancellation": PHASE4_CANCELLATION,
    "disputes": PHASE4_DISPUTES,
    "ratings": PHASE4_RATINGS,
    "boost": PHASE4_BOOST,
}


def seed_phase4_business_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    expected = {
        "canonical_currency": "EUR",
        "commission_rate_bps": 2_500,
        "pricing_version": "v1-lifecycle-1",
        "policy": PHASE4_POLICY,
    }
    settings_version = BusinessSettingsVersion.objects.filter(version=4).first()
    if settings_version is not None:
        mismatches = [
            field
            for field, expected_value in expected.items()
            if getattr(settings_version, field) != expected_value
        ]
        if mismatches:
            raise RuntimeError(
                "Business settings version 4 already exists with incompatible "
                f"immutable fields: {', '.join(mismatches)}. Reconcile it before "
                "applying the Phase 4 migration."
            )
    BusinessSettingsVersion.objects.filter(status="active").exclude(
        version=4
    ).update(status="retired")
    if settings_version is None:
        settings_version = BusinessSettingsVersion.objects.create(
            version=4,
            status="active",
            activated_at=timezone.now(),
            **expected,
        )
    if settings_version.status != "active":
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            status="active",
            activated_at=timezone.now(),
        )


def unseed_phase4_business_settings(apps, schema_editor):
    del schema_editor
    BusinessSettingsVersion = apps.get_model("core", "BusinessSettingsVersion")
    # Append-only: retire rather than delete, and hand activation back to the
    # Phase 3 revision so a rollback leaves exactly one active row and payments
    # keep working without any Phase 4 behaviour.
    BusinessSettingsVersion.objects.filter(version=4).update(status="retired")
    BusinessSettingsVersion.objects.filter(version=3).update(
        status="active",
        activated_at=timezone.now(),
    )


class Migration(migrations.Migration):
    dependencies = [("core", "0005_seed_phase3_payment_settings")]

    operations = [
        migrations.RunPython(
            seed_phase4_business_settings,
            unseed_phase4_business_settings,
        )
    ]
