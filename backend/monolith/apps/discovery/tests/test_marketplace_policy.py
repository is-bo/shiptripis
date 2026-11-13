"""L2A: the marketplace policy reader, its save-time validation and its admin form."""

from __future__ import annotations

from copy import deepcopy

from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.admin_panel.models import AdminAuditLog
from apps.admin_panel.ops_serializers import AdminSettingsCreateSerializer
from apps.admin_panel.permissions import assign_admin_roles
from apps.core.marketplace_policy import (
    InvalidMarketplacePolicy,
    MarketplacePolicy,
    marketplace_policy,
)
from apps.core.models import BusinessSettingsVersion

from .support import STATIC_STORES


class DefaultsTests(SimpleTestCase):
    def test_a_missing_section_means_the_spec_defaults(self):
        policy = MarketplacePolicy.from_section(None)

        self.assertTrue(policy.discovery.listings_enabled)
        self.assertTrue(policy.discovery.profiles_enabled)
        self.assertEqual(policy.discovery.interest_daily_cap, 10)
        # Sea legs ship off; everything else ships on.
        self.assertFalse(policy.sea_legs_enabled)
        self.assertTrue(policy.traveler_pricing.enabled)
        self.assertEqual(policy.traveler_pricing.max_price_per_kg_eur_cents, 10_000)
        self.assertEqual(policy.traveler_pricing.max_min_price_eur_cents, 50_000)
        self.assertTrue(policy.reminders.enabled)
        self.assertEqual(
            (
                policy.reminders.depart_after_minutes,
                policy.reminders.arrive_after_minutes,
                policy.reminders.repeat_after_minutes,
                policy.reminders.max_repeats,
            ),
            (30, 60, 180, 2),
        )
        self.assertEqual(policy.route_change.material_shift_minutes, 360)

    def test_an_empty_section_and_an_empty_sub_section_are_the_defaults_too(self):
        self.assertEqual(
            MarketplacePolicy.from_section({}),
            MarketplacePolicy.from_section({"discovery": {}, "reminders": {}}),
        )

    def test_a_partial_section_keeps_the_defaults_it_does_not_name(self):
        policy = MarketplacePolicy.from_section({"discovery": {"profiles_enabled": False}})

        self.assertFalse(policy.discovery.profiles_enabled)
        self.assertTrue(policy.discovery.listings_enabled)

    def test_the_policy_is_frozen(self):
        policy = MarketplacePolicy.from_section(None)
        with self.assertRaises(AttributeError):
            policy.sea_legs_enabled = True  # type: ignore[misc]


class RefusalTests(SimpleTestCase):
    def assertRefused(self, section):
        with self.assertRaises(InvalidMarketplacePolicy):
            MarketplacePolicy.from_section(section)

    def test_an_unknown_top_level_key_is_refused(self):
        self.assertRefused({"sea_leg_enabled": True})

    def test_an_unknown_nested_key_is_refused(self):
        self.assertRefused({"discovery": {"listing_enabled": False}})

    def test_a_section_that_is_not_an_object_is_refused(self):
        self.assertRefused([])
        self.assertRefused({"discovery": True})

    def test_a_switch_must_be_a_real_boolean(self):
        self.assertRefused({"sea_legs_enabled": "false"})
        self.assertRefused({"discovery": {"listings_enabled": 0}})

    def test_a_number_must_be_a_real_integer(self):
        self.assertRefused({"discovery": {"interest_daily_cap": True}})
        self.assertRefused({"discovery": {"interest_daily_cap": 2.5}})

    def test_every_integer_field_enforces_its_bounds(self):
        bounds = {
            ("discovery", "interest_daily_cap"): (1, 100),
            ("traveler_pricing", "max_price_per_kg_eur_cents"): (100, 100_000),
            ("traveler_pricing", "max_min_price_eur_cents"): (100, 1_000_000),
            ("reminders", "depart_after_minutes"): (5, 1_440),
            ("reminders", "arrive_after_minutes"): (5, 1_440),
            ("reminders", "repeat_after_minutes"): (15, 1_440),
            ("reminders", "max_repeats"): (0, 5),
            ("route_change", "material_shift_minutes"): (30, 10_080),
        }
        for (section, key), (low, high) in bounds.items():
            with self.subTest(f"{section}.{key}"):
                MarketplacePolicy.from_section({section: {key: low}})
                MarketplacePolicy.from_section({section: {key: high}})
                self.assertRefused({section: {key: low - 1}})
                self.assertRefused({section: {key: high + 1}})


