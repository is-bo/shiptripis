from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase
from django.core.exceptions import ValidationError

from apps.core.business_settings import (
    activate_business_settings,
    calculate_offer_economics,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion


class BusinessSettingsTests(TestCase):
    def test_the_active_revision_is_the_latest_seeded_one(self):
        """Each phase adds a revision; exactly one is ever active."""

        active = get_active_business_settings()
        latest = BusinessSettingsVersion.objects.order_by("-version").first()

        assert active.pk == latest.pk
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

    def test_seeded_revision_and_minor_unit_rounding(self):
        active = get_active_business_settings()

        assert active.version == 6
        assert active.pricing_version == "v1-boost-economics-1"
        assert active.policy["boost"]["minimum_amount_eur_cents"] == 500
        assert active.policy["boost"]["traveler_share_bps"] == 7_500
        assert active.canonical_currency == "EUR"
        assert active.policy["payments"]["providers"] == {
            "stripe_enabled": False,
            "chargily_enabled": False,
            "mock_enabled": False,
        }
        assert active.policy["payments"]["chargily"]["new_checkouts_enabled"] is False
        assert calculate_offer_economics(101, active) == {
            "traveler_reward_minor": 101,
            "commission_rate_bps": 2500,
            "platform_fee_minor": 26,
            "sender_total_minor": 127,
        }

    def test_activation_retires_previous_revision(self):
        previous = get_active_business_settings()
        second = BusinessSettingsVersion.objects.create(
            version=7,
            commission_rate_bps=1800,
            pricing_version="v1.1",
            policy={"experiment": "lower_fee"},
        )

        activated = activate_business_settings(second)

        assert activated.status == BusinessSettingsVersion.Status.ACTIVE
        assert get_active_business_settings().pk == second.pk
        assert BusinessSettingsVersion.objects.get(pk=previous.pk).status == (
            BusinessSettingsVersion.Status.RETIRED
        )

    def test_boost_seed_reverse_never_clobbers_a_later_operator_revision(self):
        economics = import_module("apps.core.migrations.0009_seed_boost_economics")
        seeded = get_active_business_settings()
        later = BusinessSettingsVersion.objects.create(
            version=seeded.version + 1,
            commission_rate_bps=seeded.commission_rate_bps,
            pricing_version="operator-boost-adjustment",
            policy=seeded.policy,
        )
        activate_business_settings(later)

        economics.unseed_boost_economics(django_apps, None)

        assert get_active_business_settings().pk == later.pk
        assert BusinessSettingsVersion.objects.get(pk=seeded.pk).status == (
            BusinessSettingsVersion.Status.RETIRED
        )

    def test_revisions_are_append_only(self):
        active = get_active_business_settings()

        with self.assertRaises(ValidationError):
            active.delete()

        assert BusinessSettingsVersion.objects.filter(pk=active.pk).exists()

    def test_phase2_seed_reverse_forward_roundtrip_is_non_destructive(self):
        prelaunch = import_module(
            "apps.core.migrations.0008_seed_prelaunch_provider_settings"
        )
        economics = import_module("apps.core.migrations.0009_seed_boost_economics")
        phase4 = import_module(
            "apps.core.migrations.0006_seed_phase4_business_settings"
        )
        phase3 = import_module("apps.core.migrations.0005_seed_phase3_payment_settings")
        migration = import_module(
            "apps.core.migrations.0004_seed_phase2_business_settings"
        )

        # Migrations unwind in order: pre-launch, Phase 4, then Phase 3.
        economics.unseed_boost_economics(django_apps, None)
        prelaunch.unseed_prelaunch_provider_settings(django_apps, None)
        phase4.unseed_phase4_business_settings(django_apps, None)
        phase3.unseed_phase3_payment_settings(django_apps, None)
        migration.unseed_phase2_business_settings(django_apps, None)
        assert BusinessSettingsVersion.objects.get(version=1).status == (
            BusinessSettingsVersion.Status.ACTIVE
        )
        assert BusinessSettingsVersion.objects.get(version=2).status == (
            BusinessSettingsVersion.Status.RETIRED
        )

        migration.seed_phase2_business_settings(django_apps, None)
        assert BusinessSettingsVersion.objects.get(version=2).status == (
            BusinessSettingsVersion.Status.ACTIVE
        )
        assert BusinessSettingsVersion.objects.get(version=1).status == (
            BusinessSettingsVersion.Status.RETIRED
        )

        phase3.seed_phase3_payment_settings(django_apps, None)
        assert BusinessSettingsVersion.objects.get(version=3).status == (
            BusinessSettingsVersion.Status.ACTIVE
        )

        phase4.seed_phase4_business_settings(django_apps, None)
        prelaunch.seed_prelaunch_provider_settings(django_apps, None)
        economics.seed_boost_economics(django_apps, None)
        assert get_active_business_settings().version == 7

    def test_phase3_seed_reverse_forward_roundtrip_is_non_destructive(self):
        """Rolling the payment revision back hands activation to Phase 2."""

        prelaunch = import_module(
            "apps.core.migrations.0008_seed_prelaunch_provider_settings"
        )
        economics = import_module("apps.core.migrations.0009_seed_boost_economics")
        phase4 = import_module(
            "apps.core.migrations.0006_seed_phase4_business_settings"
        )
        phase3 = import_module("apps.core.migrations.0005_seed_phase3_payment_settings")

        economics.unseed_boost_economics(django_apps, None)
        prelaunch.unseed_prelaunch_provider_settings(django_apps, None)
        phase4.unseed_phase4_business_settings(django_apps, None)
        phase3.unseed_phase3_payment_settings(django_apps, None)

        assert BusinessSettingsVersion.objects.get(version=2).status == (
            BusinessSettingsVersion.Status.ACTIVE
        )
        # The revision is retired, never deleted: Offers and Orders point at it.
        assert BusinessSettingsVersion.objects.get(version=3).status == (
            BusinessSettingsVersion.Status.RETIRED
        )
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

        phase3.seed_phase3_payment_settings(django_apps, None)

        assert get_active_business_settings().version == 3
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

        phase4.seed_phase4_business_settings(django_apps, None)
        prelaunch.seed_prelaunch_provider_settings(django_apps, None)
        economics.seed_boost_economics(django_apps, None)
        assert get_active_business_settings().version == 7

    def test_phase3_seed_rejects_a_conflicting_existing_version_three(self):
        phase3 = import_module("apps.core.migrations.0005_seed_phase3_payment_settings")
        BusinessSettingsVersion.objects.filter(version=3).update(
            pricing_version="unrelated-production-v3"
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "incompatible immutable fields: pricing_version",
        ):
            phase3.seed_phase3_payment_settings(django_apps, None)

    def test_phase2_seed_rejects_a_conflicting_existing_version_two(self):
        migration = import_module(
            "apps.core.migrations.0004_seed_phase2_business_settings"
        )
        BusinessSettingsVersion.objects.filter(version=2).update(
            pricing_version="unrelated-production-v2"
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "incompatible immutable fields: pricing_version",
        ):
            migration.seed_phase2_business_settings(django_apps, None)

    def test_phase4_seed_reverse_forward_roundtrip_is_non_destructive(self):
        """Rolling the lifecycle revision back hands activation to Phase 3.

        That is the degradation Phase 4 is designed for: an older revision can
        still take payments, and every Phase 4 endpoint fails closed until a
        revision carrying the lifecycle policy is active again.
        """

        prelaunch = import_module(
            "apps.core.migrations.0008_seed_prelaunch_provider_settings"
        )
        economics = import_module("apps.core.migrations.0009_seed_boost_economics")
        phase4 = import_module(
            "apps.core.migrations.0006_seed_phase4_business_settings"
        )

        economics.unseed_boost_economics(django_apps, None)
        prelaunch.unseed_prelaunch_provider_settings(django_apps, None)
        phase4.unseed_phase4_business_settings(django_apps, None)

        assert get_active_business_settings().version == 3
        # Retired, never deleted: Deals and BoostPurchases point at it.
        assert BusinessSettingsVersion.objects.get(version=4).status == (
            BusinessSettingsVersion.Status.RETIRED
        )
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

        phase4.seed_phase4_business_settings(django_apps, None)
        prelaunch.seed_prelaunch_provider_settings(django_apps, None)
        economics.seed_boost_economics(django_apps, None)

        assert get_active_business_settings().version == 7
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

    def test_phase4_seed_rejects_a_conflicting_existing_version_four(self):
        phase4 = import_module(
            "apps.core.migrations.0006_seed_phase4_business_settings"
        )
        BusinessSettingsVersion.objects.filter(version=4).update(
            pricing_version="unrelated-production-v4"
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "incompatible immutable fields: pricing_version",
        ):
            phase4.seed_phase4_business_settings(django_apps, None)

    def test_prelaunch_seed_reverse_forward_roundtrip_is_non_destructive(self):
        prelaunch = import_module(
            "apps.core.migrations.0008_seed_prelaunch_provider_settings"
        )
        economics = import_module("apps.core.migrations.0009_seed_boost_economics")

        economics.unseed_boost_economics(django_apps, None)
        prelaunch.unseed_prelaunch_provider_settings(django_apps, None)
        assert get_active_business_settings().version == 4
        assert BusinessSettingsVersion.objects.get(version=5).status == (
            BusinessSettingsVersion.Status.RETIRED
        )

        prelaunch.seed_prelaunch_provider_settings(django_apps, None)
        economics.seed_boost_economics(django_apps, None)
        assert get_active_business_settings().version == 7
        assert BusinessSettingsVersion.objects.filter(status="active").count() == 1

    def test_prelaunch_seed_rejects_a_conflicting_existing_version_five(self):
        prelaunch = import_module(
            "apps.core.migrations.0008_seed_prelaunch_provider_settings"
        )
        BusinessSettingsVersion.objects.filter(version=5).update(
            pricing_version="unrelated-production-v5"
        )

        with self.assertRaisesMessage(
            RuntimeError,
            "incompatible immutable fields: pricing_version",
        ):
            prelaunch.seed_prelaunch_provider_settings(django_apps, None)
