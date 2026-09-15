"""J2 Boost: extra reward, editable until commitment, frozen once, consumed once.

What is being defended here, in the order the money moves:

**A Boost is priced additively.** The Traveler receives the whole Boost and
ShipTrip's commission is charged on top, at a rate the Admin sets separately from
the delivery commission. Integer cents, ceiling to the platform, no float.

**A Boost has no timer.** It lasts exactly as long as the request can still be
matched. Nothing retires it early and no job exists to.

**A Boost is editable only before commitment.** Up, down, or away to zero while
the request is unmatched; refused the instant an offer is accepted, so a sender
can never reduce compensation a Traveler has already agreed to.

**A Boost freezes once and is consumed once.** Acceptance copies the amount and
the rate onto the Deal; funding clears the column. An unfunded release therefore
revives an unpaid Boost with its request, and a Boost that was actually paid for
cannot revive onto a reopened one -- the column is already zero.

**A Boost funds, refunds and reconciles with the reward it belongs to.** There is
no separate Boost obligation in J2: it rides inside the Deal balance, so no
orphan Boost revenue can exist and no Boost commission is recognised on
economics that were refunded.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from apps.boosts.models import BoostIntentEvent
from apps.boosts.services import (
    BoostError,
    NotAuthorized,
    calculate_boost_reward,
    set_boost_intent,
)
from apps.core.business_settings import activate_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.core.phase4_policy import phase4_policy
from apps.deals.cancellation import cancel_funded_deal
from apps.deals.services import cancel_pending_deal, release_pending_deal_reservation
from apps.deals.tests.phase4_factories import enable_mock_rail
from apps.finance import ledger
from apps.finance.models import LedgerAccount, LedgerTransaction, PaymentRefund, Payout
from apps.finance.settlement import assert_deal_reconciles, read_deal_money
from apps.finance.tests.factories import build_scenario, pay_order_with_mock
from apps.matching.policy import Phase2Policy
from apps.matching.ranking import rank_compatible_candidate
from apps.matching.compatibility import evaluate_compatibility
from apps.parcels.models import ParcelRequest
from apps.parcels.services import cancel_delivery_request
from apps.routing.providers import UnavailableRouteProvider


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_boost_commission(rate_bps: int) -> BusinessSettingsVersion:
    """Activate a new revision carrying one different Boost commission rate."""

    active = BusinessSettingsVersion.objects.get(status="active")
    policy = deepcopy(active.policy)
    policy["boost"]["commission_rate_bps"] = rate_bps
    revision = BusinessSettingsVersion.objects.create(
        version=active.version + 1,
        status=BusinessSettingsVersion.Status.DRAFT,
        commission_rate_bps=active.commission_rate_bps,
        pricing_version=active.pricing_version,
        policy=policy,
    )
    return activate_business_settings(revision)


# --- economics ----------------------------------------------------------------


class BoostEconomicsTests(TestCase):
    def test_traveler_receives_the_whole_boost_and_commission_is_added_on_top(self):
        policy = phase4_policy()
        reward = calculate_boost_reward(amount_eur_cents=800, policy=policy)

        assert reward.amount_eur_cents == 800
        assert reward.traveler_bonus_eur_cents == 800
        assert reward.commission_rate_bps == 2_500
        assert reward.platform_fee_eur_cents == 200
        assert reward.sender_cost_eur_cents == 1_000
        assert reward.as_dict()["economics_version"] == "additive_commission_v2"

    def test_rounding_is_integer_and_the_ceiling_falls_on_the_platform(self):
        """Every edge the money can land on, with no float anywhere near it."""

        policy = phase4_policy()

        zero = calculate_boost_reward(amount_eur_cents=0, policy=policy)
        assert (zero.platform_fee_eur_cents, zero.sender_cost_eur_cents) == (0, 0)

        # EUR 1 at 25%: 25 exactly.
        assert calculate_boost_reward(
            amount_eur_cents=100, policy=policy
        ).platform_fee_eur_cents == 25

        # An odd-cent boost cannot round in the Traveler's favour by shrinking
        # what they receive, and cannot round in nobody's favour either: the
        # remainder goes to the platform as a ceiling.
        odd = calculate_boost_reward(amount_eur_cents=333, policy=policy)
        assert odd.traveler_bonus_eur_cents == 333
        assert odd.platform_fee_eur_cents == 84  # ceil(333 * 0.25) == 83.25 -> 84

        high = calculate_boost_reward(amount_eur_cents=100_000_000, policy=policy)
        assert high.platform_fee_eur_cents == 25_000_000

        set_boost_commission(0)
        free = calculate_boost_reward(amount_eur_cents=777, policy=phase4_policy())
        assert free.platform_fee_eur_cents == 0
        assert free.sender_cost_eur_cents == 777

        set_boost_commission(10_000)
        maximal = calculate_boost_reward(amount_eur_cents=777, policy=phase4_policy())
        assert maximal.platform_fee_eur_cents == 777
        assert maximal.sender_cost_eur_cents == 1_554

    def test_the_boost_rate_is_independent_of_the_delivery_commission(self):
        set_boost_commission(1_000)
        policy = phase4_policy()
        assert policy.settings_version.commission_rate_bps == 2_500
        assert policy.boost.commission_rate_bps == 1_000
        assert (
            calculate_boost_reward(
                amount_eur_cents=1_000, policy=policy
            ).platform_fee_eur_cents
            == 100
        )


# --- editing ------------------------------------------------------------------


class BoostIntentEditingTests(TestCase):
    def test_add_increase_decrease_and_remove_while_the_request_is_open(self):
        scenario = build_scenario(prefix="bi1")
        request_id = scenario.delivery_request.pk
        sender_id = scenario.sender.pk

        added = set_boost_intent(
            delivery_request_id=request_id, actor_id=sender_id, amount_eur_cents=500
        )
        assert added["boost_eur_cents"] == 500
        assert added["economics"]["boost_traveler_bonus_eur_cents"] == 500
        assert added["economics"]["boost_platform_fee_eur_cents"] == 125
        assert added["can_edit"] is True
        # No timer, ever: the Boost is eligible for exactly as long as the
        # request is, and nothing else.
        assert added["policy"]["has_expiry"] is False
        assert added["eligible_until"] == scenario.delivery_request.deadline_at

        raised = set_boost_intent(
            delivery_request_id=request_id, actor_id=sender_id, amount_eur_cents=1_200
        )
        assert raised["boost_eur_cents"] == 1_200
        lowered = set_boost_intent(
            delivery_request_id=request_id, actor_id=sender_id, amount_eur_cents=300
        )
        assert lowered["boost_eur_cents"] == 300
        removed = set_boost_intent(
            delivery_request_id=request_id, actor_id=sender_id, amount_eur_cents=0
        )
        assert removed["boost_eur_cents"] == 0

        reasons = list(
            BoostIntentEvent.objects.filter(delivery_request_id=request_id)
            .order_by("pk")
            .values_list("reason", "previous_eur_cents", "amount_eur_cents")
        )
        assert reasons == [
            ("sender_set", 0, 500),
            ("sender_increased", 500, 1_200),
            ("sender_decreased", 1_200, 300),
            ("sender_removed", 300, 0),
        ]

    def test_setting_the_same_amount_writes_nothing(self):
        scenario = build_scenario(prefix="bi2")
        for _ in range(3):
            set_boost_intent(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=500,
            )
        assert BoostIntentEvent.objects.count() == 1

    def test_the_band_is_enforced_and_zero_is_always_allowed(self):
        scenario = build_scenario(prefix="bi3")
        policy = phase4_policy()

        with self.assertRaises(BoostError) as caught:
            set_boost_intent(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=policy.boost.minimum_intent_eur_cents - 1,
            )
        assert caught.exception.code == "boost_amount_below_minimum"

        with self.assertRaises(BoostError) as caught:
            set_boost_intent(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=policy.boost.maximum_intent_eur_cents + 1,
            )
        assert caught.exception.code == "boost_amount_above_maximum"

        # The retired package's EUR 5 floor is gone with the package; a EUR 1
        # boost is a real offer and is accepted.
        assert (
            set_boost_intent(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=100,
            )["boost_eur_cents"]
            == 100
        )

    def test_lowering_a_boost_cannot_strand_a_deposit_already_committed(self):
        """A deposit pre-pays a total; the total cannot shrink below it.

        Without this, `apply_posting_deposit_credit` would credit only what the
        balance owes and leave the difference discharging nothing -- neither
        credited nor refunded, which is real money quietly stuck.
        """

        from apps.finance.services import ensure_posting_deposit_order

        scenario = build_scenario(prefix="bi7", open_request=False)
        request = scenario.delivery_request
        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=1_000,
        )
        request.refresh_from_db()
        # Reward 2000 + 500 commission + boost 1000 + 250 boost commission.
        ensure_posting_deposit_order(
            delivery_request=request, chosen_amount_eur_cents=3_750
        )

        with self.assertRaises(BoostError) as caught:
            set_boost_intent(
                delivery_request_id=request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=0,
            )
        assert caught.exception.code == "boost_below_prepaid_deposit"
        assert caught.exception.details()["deposit_eur_cents"] == 3_750

        request.refresh_from_db()
        assert request.boost_eur_cents == 1_000

        # Raising it is always fine, and so is a cut the deposit still covers.
        assert (
            set_boost_intent(
                delivery_request_id=request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=2_000,
            )["boost_eur_cents"]
            == 2_000
        )
        assert (
            set_boost_intent(
                delivery_request_id=request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=1_000,
            )["boost_eur_cents"]
            == 1_000
        )

    def test_only_the_sender_may_change_their_own_requests_boost(self):
        scenario = build_scenario(prefix="bi4")
        for stranger in (scenario.traveler, scenario.outsider):
            with self.assertRaises(NotAuthorized):
                set_boost_intent(
                    delivery_request_id=scenario.delivery_request.pk,
                    actor_id=stranger.pk,
                    amount_eur_cents=500,
                )

    def test_ranking_weight_is_derived_bounded_and_paired_with_the_deadline(self):
        scenario = build_scenario(prefix="bi5")
        request = scenario.delivery_request
        policy = phase4_policy()

        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=100,
        )
        request.refresh_from_db()
        assert request.ranking_boost_weight == 1
        # Paired with the request's own deadline: the Boost lasts as long as
        # the request can be matched, which is not a Boost timer.
        assert request.ranking_boost_expires_at == request.deadline_at
        assert request.is_ranking_boost_active() is True

        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=100_000_000,
        )
        request.refresh_from_db()
        assert request.ranking_boost_weight == policy.boost.ranking_weight_max

        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=0,
        )
        request.refresh_from_db()
        assert request.ranking_boost_weight == 0
        assert request.ranking_boost_expires_at is None

    def test_a_boost_still_never_creates_compatibility(self):
        scenario = build_scenario(prefix="bi6")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=100_000_000,
        )
        scenario.delivery_request.refresh_from_db()
        policy = Phase2Policy.from_settings(scenario.policy.settings_version)
        compat = evaluate_compatibility(
            delivery_request=scenario.delivery_request,
            journey=scenario.journey,
            policy=policy,
            route_provider=UnavailableRouteProvider(),
        )
        ranked = rank_compatible_candidate(
            compatibility=compat,
            delivery_request=scenario.delivery_request,
            policy=policy,
        )
        assert ranked["boost"]["compatibility_override"] is False
        assert ranked["boost"]["points"] <= policy.max_boost_points
        assert ranked["score"] == ranked["base_score"] + ranked["boost"]["points"]


# --- the commitment boundary --------------------------------------------------


class BoostFreezeTests(TestCase):
    def test_acceptance_freezes_the_amount_the_rate_and_the_sender_total(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bf1")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        terms = deal.terms

        assert terms.boost_economics_version == "additive_commission_v2"
        assert terms.boost_amount_minor == 800
        assert terms.boost_commission_rate_bps == 2_500
        assert terms.boost_traveler_bonus_minor == 800
        assert terms.boost_platform_fee_minor == 200
        # base 2000 + base fee 500 + boost 800 + boost fee 200
        assert terms.sender_total_with_boost_minor == 3_500
        assert terms.traveler_total_minor == 2_800
        assert terms.platform_total_minor == 700
        assert scenario.balance_order().amount_eur_cents == 3_500

        assert BoostIntentEvent.objects.filter(
            delivery_request_id=scenario.delivery_request.pk,
            reason=BoostIntentEvent.Reason.FROZEN_INTO_DEAL,
            deal_id=deal.pk,
        ).exists()

    def test_a_later_admin_rate_change_cannot_move_an_existing_deal(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bf2")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)

        set_boost_commission(9_000)

        deal.refresh_from_db()
        assert deal.terms.boost_commission_rate_bps == 2_500
        assert deal.terms.boost_platform_fee_minor == 200
        assert scenario.balance_order().amount_eur_cents == 3_500

    def test_the_boost_is_immutable_once_the_request_is_matched(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bf3")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        scenario.accept(reward_eur_cents=2_000)

        for attempt in (0, 100, 5_000):
            with self.assertRaises(BoostError) as caught:
                set_boost_intent(
                    delivery_request_id=scenario.delivery_request.pk,
                    actor_id=scenario.sender.pk,
                    amount_eur_cents=attempt,
                )
            assert caught.exception.code == "boost_request_not_active"

    def test_the_new_rate_applies_to_the_next_commitment(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bf4")
        set_boost_commission(1_000)
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        assert deal.terms.boost_commission_rate_bps == 1_000
        assert deal.terms.boost_platform_fee_minor == 80
        assert scenario.balance_order().amount_eur_cents == 3_380


# --- funding, release and rematch --------------------------------------------


class BoostLifetimeTests(TestCase):
    def test_funding_consumes_the_boost_so_it_can_never_revive(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bl1")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        pay_order_with_mock(self.client, scenario.balance_order())

        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.boost_eur_cents == 0
        assert BoostIntentEvent.objects.filter(
            delivery_request_id=scenario.delivery_request.pk,
            reason=BoostIntentEvent.Reason.CONSUMED_BY_FUNDING,
        ).exists()
        # The Deal keeps the authoritative copy.
        deal.refresh_from_db()
        assert deal.terms.boost_amount_minor == 800

    def test_an_unfunded_reservation_release_revives_the_boost_with_the_request(
        self,
    ):
        enable_mock_rail()
        scenario = build_scenario(prefix="bl2")
        request = scenario.delivery_request
        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)

        release_pending_deal_reservation(
            deal_id=deal.pk, reason="payment_grace_expired"
        )

        request.refresh_from_db()
        assert request.status == ParcelRequest.Status.OPEN
        # Nobody paid it, so it belongs to the request, not to the traveler who
        # walked away.
        assert request.boost_eur_cents == 800
        assert request.ranking_boost_weight > 0
        assert request.ranking_boost_expires_at == request.deadline_at
        assert BoostIntentEvent.objects.filter(
            delivery_request_id=request.pk,
            reason=BoostIntentEvent.Reason.RELEASED_WITH_RESERVATION,
        ).exists()

        # And it is editable again.
        assert (
            set_boost_intent(
                delivery_request_id=request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=1_500,
            )["boost_eur_cents"]
            == 1_500
        )

    def test_an_unfunded_deal_cancellation_also_returns_the_boost(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bl3")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        cancel_pending_deal(deal_id=deal.pk, actor_id=scenario.sender.pk)

        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.status == ParcelRequest.Status.OPEN
        assert scenario.delivery_request.boost_eur_cents == 800

    def test_cancelling_the_request_ends_its_boost_with_it(self):
        scenario = build_scenario(prefix="bl4")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        cancel_delivery_request(
            request_id=scenario.delivery_request.pk, actor_id=scenario.sender.pk
        )

        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.boost_eur_cents == 0
        assert scenario.delivery_request.ranking_boost_weight == 0
        assert BoostIntentEvent.objects.filter(
            delivery_request_id=scenario.delivery_request.pk,
            reason=BoostIntentEvent.Reason.REQUEST_CLOSED,
        ).exists()

    def test_the_boost_survives_the_whole_unmatched_life_of_the_request(self):
        """No timer means no decay: only an explicit event may change it."""

        scenario = build_scenario(prefix="bl5")
        request = scenario.delivery_request
        set_boost_intent(
            delivery_request_id=request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        # There is no Boost expiry job, so nothing exists that could retire it.
        from apps.finance.models import ScheduledJob

        assert not ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.BOOST_EXPIRY
        ).exists()

        request.refresh_from_db()
        assert request.boost_eur_cents == 800
        assert request.is_ranking_boost_active(
            at=request.deadline_at - timedelta(seconds=1)
        )


# --- accounting ---------------------------------------------------------------


class BoostAccountingTests(TestCase):
    def test_funding_recognises_the_boost_separately_and_balances_the_subledger(
        self,
    ):
        enable_mock_rail()
        scenario = build_scenario(prefix="bac1")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        pay_order_with_mock(self.client, scenario.balance_order())

        # The Traveler is owed the reward plus the whole Boost.
        assert Payout.objects.get(deal=deal).amount_eur_cents == 2_800

        allocation = LedgerTransaction.objects.get(
            key=f"deal_boost_allocation:deal:{deal.pk}"
        )
        assert allocation.kind == LedgerTransaction.Kind.BOOST_ALLOCATION
        assert sum(entry.amount_eur_cents for entry in allocation.entries.all()) == 0
        # Base delivery commission and Boost commission are separable, which is
        # what H5 needs to tell them apart.
        assert (
            allocation.entries.get(
                account=LedgerAccount.PLATFORM_COMMISSION
            ).amount_eur_cents
            == -200
        )
        funding = LedgerTransaction.objects.get(key=f"deal_funding:deal:{deal.pk}")
        assert (
            funding.entries.get(
                account=LedgerAccount.PLATFORM_COMMISSION
            ).amount_eur_cents
            == -500
        )
        # No money left unassigned: the pooled deal liability is fully released.
        assert ledger.deal_balance(deal.pk, LedgerAccount.DEAL_FUNDS) == 0
        assert assert_deal_reconciles(deal.pk)["net"] == 0
        # There is no separate Boost obligation in J2.
        assert not read_deal_money(deal).boost_order_ids

    def test_a_funded_cancellation_refunds_the_boost_with_the_reward(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bac2")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        pay_order_with_mock(self.client, scenario.balance_order())
        money = read_deal_money(deal)
        assert money.collected_eur_cents == 3_500

        quote = cancel_funded_deal(deal_id=deal.pk, actor_id=scenario.traveler.pk)

        refunded = sum(
            PaymentRefund.objects.filter(order__deal_id=deal.pk)
            .exclude(status=PaymentRefund.Status.FAILED)
            .values_list("amount_eur_cents", flat=True)
        )
        assert quote.sender_refund_eur_cents == 3_500
        assert refunded == 3_500
        assert assert_deal_reconciles(deal.pk)["net"] == 0
        assert Payout.objects.get(deal=deal).status == Payout.Status.CANCELLED
        # The request is terminal, so a consumed Boost has nowhere to revive to.
        scenario.delivery_request.refresh_from_db()
        assert scenario.delivery_request.boost_eur_cents == 0

    def test_a_zero_boost_creates_no_allocation_and_changes_no_total(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bac3")
        deal = scenario.accept(reward_eur_cents=2_000)
        pay_order_with_mock(self.client, scenario.balance_order())

        assert deal.terms.boost_amount_minor == 0
        assert scenario.balance_order().amount_eur_cents == 2_500
        assert not LedgerTransaction.objects.filter(
            key=f"deal_boost_allocation:deal:{deal.pk}"
        ).exists()
        assert Payout.objects.get(deal=deal).amount_eur_cents == 2_000
        assert assert_deal_reconciles(deal.pk)["net"] == 0


# --- concurrency and idempotency ---------------------------------------------


class BoostConcurrencyTests(TestCase):
    def test_an_edit_racing_an_acceptance_loses_and_the_frozen_terms_win(self):
        """The request row serialises the two writers.

        Acceptance takes the request FOR NO KEY UPDATE and leaves it `matched`.
        An edit that lands afterwards reads that committed state and is refused,
        which is exactly what the Deal's frozen terms depend on.
        """

        enable_mock_rail()
        scenario = build_scenario(prefix="bcc1")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)

        with self.assertRaises(BoostError):
            set_boost_intent(
                delivery_request_id=scenario.delivery_request.pk,
                actor_id=scenario.sender.pk,
                amount_eur_cents=5_000,
            )
        deal.refresh_from_db()
        assert deal.terms.boost_amount_minor == 800

    def test_a_replayed_funding_webhook_recognises_the_boost_once(self):
        enable_mock_rail()
        scenario = build_scenario(prefix="bcc2")
        set_boost_intent(
            delivery_request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
            amount_eur_cents=800,
        )
        deal = scenario.accept(reward_eur_cents=2_000)
        order = scenario.balance_order()
        attempt = pay_order_with_mock(self.client, order)

        from apps.finance.tests.factories import deliver_mock_webhook, succeed_attempt

        assert deliver_mock_webhook(self.client, succeed_attempt(attempt)).status_code == 200
        assert deliver_mock_webhook(self.client, succeed_attempt(attempt)).status_code == 200

        assert (
            LedgerTransaction.objects.filter(
                key=f"deal_boost_allocation:deal:{deal.pk}"
            ).count()
            == 1
        )
        assert Payout.objects.filter(deal=deal).count() == 1
        assert Payout.objects.get(deal=deal).amount_eur_cents == 2_800
        assert assert_deal_reconciles(deal.pk)["net"] == 0


# --- API ----------------------------------------------------------------------


class BoostApiTests(TestCase):
    def test_policy_read_edit_and_authorization(self):
        scenario = build_scenario(prefix="bapi1")
        sender = client_for(scenario.sender)
        outsider = client_for(scenario.outsider)
        url = reverse("boosts-intent", args=[scenario.delivery_request.pk])

        assert APIClient().get(reverse("boosts-policy")).status_code == 401

        policy_res = sender.get(reverse("boosts-policy"))
        assert policy_res.status_code == 200, policy_res.data
        assert policy_res.data["has_expiry"] is False
        assert policy_res.data["affects_compatibility"] is False
        assert policy_res.data["minimum_boost_eur_cents"] == 100
        assert policy_res.data["boost_commission_rate_bps"] == 2_500

        # Nobody else may read or write it.
        assert outsider.get(url).status_code in (403, 404)
        assert (
            outsider.put(url, {"boost_eur_cents": 500}, format="json").status_code
            in (403, 404)
        )

        res = sender.put(url, {"boost_eur_cents": 800}, format="json")
        assert res.status_code == 200, res.data
        assert res.data["boost_eur_cents"] == 800
        assert res.data["economics"]["boost_sender_cost_eur_cents"] == 1_000
        assert res.data["can_edit"] is True

        read = sender.get(url)
        assert read.status_code == 200, read.data
        assert read.data["boost_eur_cents"] == 800
        assert [row["reason"] for row in read.data["history"]] == ["sender_set"]

        # A negative amount is refused by the contract, not by the service.
        assert sender.put(url, {"boost_eur_cents": -1}, format="json").status_code == 400

    def test_the_request_pricing_contract_states_the_total_offered_reward(self):
        scenario = build_scenario(prefix="bapi2")
        sender = client_for(scenario.sender)
        sender.put(
            reverse("boosts-intent", args=[scenario.delivery_request.pk]),
            {"boost_eur_cents": 800},
            format="json",
        )
        res = sender.get(
            reverse("parcels-pricing", args=[scenario.delivery_request.pk])
        )
        assert res.status_code == 200, res.data
        boost = res.data["boost"]
        assert boost["boost_eur_cents"] == 800
        assert boost["base_reward_eur_cents"] == 2_000
        # The traveler-facing number, computed by the server.
        assert boost["total_offered_reward_eur_cents"] == 2_800
        assert boost["boost_platform_fee_eur_cents"] == 200
        assert res.data["actions"]["can_edit_boost"] is True
