"""Post-funding cancellation, compensation and the no-show foundation.

The rule being defended is not "the right number appears in the response". It is
that after a cancellation the platform is holding exactly nothing it should not
be holding: every cent collected has gone back to the sender, to the traveler as
compensation, or stayed as commission, and the ledger says so. A cancellation
that returned a plausible number while stranding forty cents in `deal_funds`
would pass a shallower test and lose real money.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.deals.cancellation import (
    CancellationError,
    cancel_funded_deal,
    quote_cancellation,
    record_no_show,
)
from apps.deals.models import Deal, DealEvent, DealLegAllocation
from apps.deals.tests.phase4_factories import (
    confirm_pickup,
    fund_scenario,
    record_recipient,
    reveal_pickup_code,
)
from apps.finance.models import PaymentOrder, PaymentRefund, Payout
from apps.finance.settlement import assert_deal_reconciles, read_deal_money
from apps.handover.models import DealHandoverCode
from apps.handover.services import HandoverError, submit_code


def client_for(user) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def set_pickup_in(scenario, delta: timedelta) -> None:
    """Move the agreed pickup instant, which is what the cutoff is measured from."""

    Deal.objects.filter(pk=scenario.deal.pk).update(
        agreed_pickup_at=timezone.now() + delta
    )


def total_refunds(deal_id: int) -> int:
    from django.db.models import Sum

    return int(
        PaymentRefund.objects.filter(order__deal_id=deal_id)
        .exclude(status=PaymentRefund.Status.FAILED)
        .aggregate(total=Sum("amount_eur_cents"))["total"]
        or 0
    )


class CancellationPolicyTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="cnl", reward_eur_cents=20_000)
        record_recipient(self.scenario)

    def test_the_traveler_cancelling_before_pickup_refunds_the_sender_in_full(self):
        set_pickup_in(self.scenario, timedelta(hours=2))
        money = read_deal_money(self.scenario.deal)
        quote = cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.traveler.pk
        )

        assert quote.actor_role == "traveler"
        assert quote.is_late is False
        assert quote.sender_refund_eur_cents == money.collected_eur_cents
        assert quote.traveler_compensation_eur_cents == 0
        assert total_refunds(self.scenario.deal.pk) == money.collected_eur_cents
        assert self.scenario.deal.status == Deal.Status.REFUNDED

    def test_the_sender_cancelling_well_before_pickup_pays_no_compensation(self):
        set_pickup_in(self.scenario, timedelta(hours=48))
        money = read_deal_money(self.scenario.deal)
        quote = cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )

        assert quote.is_late is False
        assert quote.sender_refund_eur_cents == money.collected_eur_cents
        assert quote.traveler_compensation_eur_cents == 0

    def test_the_sender_cancelling_inside_the_cutoff_pays_the_capped_percentage(self):
        """Reward EUR 200: ten percent is EUR 20, the cap is EUR 15."""

        set_pickup_in(self.scenario, timedelta(hours=2))
        money = read_deal_money(self.scenario.deal)
        quote = cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )

        assert quote.is_late is True
        assert quote.traveler_compensation_eur_cents == 1_500
        assert quote.sender_refund_eur_cents == money.collected_eur_cents - 1_500
        assert self.scenario.deal.status == Deal.Status.PARTIALLY_REFUNDED
        assert DealEvent.objects.filter(
            deal_id=self.scenario.deal.pk,
            kind=DealEvent.Kind.COMPENSATION_APPLIED,
        ).exists()

    def test_a_smaller_reward_pays_ten_percent_rather_than_the_cap(self):
        scenario = fund_scenario(self.client, prefix="cnl-small", reward_eur_cents=2_000)
        record_recipient(scenario)
        set_pickup_in(scenario, timedelta(hours=2))
        quote = cancel_funded_deal(deal_id=scenario.deal.pk, actor_id=scenario.sender.pk)

        assert quote.is_late is True
        assert quote.traveler_compensation_eur_cents == 200

    def test_exactly_on_the_cutoff_counts_as_late(self):
        """The boundary is inclusive, and it is stated once rather than guessed."""

        set_pickup_in(self.scenario, timedelta(hours=24))
        quote = quote_cancellation(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        assert quote.cutoff_at is not None
        assert quote.is_late is True

    def test_one_second_before_the_cutoff_is_still_free(self):
        set_pickup_in(self.scenario, timedelta(hours=24, seconds=5))
        quote = quote_cancellation(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        assert quote.is_late is False

    def test_a_stranger_is_refused(self):
        quote = quote_cancellation(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.outsider.pk
        )
        assert quote.allowed is False
        assert quote.refusal_code == "not_authorized"
        with self.assertRaises(CancellationError):
            cancel_funded_deal(
                deal_id=self.scenario.deal.pk, actor_id=self.scenario.outsider.pk
            )

    def test_the_quote_endpoint_prices_without_cancelling(self):
        set_pickup_in(self.scenario, timedelta(hours=2))
        response = client_for(self.scenario.sender).get(
            reverse("deals-cancellation-quote", args=[self.scenario.deal.pk])
        )
        assert response.status_code == 200
        assert response.data["is_late"] is True
        assert response.data["traveler_compensation_eur_cents"] == 1_500
        assert self.scenario.deal.status == Deal.Status.PICKUP_READY


class CancellationSideEffectTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="cnlfx", reward_eur_cents=20_000)
        record_recipient(self.scenario)
        set_pickup_in(self.scenario, timedelta(hours=2))

    def test_capacity_the_payout_and_the_live_codes_are_all_released(self):
        cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )

        allocations = DealLegAllocation.objects.filter(deal_id=self.scenario.deal.pk)
        assert allocations.exists()
        assert all(
            row.status
            in (
                DealLegAllocation.Status.RELEASED,
                DealLegAllocation.Status.CANCELLED,
            )
            for row in allocations
        )
        assert not DealHandoverCode.objects.filter(
            deal_id=self.scenario.deal.pk,
            status__in=DealHandoverCode.LIVE_STATUSES,
        ).exists()

    def test_the_balance_obligation_is_closed_so_late_money_cannot_fund_it(self):
        cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        order = PaymentOrder.objects.get(
            deal_id=self.scenario.deal.pk, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        assert order.cancelled_at is not None or order.is_collectable is False

    def test_every_collected_cent_is_accounted_for(self):
        money = read_deal_money(self.scenario.deal)
        quote = cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        assert (
            quote.sender_refund_eur_cents
            + quote.traveler_compensation_eur_cents
            + quote.platform_fee_eur_cents
            == money.collected_eur_cents
        )
        balances = assert_deal_reconciles(self.scenario.deal.pk)
        # The ledger's own arithmetic: every transaction balanced, so the sum
        # over all accounts for this Deal is zero.
        assert balances["net"] == 0

    def test_the_payout_reflects_only_the_compensation(self):
        cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        payout = Payout.objects.filter(deal_id=self.scenario.deal.pk).first()
        if payout is not None and payout.status != Payout.Status.CANCELLED:
            assert int(payout.amount_eur_cents) == 1_500

    def test_cancelling_twice_does_not_refund_twice(self):
        cancel_funded_deal(
            deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
        )
        refunded = total_refunds(self.scenario.deal.pk)
        with self.assertRaises(CancellationError):
            cancel_funded_deal(
                deal_id=self.scenario.deal.pk, actor_id=self.scenario.sender.pk
            )
        assert total_refunds(self.scenario.deal.pk) == refunded


class CancellationAfterPickupTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="cnlpk")
        record_recipient(self.scenario)
        confirm_pickup(self.scenario)

    def test_no_normal_cancellation_exists_after_pickup(self):
        for actor in (self.scenario.sender, self.scenario.traveler):
            quote = quote_cancellation(
                deal_id=self.scenario.deal.pk, actor_id=actor.pk
            )
            assert quote.allowed is False
            assert quote.refusal_code == "cancellation_not_available_after_pickup"
            with self.assertRaises(CancellationError) as caught:
                cancel_funded_deal(deal_id=self.scenario.deal.pk, actor_id=actor.pk)
            assert caught.exception.code == (
                "cancellation_not_available_after_pickup"
            )

    def test_the_api_points_the_client_at_a_dispute_instead(self):
        response = client_for(self.scenario.sender).post(
            reverse("deals-cancel", args=[self.scenario.deal.pk])
        )
        assert response.status_code == 409
        assert response.data["code"] == "cancellation_not_available_after_pickup"
        assert "dispute" in response.data["detail"].lower()


class CancellationVersusPickupTests(TestCase):
    """The two writers that race for the same Deal, resolved by its row lock.

    Serialized here; the genuinely concurrent version lives in the PostgreSQL
    suite. What this asserts is the invariant both orderings must satisfy:
    exactly one of them takes effect, and the loser is refused against committed
    state rather than half-applying.
    """

    def test_a_cancellation_that_loses_to_a_pickup_is_refused(self):
        scenario = fund_scenario(self.client, prefix="race1")
        record_recipient(scenario)
        set_pickup_in(scenario, timedelta(hours=2))
        confirm_pickup(scenario)

        with self.assertRaises(CancellationError) as caught:
            cancel_funded_deal(deal_id=scenario.deal.pk, actor_id=scenario.sender.pk)
        assert caught.exception.code == "cancellation_not_available_after_pickup"
        assert total_refunds(scenario.deal.pk) == 0

    def test_a_pickup_that_loses_to_a_cancellation_is_refused(self):
        scenario = fund_scenario(self.client, prefix="race2")
        record_recipient(scenario)
        set_pickup_in(scenario, timedelta(hours=2))
        code = reveal_pickup_code(scenario)
        cancel_funded_deal(deal_id=scenario.deal.pk, actor_id=scenario.sender.pk)

        with self.assertRaises(HandoverError):
            submit_code(
                deal_id=scenario.deal.pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=scenario.traveler.pk,
                submitted_code=code,
            )
        assert scenario.deal.pickup_confirmed_at is None


class NoShowTests(TestCase):
    def setUp(self):
        self.scenario = fund_scenario(self.client, prefix="nsh")
        record_recipient(self.scenario)

    def test_a_verified_traveler_no_show_refunds_the_sender_in_full(self):
        money = read_deal_money(self.scenario.deal)
        result = record_no_show(
            deal_id=self.scenario.deal.pk,
            party=Deal.NoShowParty.TRAVELER,
            admin_actor_id=self.scenario.admin.pk,
            note="Traveler did not appear at the agreed point.",
        )
        assert result["changed"] is True
        assert result["sender_refunded"] is True
        assert total_refunds(self.scenario.deal.pk) == money.collected_eur_cents
        deal = self.scenario.deal
        assert deal.no_show_party == Deal.NoShowParty.TRAVELER
        assert deal.no_show_recorded_by_id == self.scenario.admin.pk
        assert deal.status == Deal.Status.REFUNDED

    def test_a_sender_no_show_is_recorded_without_an_automatic_refund(self):
        record_no_show(
            deal_id=self.scenario.deal.pk,
            party=Deal.NoShowParty.SENDER,
            admin_actor_id=self.scenario.admin.pk,
        )
        assert total_refunds(self.scenario.deal.pk) == 0
        assert self.scenario.deal.no_show_party == Deal.NoShowParty.SENDER

    def test_recording_a_no_show_twice_changes_nothing(self):
        record_no_show(
            deal_id=self.scenario.deal.pk,
            party=Deal.NoShowParty.TRAVELER,
            admin_actor_id=self.scenario.admin.pk,
        )
        refunded = total_refunds(self.scenario.deal.pk)
        again = record_no_show(
            deal_id=self.scenario.deal.pk,
            party=Deal.NoShowParty.TRAVELER,
            admin_actor_id=self.scenario.admin.pk,
        )
        assert again["changed"] is False
        assert total_refunds(self.scenario.deal.pk) == refunded

    def test_a_no_show_cannot_be_recorded_after_pickup(self):
        confirm_pickup(self.scenario)
        with self.assertRaises(CancellationError) as caught:
            record_no_show(
                deal_id=self.scenario.deal.pk,
                party=Deal.NoShowParty.TRAVELER,
                admin_actor_id=self.scenario.admin.pk,
            )
        assert caught.exception.code == "pickup_already_confirmed"

    def test_an_unknown_party_is_refused(self):
        with self.assertRaises(CancellationError) as caught:
            record_no_show(
                deal_id=self.scenario.deal.pk,
                party="recipient",
                admin_actor_id=self.scenario.admin.pk,
            )
        assert caught.exception.code == "no_show_party_invalid"
