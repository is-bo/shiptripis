"""Money that has already left cannot be allocated again.

These are regressions for the worst defect found in the Phase 4 review: a Deal
whose payout had already been settled could be refunded in full to the sender,
paying the same euro to two people. Every step of the original reproduction was
reachable through shipped endpoints, and each half looked correct on its own —
the payout was legitimately released by a dispute resolution, and the refund was
legitimately computed from what the Deal had collected.

The fix is in two places and both are tested here: `plan_settlement` bounds
every refund by what the platform still holds rather than by what it once
collected, and a party can no longer open a second dispute after one has been
resolved.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase

from apps.deals.models import Deal
from apps.deals.tests.phase4_factories import delivered_scenario, rewind_deal
from apps.disputes.models import Dispute
from apps.disputes.services import DisputeError, open_dispute, resolve_dispute
from apps.finance.models import Payout
from apps.finance.services import complete_manual_payout
from apps.finance.settlement import (
    LedgerAccount,
    SettlementError,
    assert_deal_reconciles,
    plan_settlement,
    read_deal_money,
)
from apps.finance import ledger


class SettlementBoundsTests(TestCase):
    """`plan_settlement` arithmetic against money already paid out."""

    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="bounds")
        self.money = read_deal_money(self.scenario.deal)

    def test_a_deal_with_nothing_paid_out_is_fully_settleable(self):
        assert self.money.paid_out_eur_cents == 0
        assert self.money.settleable_eur_cents == self.money.collected_eur_cents

    def test_a_refund_may_not_exceed_what_the_platform_still_holds(self):
        collected = self.money.collected_eur_cents
        money = read_deal_money(self.scenario.deal)
        object.__setattr__(money, "paid_out_eur_cents", 2_000)

        assert money.settleable_eur_cents == collected - 2_000
        with self.assertRaises(SettlementError) as caught:
            plan_settlement(
                money=money,
                sender_refund_eur_cents=collected,
                traveler_payout_eur_cents=0,
            )
        assert caught.exception.code == "settlement_refund_out_of_range"

    def test_the_traveler_share_is_floored_at_what_they_were_already_sent(self):
        """A decision cannot un-send a bank transfer; it can only allocate the rest."""

        collected = self.money.collected_eur_cents
        money = read_deal_money(self.scenario.deal)
        object.__setattr__(money, "paid_out_eur_cents", 2_000)

        plan = plan_settlement(
            money=money,
            sender_refund_eur_cents=collected - 2_000,
            traveler_payout_eur_cents=0,
        )
        assert plan.traveler_payout_eur_cents == 2_000
        assert plan.sender_refund_eur_cents == collected - 2_000
        assert plan.platform_fee_eur_cents == 0
        assert (
            plan.sender_refund_eur_cents
            + plan.traveler_payout_eur_cents
            + plan.platform_fee_eur_cents
            == collected
        )

    def test_a_decision_the_platform_cannot_fund_is_refused_not_approximated(self):
        money = read_deal_money(self.scenario.deal)
        object.__setattr__(
            money, "paid_out_eur_cents", money.collected_eur_cents
        )
        with self.assertRaises(SettlementError) as caught:
            plan_settlement(
                money=money,
                sender_refund_eur_cents=1,
                traveler_payout_eur_cents=0,
            )
        assert caught.exception.code == "settlement_refund_out_of_range"

    def test_every_plan_still_sums_to_the_collected_total(self):
        collected = self.money.collected_eur_cents
        for paid_out in (0, 1, 500, 2_000, collected - 1, collected):
            money = read_deal_money(self.scenario.deal)
            object.__setattr__(money, "paid_out_eur_cents", paid_out)
            settleable = money.settleable_eur_cents
            # Only refunds the platform can actually fund. Asking for one it
            # cannot is the refusal tested above, not a reconciliation case.
            for refund in sorted({0, min(1, settleable), settleable}):
                plan = plan_settlement(
                    money=money, sender_refund_eur_cents=refund
                )
                assert (
                    plan.sender_refund_eur_cents
                    + plan.traveler_payout_eur_cents
                    + plan.platform_fee_eur_cents
                    == collected
                ), (paid_out, refund)
                assert plan.traveler_payout_eur_cents >= paid_out
                assert plan.platform_fee_eur_cents >= 0


class DoublePayRegressionTests(TestCase):
    """The original reproduction, end to end, through the real services."""

    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="dpay")
        self.deal = self.scenario.deal
        self.collected = read_deal_money(self.deal).collected_eur_cents

        # 1-3. A dispute inside the window, resolved in the traveler's favour.
        first = open_dispute(
            deal_id=self.deal.pk,
            actor_id=self.scenario.sender.pk,
            category=Dispute.Category.LATE,
            reason_text="Late, but it arrived.",
        )
        resolve_dispute(
            dispute_id=first.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.FULL_TRAVELER_PAYOUT,
        )
        # 4. The operator actually sends the money.
        payout = Payout.objects.get(deal_id=self.deal.pk)
        complete_manual_payout(
            payout_id=payout.pk,
            admin_actor_id=self.scenario.admin.pk,
            payout_currency="EUR",
            payout_amount_minor=int(payout.amount_eur_cents),
            reference="BANK-REF-1",
        )
        self.payout = Payout.objects.get(pk=payout.pk)
        assert self.payout.status == Payout.Status.PAID

    def test_the_deal_reports_the_money_that_has_left(self):
        money = read_deal_money(self.deal)
        assert money.paid_out_eur_cents == int(self.payout.amount_eur_cents)
        assert money.settleable_eur_cents == self.collected - money.paid_out_eur_cents

    def test_a_party_cannot_open_a_second_dispute_after_one_resolved(self):
        """Step 5 of the original reproduction, now closed."""

        with self.assertRaises(DisputeError) as caught:
            open_dispute(
                deal_id=self.deal.pk,
                actor_id=self.scenario.sender.pk,
                category=Dispute.Category.DAMAGED,
                reason_text="Actually it was damaged.",
            )
        assert caught.exception.code == "dispute_already_resolved"

    def test_an_admin_dispute_cannot_refund_money_already_paid_out(self):
        """Step 6, now refused rather than silently double-paying."""

        second = open_dispute(
            deal_id=self.deal.pk,
            actor_id=self.scenario.admin.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Escalated after the payout.",
            as_admin=True,
        )
        assert second.payout_already_settled is True

        with self.assertRaises(SettlementError) as caught:
            resolve_dispute(
                dispute_id=second.pk,
                admin_actor_id=self.scenario.admin.pk,
                resolution=Dispute.Resolution.FULL_SENDER_REFUND,
            )
        assert caught.exception.code == "settlement_refund_out_of_range"

    def test_nothing_left_the_platform_twice(self):
        try:
            second = open_dispute(
                deal_id=self.deal.pk,
                actor_id=self.scenario.admin.pk,
                category=Dispute.Category.DAMAGED,
                reason_text="Escalated after the payout.",
                as_admin=True,
            )
            resolve_dispute(
                dispute_id=second.pk,
                admin_actor_id=self.scenario.admin.pk,
                resolution=Dispute.Resolution.FULL_SENDER_REFUND,
            )
        except SettlementError:
            pass

        # The original defect ended with `traveler_payable` at +2000 -- the
        # books asserting the traveler owed the platform the reward back.
        payable = ledger.deal_balance(
            self.deal.pk, LedgerAccount.TRAVELER_PAYABLE
        )
        assert payable <= 0, payable
        assert assert_deal_reconciles(self.deal.pk)["net"] == 0

    def test_a_partial_recovery_out_of_the_platform_share_still_reconciles(self):
        """What the operator *can* still do automatically: refund the fee."""

        money = read_deal_money(self.deal)
        recoverable = money.settleable_eur_cents
        assert recoverable > 0

        second = open_dispute(
            deal_id=self.deal.pk,
            actor_id=self.scenario.admin.pk,
            category=Dispute.Category.DAMAGED,
            reason_text="Partial goodwill recovery.",
            as_admin=True,
        )
        resolve_dispute(
            dispute_id=second.pk,
            admin_actor_id=self.scenario.admin.pk,
            resolution=Dispute.Resolution.PARTIAL_SPLIT,
            sender_refund_eur_cents=recoverable,
            traveler_payout_eur_cents=0,
        )
        resolved = Dispute.objects.get(pk=second.pk)
        assert resolved.sender_refund_eur_cents == recoverable
        # The traveler's share is what they were actually sent, not zero.
        assert resolved.traveler_payout_eur_cents == money.paid_out_eur_cents
        assert (
            resolved.sender_refund_eur_cents
            + resolved.traveler_payout_eur_cents
            + resolved.platform_fee_eur_cents
            == self.collected
        )
        assert assert_deal_reconciles(self.deal.pk)["net"] == 0


class ReallocationLedgerTests(TestCase):
    """The compensating transaction reads the books, not the frozen price."""

    def test_a_second_settlement_does_not_re_release_the_same_liabilities(self):
        from apps.finance.models import PaymentRefund
        from apps.finance.settlement import apply_settlement

        scenario = delivered_scenario(self.client, prefix="realloc")
        deal = scenario.deal
        money = read_deal_money(deal)
        collected = money.collected_eur_cents

        plan = plan_settlement(
            money=money,
            sender_refund_eur_cents=collected,
            traveler_payout_eur_cents=0,
        )
        apply_settlement(
            plan=plan,
            settlement_key=f"probe_one:{deal.pk}",
            refund_reason=PaymentRefund.Reason.ADMIN,
            note="first",
            actor_id=scenario.admin.pk,
        )
        after_first = {
            account: ledger.deal_balance(deal.pk, account)
            for account in (
                LedgerAccount.DEAL_FUNDS,
                LedgerAccount.TRAVELER_PAYABLE,
                LedgerAccount.PLATFORM_COMMISSION,
            )
        }

        # A second settlement under a DIFFERENT key. Nothing is left to move,
        # so the reallocation must post nothing at all.
        second_money = read_deal_money(deal)
        assert second_money.collected_eur_cents == 0
        second_plan = plan_settlement(
            money=second_money,
            sender_refund_eur_cents=0,
            traveler_payout_eur_cents=0,
        )
        apply_settlement(
            plan=second_plan,
            settlement_key=f"probe_two:{deal.pk}",
            refund_reason=PaymentRefund.Reason.ADMIN,
            note="second",
            actor_id=scenario.admin.pk,
        )
        after_second = {
            account: ledger.deal_balance(deal.pk, account)
            for account in after_first
        }
        assert after_second == after_first, (after_first, after_second)
        assert assert_deal_reconciles(deal.pk)["net"] == 0


class ProtectionStillGatesTheOrdinaryPathTests(TestCase):
    """The fix must not have loosened the normal 48-hour gate."""

    def test_a_clean_deal_still_completes_and_pays_after_the_window(self):
        scenario = delivered_scenario(self.client, prefix="clean")
        from apps.finance.payout_release import evaluate_payout_release

        rewind_deal(scenario.deal, timedelta(hours=49))
        assert evaluate_payout_release(deal_id=scenario.deal.pk) == "released"
        payout = Payout.objects.get(deal_id=scenario.deal.pk)
        assert payout.status == Payout.Status.ELIGIBLE
        assert scenario.deal.status == Deal.Status.COMPLETED