class SaveTimeValidationTests(TestCase):
    def _candidate(self, marketplace):
        active = BusinessSettingsVersion.objects.get(
            status=BusinessSettingsVersion.Status.ACTIVE
        )
        policy = deepcopy(active.policy)
        policy["marketplace"] = marketplace
        return AdminSettingsCreateSerializer(
            data={
                "commission_rate_bps": active.commission_rate_bps,
                "pricing_version": active.pricing_version,
                "policy": policy,
                "reason": "test",
            }
        )

    def test_a_revision_with_an_unknown_marketplace_key_cannot_be_saved(self):
        serializer = self._candidate({"discovery": {"listings": False}})

        self.assertFalse(serializer.is_valid())
        self.assertEqual(
            serializer.errors["policy"]["code"], InvalidMarketplacePolicy.code
        )

    def test_a_revision_carrying_a_parked_section_cannot_be_saved(self):
        # L6A. The two sections the parked features left behind are gone, so
        # a revision naming either is refused like any other unknown key.
        for section in ("courier_handoff", "professional"):
            with self.subTest(section):
                serializer = self._candidate({section: {"enabled": False}})

                self.assertFalse(serializer.is_valid())
                self.assertEqual(
                    serializer.errors["policy"]["code"], InvalidMarketplacePolicy.code
                )

    def test_a_valid_marketplace_section_saves(self):
        self.assertTrue(self._candidate({"discovery": {"listings_enabled": False}}).is_valid())

    def test_the_seeded_revision_has_no_section_and_reads_as_the_defaults(self):
        active = BusinessSettingsVersion.objects.get(
            status=BusinessSettingsVersion.Status.ACTIVE
        )
        self.assertNotIn("marketplace", active.policy)
        self.assertEqual(marketplace_policy(), MarketplacePolicy.from_section(None))


@override_settings(STORAGES=STATIC_STORES)
class MarketplaceFormTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="ops@example.com",
            email="ops@example.com",
            password="Sup3rStrongPass!",
            is_staff=True,
        )

    def _grant(self, role: str):
        assign_admin_roles(self.admin, [role])

    def _post(self, **fields):
        self.client.force_login(self.admin)
        data = {
            "action": "marketplace",
            "listings_enabled": "on",
            "interest_daily_cap": "4",
            "traveler_pricing_enabled": "on",
            "max_price_per_kg_eur": "100.00",
            "max_min_price_eur": "500.00",
            "reason": "Pausing public profiles during review",
            "confirm": "on",
        }
        data.update(fields)
        return self.client.post(reverse("admin_console:settings"), data)

    def test_saving_creates_an_audited_revision_with_the_new_switches(self):
        self._grant("super_admin")
        before = BusinessSettingsVersion.objects.get(
            status=BusinessSettingsVersion.Status.ACTIVE
        )

        response = self._post()

        self.assertEqual(response.status_code, 302)
        active = BusinessSettingsVersion.objects.get(
            status=BusinessSettingsVersion.Status.ACTIVE
        )
        self.assertGreater(active.version, before.version)
        self.assertEqual(
            active.policy["marketplace"],
            {
                "discovery": {
                    "listings_enabled": True,
                    "profiles_enabled": False,
                    "interest_daily_cap": 4,
                },
                "sea_legs_enabled": False,
                # L4A put traveler pricing in the same form.
                "traveler_pricing": {
                    "enabled": True,
                    "max_price_per_kg_eur_cents": 10_000,
                    "max_min_price_eur_cents": 50_000,
                },
            },
        )
        policy = marketplace_policy()
        self.assertFalse(policy.discovery.profiles_enabled)
        self.assertEqual(policy.discovery.interest_daily_cap, 4)
        audit = AdminAuditLog.objects.get(action="settings.version_created")
        self.assertEqual(audit.reason, "Pausing public profiles during review")
        self.assertIsNone(audit.before["marketplace.discovery.profiles_enabled"])
        self.assertFalse(audit.after["marketplace.discovery.profiles_enabled"])

    def test_the_sea_legs_switch_is_saved_with_the_form_and_audited(self):
        self._grant("super_admin")

        self._post(sea_legs_enabled="on")

        self.assertTrue(marketplace_policy().sea_legs_enabled)
        audit = AdminAuditLog.objects.get(action="settings.version_created")
        self.assertIsNone(audit.before["marketplace.sea_legs_enabled"])
        self.assertTrue(audit.after["marketplace.sea_legs_enabled"])

        self._post(reason="Customs question open")

        self.assertFalse(marketplace_policy().sea_legs_enabled)

    def test_the_settings_page_warns_what_sea_legs_enables(self):
        self._grant("super_admin")
        self.client.force_login(self.admin)

        body = self.client.get(reverse("admin_console:settings")).content.decode()

        self.assertIn("Allow sea legs", body)
        self.assertIn("customs", body)

    def test_a_viewer_without_manage_settings_cannot_save(self):
        self._grant("support")

        response = self._post()

        self.assertEqual(response.status_code, 403)
        self.assertNotIn(
            "marketplace",
            BusinessSettingsVersion.objects.get(
                status=BusinessSettingsVersion.Status.ACTIVE
            ).policy,
        )

    def test_the_settings_page_shows_the_form(self):
        self._grant("super_admin")
        self.client.force_login(self.admin)

        response = self.client.get(reverse("admin_console:settings"))

        self.assertContains(response, 'id="st-settings-marketplace"')
        self.assertContains(response, 'name="interest_daily_cap"')
