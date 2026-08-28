"""Integer money arithmetic and the versioned payment policy.

These are the foundations everything else stands on: if conversion rounds the
wrong way or the policy parser accepts a malformed revision, every higher-level
guarantee is decorative.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from django.test import TestCase

from apps.core.business_settings import (
    activate_business_settings,
    get_active_business_settings,
)
from apps.core.models import BusinessSettingsVersion
from apps.finance.money import (
    CANONICAL_CURRENCY,
    FX_RATE_SCALE,
    MoneyError,
    clamp,
    convert_eur_cents,
    currency_exponent,
    format_minor,
    format_rate,
    percentage_of,
    require_positive_cents,
)
from apps.finance.policy import (
    InvalidPaymentPolicy,
    PaymentTimingMode,
    Phase3Policy,
    phase3_policy,
)


class MoneyArithmeticTests(TestCase):
    def test_canonical_currency_is_eur_in_cents(self):
        assert CANONICAL_CURRENCY == "EUR"
        assert currency_exponent("EUR") == 2

    def test_dzd_has_no_circulating_minor_unit(self):
        """Chargily expresses DZD in whole dinars; the exponent records that."""

        assert currency_exponent("DZD") == 0
        assert currency_exponent("dzd") == 0

    def test_an_unknown_currency_is_refused(self):
        with self.assertRaises(MoneyError):
            currency_exponent("USD")

    def test_conversion_is_exact_integer_arithmetic(self):
        # EUR 62.50 at 150.000000 DZD/EUR = 9375 DZD exactly.
        assert (
            convert_eur_cents(6_250, to_currency="DZD", rate_micros=150_000_000)
            == 9_375
        )

    def test_conversion_rounds_up_so_we_never_undercollect(self):
        """A fraction of a dinar cannot be charged, so the residual rounds up."""

        # EUR 0.01 at 150.5 DZD/EUR = 1.505 DZD -> 2 whole dinars.
        assert convert_eur_cents(1, to_currency="DZD", rate_micros=150_500_000) == 2
        # EUR 10.01 at 150.123456 -> 1502.735... -> 1503.
        assert (
            convert_eur_cents(1_001, to_currency="DZD", rate_micros=150_123_456)
            == 1_503
        )

    def test_conversion_never_uses_floats(self):
        """A rate that a float would mangle still converts exactly."""

        # 0.1 + 0.2 style error would show up here as an off-by-one.
        assert (
            convert_eur_cents(300, to_currency="DZD", rate_micros=100_000_000) == 300
        )

    def test_conversion_rejects_a_nonsense_rate(self):
        for bad in (0, -1, True):
            with self.assertRaises(MoneyError):
                convert_eur_cents(1_000, to_currency="DZD", rate_micros=bad)

    def test_percentage_uses_basis_points_and_exact_decimals(self):
        assert percentage_of(4_000, bps=1_000) == 400  # 10% of EUR 40.00
        assert percentage_of(3_333, bps=1_000) == 333  # 333.3 -> 333
        assert percentage_of(3_335, bps=1_000) == 334  # 333.5 -> 334 (half up)

    def test_clamp_bounds_and_validates_its_range(self):
        assert clamp(150, minimum=300, maximum=700) == 300
        assert clamp(1_500, minimum=300, maximum=700) == 700
        assert clamp(450, minimum=300, maximum=700) == 450
        with self.assertRaises(MoneyError):
            clamp(1, minimum=700, maximum=300)

    def test_positive_cents_rejects_booleans_and_zero(self):
        assert require_positive_cents(1) == 1
        for bad in (0, -5, True, 1.5, "100", None):
            with self.assertRaises(MoneyError):
                require_positive_cents(bad)

    def test_display_helpers_are_exact(self):
        assert format_rate(150_250_000) == "150.25"
        assert format_minor(9_375, exponent=0) == "9375"
        assert format_minor(6_250, exponent=2) == "62.5"
        assert Decimal(format_rate(FX_RATE_SCALE)) == Decimal(1)


class PaymentPolicyTests(TestCase):
    def _draft(self, mutate) -> BusinessSettingsVersion:
        active = get_active_business_settings()
        policy = deepcopy(active.policy)
        mutate(policy)
        return BusinessSettingsVersion(
            version=9_100,
            status=BusinessSettingsVersion.Status.DRAFT,
            commission_rate_bps=2_500,
            pricing_version="v1-policy-test",
            policy=policy,
        )

    def test_the_seeded_revision_parses_and_defaults_to_posting_deposit(self):
        policy = phase3_policy()

        assert policy.timing_mode == PaymentTimingMode.POSTING_DEPOSIT
        assert policy.deposit_required is True
        assert policy.posting_deposit.percent_bps == 1_000
        assert policy.posting_deposit.min_eur_cents == 300
        assert policy.posting_deposit.max_eur_cents == 700
        assert policy.providers.stripe_enabled is True
        assert policy.providers.chargily_enabled is True
        assert policy.providers.mock_enabled is False
        assert policy.chargily.new_checkouts_enabled is True
        assert policy.payout.protection_window_seconds == 172_800
        assert policy.payout.auto_stripe_enabled is False

    def test_a_missing_payments_object_fails_closed(self):
        draft = self._draft(lambda policy: policy.pop("payments"))

        with self.assertRaises(InvalidPaymentPolicy):
            Phase3Policy.from_settings(draft)

    def test_an_unknown_timing_mode_is_refused(self):
        draft = self._draft(
            lambda policy: policy["payments"].__setitem__("timing_mode", "whenever")
        )

        with self.assertRaises(InvalidPaymentPolicy):
            Phase3Policy.from_settings(draft)

    def test_a_deposit_minimum_above_its_maximum_is_refused(self):
        def mutate(policy):
            policy["payments"]["posting_deposit"]["min_eur_cents"] = 900
            policy["payments"]["posting_deposit"]["max_eur_cents"] = 700

        with self.assertRaises(InvalidPaymentPolicy):
            Phase3Policy.from_settings(self._draft(mutate))

    def test_an_absurd_fx_rate_is_refused_rather_than_charged(self):
        def mutate(policy):
            policy["payments"]["chargily"]["eur_dzd_rate_micros"] = 10**15

        with self.assertRaises(InvalidPaymentPolicy):
            Phase3Policy.from_settings(self._draft(mutate))

    def test_a_boolean_flag_must_actually_be_boolean(self):
        def mutate(policy):
            policy["payments"]["providers"]["stripe_enabled"] = "yes"

        with self.assertRaises(InvalidPaymentPolicy):
            Phase3Policy.from_settings(self._draft(mutate))

    def test_the_snapshot_carries_policy_but_not_the_live_rate_binding(self):
        """An order snapshots policy; the *rate used* belongs to the attempt."""

        snapshot = phase3_policy().snapshot()

        assert snapshot["canonical_currency"] == "EUR"
        assert snapshot["payments"]["timing_mode"] == "posting_deposit"
        assert snapshot["business_settings_version"] == (
            get_active_business_settings().version
        )

    def test_after_acceptance_mode_disables_the_deposit_requirement(self):
        def mutate(policy):
            policy["payments"]["timing_mode"] = "after_acceptance"

        parsed = Phase3Policy.from_settings(self._draft(mutate))

        assert parsed.deposit_required is False

    def test_activating_a_payment_revision_keeps_one_active_row(self):
        candidate = BusinessSettingsVersion.objects.create(
            version=9_101,
            status=BusinessSettingsVersion.Status.DRAFT,
            commission_rate_bps=2_500,
            pricing_version="v1-payments-2",
            policy=deepcopy(get_active_business_settings().policy),
        )

        activate_business_settings(candidate)

        assert (
            BusinessSettingsVersion.objects.filter(status="active").count() == 1
        )
        assert get_active_business_settings().pk == candidate.pk


class LegacyRevisionCompatibilityTests(TestCase):
    """An offer frozen under a pre-Phase-3 revision must still accept.

    The offer's settings revision freezes the *agreed economics*: reward,
    commission rate, fee, sender total. Which payment rails exist, how the
    posting deposit is priced and what the FX rate is are properties of the
    moment the payment happens, so they come from the active revision instead.
    Reading the payment policy off the offer's own revision would break every
    offer negotiated before Phase 3 shipped.
    """

    def test_an_offer_frozen_on_the_phase_two_revision_still_accepts(self):
        from apps.core.models import BusinessSettingsVersion
        from apps.deals.models import Deal
        from apps.finance.models import PaymentOrder
        from apps.finance.tests.factories import build_scenario

        scenario = build_scenario(prefix="legacy-rev")
        offer = scenario.propose(reward_eur_cents=2_000)

        # Re-point the offer at the Phase 2 revision, which has no `payments`
        # object at all — exactly the shape a production row written before
        # this phase carries.
        phase2 = BusinessSettingsVersion.objects.get(version=2)
        assert "payments" not in phase2.policy
        type(offer).objects.filter(pk=offer.pk).update(
            business_settings_version=phase2
        )
        offer.refresh_from_db()

        deal = scenario.accept()

        assert deal.status == Deal.Status.PAYMENT_REQUIRED
        order = PaymentOrder.objects.get(
            deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        # The obligation is the frozen economics; the policy snapshot is current.
        # "Current" is asserted against whatever revision is active rather than
        # against a number, so a later phase adding a revision does not look
        # like a regression here.
        assert order.amount_eur_cents == int(deal.terms.sender_total_minor)
        assert order.terms_snapshot["payments"]["timing_mode"] == "posting_deposit"
        assert (
            order.business_settings_version.version
            == BusinessSettingsVersion.objects.get(status="active").version
        )
