"""Phase 8F-H3 — automatic EUR payout execution, recovery and reconciliation.

The question every test here is really asking is the same one: *could this
system pay the same euro twice, or claim to have paid one it did not?*

So the assertions are mostly about two things. **External effects**, counted on
the fake provider's own call log rather than on local rows — "exactly one
Transfer was created" is a claim about what left the building. And **the
ledger**, which has to balance and has to put the money in the right place at
each stage: in the connected account after a Transfer, in transit after a bank
payout, and discharged from the Traveler payable only when Stripe says `paid`.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.deals.models import Deal
from apps.finance import ledger
from apps.finance.models import (
    FinanceHold,
    LedgerAccount,
    PaymentAttempt,
    PaymentRefund,
    Payout,
    PayoutAttempt,
    PayoutFundingAllocation,
    PayoutProviderOperation,
    ScheduledJob,
    StripeDisbursement,
    StripeDisbursementAllocation,
)
from apps.finance.payout_execution import (
    PayoutBlocked,
    PayoutDeferred,
    PayoutUnresolved,
    execute_payout,
    execution_enabled,
)
from apps.finance.payout_reconciliation import reconcile_payout
from apps.finance.services import RefundExceedsCapture, request_refund

from .payout_execution_harness import (
    BANK,
    CONNECTED,
    H3_SETTINGS,
    FakeConnect,
    authorise_auto_stripe,
    build_stripe_payout,
    timeout,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def h3():
    with override_settings(**H3_SETTINGS):
        yield


@pytest.fixture
def world(h3):
    authorise_auto_stripe(True)
    scenario, payout, account, capture = build_stripe_payout()
    return scenario, payout, account, capture


def drive(payout, gateway, *, times=1):
    """Run the worker's own entry point, the way the job does."""

    results = []
    for _ in range(times):
        results.append(execute_payout(payout.pk, gateway=gateway))
        payout.refresh_from_db()
    return results


def revise_award(payout, amount, *, reference="test-settlement"):
    """Cut an award through the real revision service, not by editing a row."""

    from django.db import transaction

    from apps.core.financial_locks import lock_deal_lifecycle
    from apps.finance.payout_domain import revise_amount_locked

    with transaction.atomic():
        lock_deal_lifecycle(payout.deal_id)
        locked = Payout.objects.select_for_update(no_key=True).get(pk=payout.pk)
        revise_amount_locked(
            locked,
            amount=amount,
            settlement_reference=reference,
            reason_code="settlement_award",
        )
    payout.refresh_from_db()
    return payout


def balances(deal_id):
    return {
        account: ledger.deal_balance(deal_id, account)
        for account in (
            LedgerAccount.PROVIDER_CLEARING,
            LedgerAccount.DEAL_FUNDS,
            LedgerAccount.TRAVELER_PAYABLE,
            LedgerAccount.PLATFORM_COMMISSION,
            LedgerAccount.CONNECT_FUNDS,
            LedgerAccount.PAYOUT_IN_TRANSIT,
            LedgerAccount.SENDER_DEPOSIT,
        )
    }


def assert_balanced(deal_id):
    """Every account for one Deal sums to zero. Money came from somewhere."""

    assert sum(balances(deal_id).values()) == 0


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------


class TestExecutionGates:
    def test_both_switches_are_required(self, h3):
        authorise_auto_stripe(False)
        assert execution_enabled() == (False, "auto_stripe_disabled")
        authorise_auto_stripe(True)
        assert execution_enabled() == (True, "")
        with override_settings(STRIPE_CONNECT_PAYOUTS_ENABLED=False):
            assert execution_enabled() == (False, "payout_execution_disabled")
        with override_settings(STRIPE_CONNECT_ENABLED=False):
            assert execution_enabled() == (False, "stripe_connect_disabled")
        with override_settings(PAYOUT_PROFILES_ENABLED=False):
            assert execution_enabled() == (False, "payout_profiles_disabled")

    def test_a_disabled_flag_defers_and_sends_nothing(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        with override_settings(STRIPE_CONNECT_PAYOUTS_ENABLED=False):
            with pytest.raises(PayoutDeferred) as caught:
                execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "payout_execution_disabled"
        assert gateway.calls == []

    def test_protection_still_open_defers(self, world):
        _, payout, _, _ = world
        Deal.objects.filter(pk=payout.deal_id).update(
            protection_ends_at=timezone.now() + timedelta(hours=6)
        )
        gateway = FakeConnect()
        with pytest.raises(PayoutDeferred) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "protection_open"
        assert gateway.calls == []

    def test_an_unready_account_defers_without_rerouting_to_dzd(self, world):
        _, payout, account, _ = world
        account.transfers_status = "inactive"
        account.save(update_fields=["transfers_status"])
        with pytest.raises(PayoutDeferred) as caught:
            execute_payout(payout.pk, gateway=FakeConnect())
        assert caught.value.code.startswith("account_")
        payout.refresh_from_db()
        assert payout.method == "stripe_transfer" and payout.payout_currency == "EUR"

    def test_a_finance_hold_blocks_dispatch(self, world):
        _, payout, _, _ = world
        FinanceHold.objects.create(
            payout=payout,
            kind="compliance",
            reason_code="under_review",
            source_reference="ref",
        )
        gateway = FakeConnect()
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "finance_hold_active"
        assert gateway.names("create_transfer") == []

    def test_a_sub_minimum_award_is_kept_owed_and_never_rounded(self, world):
        _, payout, _, _ = world
        # A settlement cut the award below Stripe's 1 EUR minimum for FR/EUR.
        # H0 forbids rounding it up, forfeiting it, or marking it paid.
        revise_award(payout, 50)
        gateway = FakeConnect(balance_available=50)
        assert drive(payout, gateway) == ["payout_below_minimum"]
        assert payout.status == "blocked"
        assert payout.block_reason == "payout_below_minimum"
        # Owed in full. Nothing was transferred and nothing was paid out, so the
        # money never left the platform to sit unreachable in a connected
        # account it could not be paid out of.
        assert payout.amount_eur_cents == 50
        assert gateway.names("create_transfer") == []
        assert gateway.names("create_bank_payout") == []
        # A re-run stays blocked rather than escalating into a failure.
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "payout_below_minimum"
        payout.refresh_from_db()
        assert payout.status == "blocked" and payout.amount_eur_cents == 50


# ---------------------------------------------------------------------------
# Source funding and charge identity
# ---------------------------------------------------------------------------


class TestSourceFunding:
    def test_the_charge_id_is_resolved_from_the_payment_intent_and_persisted(
        self, world
    ):
        _, payout, _, capture = world
        gateway = FakeConnect()
        drive(payout, gateway)
        capture.refresh_from_db()
        assert capture.provider_charge_id.startswith("ch_")
        sent = gateway.names("create_transfer")[0]
        assert sent.kwargs["source_transaction"] == capture.provider_charge_id
        assert not sent.kwargs["source_transaction"].startswith("pi_")

    def test_a_transfer_never_carries_a_payment_intent_id(self, world):
        _, payout, _, capture = world
        PaymentAttempt.objects.filter(pk=capture.pk).update(
            provider_payment_id="", provider_charge_id=""
        )
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=FakeConnect())
        assert caught.value.code == "source_charge_unresolved"

    def test_a_refunded_source_cannot_still_fund_the_obligation(self, world):
        _, payout, _, capture = world
        PaymentRefund.objects.create(
            order=capture.order,
            attempt=capture,
            amount_eur_cents=7000,
            provider="stripe",
            provider_mode="test",
            idempotency_key="refund-most-of-it",
            reason="admin",
            status="succeeded",
        )
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=FakeConnect())
        assert caught.value.code == "funding_route_unavailable"

    def test_a_live_reservation_is_not_borrowed_by_a_second_payout(self, world):
        _, payout, _, capture = world
        gateway = FakeConnect()
        drive(payout, gateway)
        from apps.finance.payout_domain import source_available_cents

        capture.refresh_from_db()
        # 7,500 captured, 6,000 reserved for this Traveler.
        assert source_available_cents(capture) == 1500

    def test_a_wrong_mode_charge_is_refused(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        gateway.charge_livemode = True
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "source_charge_ineligible"
        assert gateway.names("create_transfer") == []


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_transfer_then_bank_payout_then_paid(self, world):
        scenario, payout, _, _ = world
        gateway = FakeConnect()

        # 1. Reserve, commit, transfer.
        drive(payout, gateway)
        assert payout.status == "processing"
        attempt = payout.attempts.get()
        assert attempt.status == PayoutAttempt.Status.ACCEPTED
        transfer = gateway.names("create_transfer")[0]
        assert transfer.kwargs["amount_minor"] == 6000
        assert transfer.kwargs["destination"] == CONNECTED
        after_transfer = balances(payout.deal_id)
        assert after_transfer[LedgerAccount.CONNECT_FUNDS] == 6000
        # A Transfer is not a payment: the Traveler is still owed everything.
        assert after_transfer[LedgerAccount.TRAVELER_PAYABLE] == -6000
        assert_balanced(payout.deal_id)

        # 2. Bank payout.
        drive(payout, gateway)
        created = gateway.names("create_bank_payout")[0]
        assert created.kwargs["account_id"] == CONNECTED
        assert created.kwargs["destination"] == BANK
        assert created.kwargs["amount_minor"] == 6000
        disbursement = StripeDisbursement.objects.get()
        assert disbursement.status == StripeDisbursement.Status.PENDING
        payout.refresh_from_db()
        assert payout.status == "processing"
        in_transit_stage = balances(payout.deal_id)
        assert in_transit_stage[LedgerAccount.PAYOUT_IN_TRANSIT] == 6000
        assert in_transit_stage[LedgerAccount.CONNECT_FUNDS] == 0
        assert in_transit_stage[LedgerAccount.TRAVELER_PAYABLE] == -6000

        # 3. In transit is `sent`, not paid.
        gateway.payout_status = "in_transit"
        reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        assert payout.status == "sent" and payout.paid_at is None

        # 4. Only the provider's `paid` discharges the obligation.
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        assert payout.status == "paid"
        assert payout.paid_at and payout.settled_at
        assert payout.provider_payout_id.startswith("po_")
        final = balances(payout.deal_id)
        assert final[LedgerAccount.TRAVELER_PAYABLE] == 0
        assert final[LedgerAccount.PAYOUT_IN_TRANSIT] == 0
        assert_balanced(payout.deal_id)

    def test_no_stripe_fee_is_deducted_from_the_traveler(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        assert gateway.names("create_transfer")[0].kwargs["amount_minor"] == 6000
        assert gateway.names("create_bank_payout")[0].kwargs["amount_minor"] == 6000
        payout.refresh_from_db()
        assert payout.amount_eur_cents == 6000

    def test_the_transfer_group_and_metadata_carry_no_personal_data(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway)
        call = gateway.names("create_transfer")[0]
        blob = f"{call.kwargs['transfer_group']}{call.kwargs['metadata']}"
        assert "@" not in blob
        assert str(payout.traveler.email) not in blob
        assert set(call.kwargs["metadata"]) == {
            "shiptrip_operation",
            "shiptrip_payout",
            "shiptrip_env",
        }


# ---------------------------------------------------------------------------
# Fault injection
# ---------------------------------------------------------------------------


class TestAmbiguousResults:
    def test_a_timeout_becomes_unknown_and_keeps_its_reservation(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        gateway.fail["create_transfer"] = timeout()
        drive(payout, gateway)
        operation = PayoutProviderOperation.objects.get(kind="transfer_create")
        assert operation.status == "unknown"
        assert operation.failure_code == "timeout"  # Stripe's own reason, not ours
        assert PayoutFundingAllocation.objects.filter(release__isnull=True).count() == 1
        payout.refresh_from_db()
        assert payout.status == "processing"

    def test_recovery_replays_the_same_key_and_creates_one_transfer(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        gateway.fail["create_transfer"] = timeout()
        drive(payout, gateway)
        first_key = gateway.names("create_transfer")[0].kwargs["idempotency_key"]

        drive(payout, gateway)
        attempts = gateway.names("create_transfer")
        assert len(attempts) == 2
        assert attempts[1].kwargs["idempotency_key"] == first_key
        # Stripe's idempotency returns the original object, so exactly one
        # Transfer exists externally and exactly one ledger posting was made.
        assert len(gateway.transfers) == 1
        assert balances(payout.deal_id)[LedgerAccount.CONNECT_FUNDS] == 6000
        assert_balanced(payout.deal_id)

    def test_a_transfer_created_before_the_timeout_is_not_created_twice(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()

        class LateTimeout(FakeConnect):
            pass

        # Stripe created the Transfer and the answer was lost on the way back.
        original = gateway.create_transfer

        def create_then_lose(**kwargs):
            original(**kwargs)
            raise timeout()

        gateway.create_transfer = create_then_lose
        drive(payout, gateway)
        assert len(gateway.transfers) == 1
        operation = PayoutProviderOperation.objects.get(kind="transfer_create")
        assert operation.status == "unknown"

        gateway.create_transfer = original
        drive(payout, gateway)
        assert len(gateway.transfers) == 1
        operation.refresh_from_db()
        assert operation.status == "accepted"
        assert operation.provider_object_id == "tr_1"
        assert_balanced(payout.deal_id)

    def test_past_the_replay_window_a_search_resolves_it(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        original = gateway.create_transfer

        def create_then_lose(**kwargs):
            original(**kwargs)
            raise timeout()

        gateway.create_transfer = create_then_lose
        drive(payout, gateway)
        PayoutProviderOperation.objects.filter(kind="transfer_create").update(
            first_request_at=timezone.now() - timedelta(hours=30)
        )
        gateway.create_transfer = original
        drive(payout, gateway)
        assert gateway.names("find_transfer_by_metadata")
        # No second create was attempted past the window.
        assert len(gateway.names("create_transfer")) == 1
        assert PayoutProviderOperation.objects.get(
            kind="transfer_create"
        ).status == "accepted"

    def test_an_unprovable_absence_blocks_rather_than_resending(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        gateway.fail["create_transfer"] = timeout()
        drive(payout, gateway)
        PayoutProviderOperation.objects.filter(kind="transfer_create").update(
            first_request_at=timezone.now() - timedelta(hours=30)
        )
        with pytest.raises(PayoutUnresolved) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "transfer_unresolved"
        assert len(gateway.names("create_transfer")) == 1
        assert PayoutFundingAllocation.objects.filter(release__isnull=True).count() == 1

    def test_a_definitive_rejection_releases_the_reservation(self, world):
        _, payout, _, capture = world
        from apps.finance.providers.base import ProviderCheckoutRejected

        gateway = FakeConnect()
        gateway.fail["create_transfer"] = ProviderCheckoutRejected(
            "no such destination", provider_code="account_invalid"
        )
        drive(payout, gateway)
        payout.refresh_from_db()
        assert payout.status == "failed"
        allocation = PayoutFundingAllocation.objects.get()
        assert hasattr(allocation, "release")
        from apps.finance.payout_domain import source_available_cents

        capture.refresh_from_db()
        assert source_available_cents(capture) == 7500
        assert balances(payout.deal_id)[LedgerAccount.CONNECT_FUNDS] == 0

    def test_a_crash_between_reserve_and_commit_resumes_the_same_intent(self, world):
        _, payout, _, _ = world
        from apps.finance.payout_execution import _reserve_dispatch, _resolve_charges

        gateway = FakeConnect()
        charges = _resolve_charges(payout.pk, gateway=gateway)
        plan = _reserve_dispatch(payout.pk, charges)
        payout.refresh_from_db()
        assert payout.status == "scheduled"
        assert gateway.names("create_transfer") == []

        drive(payout, gateway)
        assert PayoutAttempt.objects.count() == 1
        assert PayoutAttempt.objects.get().pk == plan.attempt_id
        assert len(gateway.names("create_transfer")) == 1


class TestBankPayoutFailure:
    def _to_bank_stage(self, payout, gateway):
        drive(payout, gateway, times=2)
        return StripeDisbursement.objects.get()

    def test_a_failed_bank_payout_never_recreates_the_transfer(self, world):
        self._scenario, payout, _, _ = world
        gateway = FakeConnect()
        self._to_bank_stage(payout, gateway)
        gateway.payout_status = "failed"
        reconcile_payout(payout.pk, gateway=gateway)

        payout.refresh_from_db()
        assert payout.status == "failed"
        # The funding transfer stands: its money is at the connected account.
        assert payout.attempts.get().status == PayoutAttempt.Status.ACCEPTED
        state = balances(payout.deal_id)
        assert state[LedgerAccount.CONNECT_FUNDS] == 6000
        assert state[LedgerAccount.PAYOUT_IN_TRANSIT] == 0
        assert state[LedgerAccount.TRAVELER_PAYABLE] == -6000
        assert_balanced(payout.deal_id)

        # Nothing automatic picks it back up: a failed bank payout is a broken
        # destination, and retrying it on a timer would hammer Stripe against
        # the same unusable account.
        assert payout.block_reason
        with pytest.raises(PayoutBlocked):
            execute_payout(payout.pk, gateway=gateway)
        assert len(gateway.names("create_bank_payout")) == 1

        # An operator authorises the retry, and it acts on the bank stage only.
        from apps.finance.payout_execution import admin_retry_bank_payout

        scenario = self._scenario
        gateway.payout_status = "pending"
        admin_retry_bank_payout(
            actor=scenario.admin,
            payout_id=payout.pk,
            expected_state_version=payout.state_version,
        )
        drive(payout, gateway)
        assert len(gateway.names("create_transfer")) == 1
        assert len(gateway.names("create_bank_payout")) == 2
        assert StripeDisbursement.objects.count() == 2
        assert (
            StripeDisbursementAllocation.objects.filter(active=True).count() == 1
        )

    def test_a_definitive_bank_rejection_leaves_the_money_at_the_account(self, world):
        _, payout, _, _ = world
        from apps.finance.providers.base import ProviderCheckoutRejected

        gateway = FakeConnect()
        drive(payout, gateway)
        gateway.fail["create_bank_payout"] = ProviderCheckoutRejected(
            "no such external account", provider_code="invalid_request_error"
        )
        drive(payout, gateway)
        payout.refresh_from_db()
        assert payout.status == "failed"
        assert StripeDisbursement.objects.get().status == "failed"
        state = balances(payout.deal_id)
        assert state[LedgerAccount.CONNECT_FUNDS] == 6000
        assert state[LedgerAccount.PAYOUT_IN_TRANSIT] == 0
        assert_balanced(payout.deal_id)

    def test_a_late_return_after_paid_preserves_history_and_restores_the_debt(
        self, world
    ):
        _, payout, _, _ = world
        gateway = FakeConnect()
        self._to_bank_stage(payout, gateway)
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        paid_at = payout.paid_at
        assert payout.status == "paid" and paid_at is not None
        assert balances(payout.deal_id)[LedgerAccount.TRAVELER_PAYABLE] == 0

        gateway.payout_status = "failed"
        reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        disbursement = StripeDisbursement.objects.get()
        assert disbursement.status == "returned"
        assert disbursement.paid_at is not None  # the paid fact is preserved
        assert payout.status == "failed"
        assert payout.paid_at == paid_at  # history, not rewritten
        state = balances(payout.deal_id)
        assert state[LedgerAccount.TRAVELER_PAYABLE] == -6000
        assert state[LedgerAccount.CONNECT_FUNDS] == 6000
        assert_balanced(payout.deal_id)
        # Both the settlement and its reversal are on the timeline.
        reasons = list(payout.events.values_list("reason_code", flat=True))
        assert "bank_payout_paid" in reasons and "bank_payout_returned" in reasons

    def test_insufficient_connected_balance_defers_without_failing(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect(balance_available=10)
        drive(payout, gateway)
        with pytest.raises(PayoutDeferred) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "connected_balance_pending"
        assert gateway.names("create_bank_payout") == []
        payout.refresh_from_db()
        assert payout.status == "processing"


# ---------------------------------------------------------------------------
# Races
# ---------------------------------------------------------------------------


class TestRaces:
    def test_a_dispute_before_dispatch_refuses_it(self, world):
        """Scenario A: the dispute commits first. Nothing may be sent."""

        scenario, payout, _, _ = world
        from apps.disputes.models import Dispute

        Dispute.objects.create(
            deal=scenario.deal,
            opened_by=scenario.sender,
            category=Dispute.Category.NOT_DELIVERED,
            reason_text="Nothing arrived at all.",
            status=Dispute.Status.OPEN,
        )
        gateway = FakeConnect()
        with pytest.raises(PayoutBlocked) as caught:
            execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "dispute_active"
        assert gateway.names("create_transfer") == []

    def test_a_dispute_after_commitment_records_the_exposure(self, world):
        """Scenario B: the dispatch commitment wins.

        The freeze still happens and still stops the *next* stage, but it does
        not pretend the platform still holds the money. No database can recall
        a Transfer Stripe has accepted.
        """

        scenario, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway)

        from django.db import transaction

        from apps.core.financial_locks import lock_deal_lifecycle
        from apps.finance.payout_release import freeze_payout

        with transaction.atomic():
            aggregate = lock_deal_lifecycle(scenario.deal.pk)
            freeze_payout(aggregate, reason="dispute_opened_after_dispatch")
        payout.refresh_from_db()
        assert payout.status == "frozen"
        assert "already committed" in payout.notes
        # The next stage is refused; the previous one is not pretended away.
        with pytest.raises(PayoutBlocked):
            execute_payout(payout.pk, gateway=gateway)
        assert gateway.names("create_bank_payout") == []
        assert balances(payout.deal_id)[LedgerAccount.CONNECT_FUNDS] == 6000

    def test_a_committed_payout_cannot_also_fund_a_refund(self, world):
        _, payout, _, capture = world
        gateway = FakeConnect()
        drive(payout, gateway)
        with pytest.raises(RefundExceedsCapture) as caught:
            request_refund(
                order_id=capture.order_id,
                attempt_id=capture.pk,
                amount_eur_cents=7000,
                reason="admin",
                requested_by_id=None,
                idempotency_key="race-refund",
            )
        assert caught.value.details()["reserved_for_payout_eur_cents"] == 6000
        # What is genuinely spare stays refundable.
        refund = request_refund(
            order_id=capture.order_id,
            attempt_id=capture.pk,
            amount_eur_cents=1500,
            reason="admin",
            requested_by_id=None,
            idempotency_key="race-refund-ok",
        )
        assert refund.amount_eur_cents == 1500

    def test_a_settlement_cannot_reassign_committed_money(self, world):
        scenario, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway)
        from apps.finance.settlement import read_deal_money

        money = read_deal_money(scenario.deal)
        assert money.paid_out_eur_cents == 6000
        assert money.settleable_eur_cents == money.collected_eur_cents - 6000

    def test_two_workers_do_not_both_dispatch(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway)
        # A second worker arriving on the same payout finds the attempt already
        # accepted and moves to the next stage rather than transferring again.
        drive(payout, gateway)
        assert len(gateway.names("create_transfer")) == 1
        assert PayoutAttempt.objects.count() == 1


# ---------------------------------------------------------------------------
# Reconciliation convergence
# ---------------------------------------------------------------------------


class TestConvergence:
    def test_a_repeated_observation_posts_the_ledger_once(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "paid"
        for _ in range(3):
            reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        assert payout.status == "paid"
        assert balances(payout.deal_id)[LedgerAccount.TRAVELER_PAYABLE] == 0
        assert_balanced(payout.deal_id)

    def test_an_older_observation_cannot_regress_a_newer_one(self, world):
        _, payout, _, _ = world
        from apps.finance.payout_reconciliation import apply_bank_payout_observation

        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        disbursement = StripeDisbursement.objects.get()
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)

        stale = gateway.retrieve_bank_payout(
            account_id=CONNECTED, payout_id=disbursement.provider_payout_id
        )
        from dataclasses import replace

        note = apply_bank_payout_observation(
            StripeDisbursement.objects.get(),
            replace(stale, status="pending"),
            observed_at=timezone.now() - timedelta(hours=1),
        )
        assert note == "superseded_by_newer_observation"
        assert StripeDisbursement.objects.get().status == "paid"

    def test_reconciliation_runs_with_execution_switched_off(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "paid"
        with override_settings(STRIPE_CONNECT_PAYOUTS_ENABLED=False):
            reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        assert payout.status == "paid"


# ---------------------------------------------------------------------------
# Jobs and the sweeper
# ---------------------------------------------------------------------------


class TestWorker:
    def test_release_arms_the_execution_job_with_no_admin_click(self, h3):
        authorise_auto_stripe(True)
        _, payout, _, _ = build_stripe_payout(
            prefix="arm", protection_expired=True
        )
        Payout.objects.filter(pk=payout.pk).update(
            status="not_eligible", eligible_at=None, eligibility_basis=""
        )
        from apps.finance.payout_release import evaluate_payout_release

        assert evaluate_payout_release(deal_id=payout.deal_id) == "payout_eligible"
        assert ScheduledJob.objects.filter(
            kind="payout_execute", key=f"payout_execute:{payout.pk}"
        ).exists()

    def test_a_deferred_wait_does_not_consume_the_retry_budget(self, world):
        _, payout, _, _ = world
        from apps.finance.jobs import handle_payout_execute, run_job

        Deal.objects.filter(pk=payout.deal_id).update(
            protection_ends_at=timezone.now() + timedelta(hours=6)
        )
        job = ScheduledJob.objects.create(
            key=f"payout_execute:{payout.pk}",
            kind=ScheduledJob.Kind.PAYOUT_EXECUTE,
            payload={"payout_id": payout.pk},
            run_at=timezone.now(),
        )
        assert run_job(job) == "deferred"
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.PENDING
        assert job.attempts == 0
        assert job.last_result.startswith("deferred:protection_open")
        assert handle_payout_execute is not None

    def test_an_unresolved_operation_is_terminal_not_retried(self, world):
        _, payout, _, _ = world
        from apps.finance.jobs import run_job

        gateway = FakeConnect()
        gateway.fail["create_transfer"] = timeout()
        drive(payout, gateway)
        PayoutProviderOperation.objects.filter(kind="transfer_create").update(
            first_request_at=timezone.now() - timedelta(hours=30)
        )
        job = ScheduledJob.objects.create(
            key=f"payout_execute:{payout.pk}",
            kind=ScheduledJob.Kind.PAYOUT_EXECUTE,
            payload={"payout_id": payout.pk},
            run_at=timezone.now(),
        )
        import apps.finance.payout_execution as execution

        original = execution.get_connect_gateway
        execution.get_connect_gateway = lambda **kwargs: gateway
        try:
            assert run_job(job) == "failed"
        finally:
            execution.get_connect_gateway = original
        job.refresh_from_db()
        assert job.last_error_code == "transfer_unresolved"
        # Terminal, not retried: a second POST is exactly what must not happen.
        assert job.status == ScheduledJob.Status.FAILED
        assert len(gateway.names("create_transfer")) == 1

    def test_the_sweeper_rearms_lost_work(self, world):
        _, payout, _, _ = world
        from apps.finance.payout_sweeper import sweep_payouts

        ScheduledJob.objects.all().delete()
        report = sweep_payouts()
        assert report["execute"] >= 1
        assert ScheduledJob.objects.filter(
            kind="payout_execute", key=f"payout_execute:{payout.pk}"
        ).exists()

    def test_the_sweeper_revives_a_job_that_already_ran(self, world):
        """A payout whose job succeeded by saying "still blocked" must be re-checked.

        `schedule_job` leaves a succeeded job alone, which is right for a
        one-shot obligation and wrong for a payout waiting on a condition that
        may resolve later. Without this the payout is armed once and then falls
        out of the queue silently.
        """

        _, payout, _, _ = world
        from apps.finance.payout_sweeper import sweep_payouts

        ScheduledJob.objects.all().delete()
        sweep_payouts()
        job = ScheduledJob.objects.get(key=f"payout_execute:{payout.pk}")
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.SUCCEEDED,
            run_at=timezone.now() - timedelta(hours=1),
            completed_at=timezone.now(),
        )
        assert sweep_payouts()["execute"] >= 1
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.PENDING

    def test_the_sweeper_does_not_shorten_a_deliberate_wait(self, world):
        _, payout, _, _ = world
        from apps.finance.payout_sweeper import sweep_payouts

        ScheduledJob.objects.all().delete()
        sweep_payouts()
        job = ScheduledJob.objects.get(key=f"payout_execute:{payout.pk}")
        later = timezone.now() + timedelta(hours=6)
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.SUCCEEDED, run_at=later, completed_at=timezone.now()
        )
        sweep_payouts()
        job.refresh_from_db()
        assert job.status == ScheduledJob.Status.SUCCEEDED

    def test_the_sweeper_rearms_reconciliation_with_execution_off(self, world):
        _, payout, _, _ = world
        from apps.finance.payout_sweeper import sweep_payouts

        drive(payout, FakeConnect())
        ScheduledJob.objects.filter(kind__startswith="payout_").delete()
        with override_settings(STRIPE_CONNECT_PAYOUTS_ENABLED=False):
            report = sweep_payouts()
        assert report["execute"] == 0
        assert report["reconcile"] >= 1


# ---------------------------------------------------------------------------
# Provider events
# ---------------------------------------------------------------------------


class TestProviderEvents:
    def _record(self, event_type, obj, *, account=""):
        from apps.finance.models import PaymentProvider, PaymentProviderEvent

        payload = {
            "id": f"evt_{event_type}",
            "type": event_type,
            "livemode": False,
            "account": account,
            "data": {"object": obj},
        }
        return PaymentProviderEvent.objects.create(
            provider=PaymentProvider.STRIPE,
            provider_event_id=payload["id"],
            provider_mode="test",
            event_type=event_type,
            payload=payload,
            signature_verified=True,
        )

    def test_a_provider_dispute_opens_a_hold_that_blocks_dispatch(self, world):
        scenario, payout, _, capture = world
        from apps.finance.payout_provider_events import handle_platform_event

        PaymentAttempt.objects.filter(pk=capture.pk).update(
            provider_charge_id="ch_disputed"
        )
        gateway = FakeConnect()
        gateway.dispute_detail = {
            "id": "dp_1",
            "charge": "ch_disputed",
            "payment_intent": "",
            "amount": 7500,
            "currency": "EUR",
            "status": "needs_response",
            "livemode": False,
        }
        record = self._record("charge.dispute.created", {"id": "dp_1", "object": "dispute"})
        import apps.finance.payout_provider_events as module

        module.get_connect_gateway = lambda: gateway
        try:
            assert handle_platform_event(record) == "provider_dispute_held"
            assert FinanceHold.objects.filter(
                kind="provider_dispute", cleared_at__isnull=True
            ).exists()
            with pytest.raises(PayoutBlocked):
                execute_payout(payout.pk, gateway=FakeConnect())

            # Closing this dispute clears only this dispute's own hold.
            FinanceHold.objects.create(
                deal_id=scenario.deal.pk,
                kind="compliance",
                reason_code="separate_review",
                source_reference="other",
            )
            gateway.dispute_detail["status"] = "won"
            closed = self._record(
                "charge.dispute.closed", {"id": "dp_1", "object": "dispute"}
            )
            assert handle_platform_event(closed).startswith("provider_dispute_cleared")
            assert FinanceHold.objects.filter(
                kind="compliance", cleared_at__isnull=True
            ).exists()
        finally:
            from apps.finance.providers.stripe_connect import get_connect_gateway

            module.get_connect_gateway = get_connect_gateway

    def test_an_external_refund_holds_the_source_without_double_refunding(self, world):
        _, payout, _, capture = world
        from apps.finance.payout_provider_events import handle_platform_event
        import apps.finance.payout_provider_events as module

        PaymentAttempt.objects.filter(pk=capture.pk).update(
            provider_charge_id="ch_external"
        )
        gateway = FakeConnect()
        gateway.refund_detail = {
            "id": "re_1",
            "charge": "ch_external",
            "payment_intent": "",
            "amount": 1000,
            "currency": "EUR",
            "status": "succeeded",
            "livemode": False,
        }
        module.get_connect_gateway = lambda: gateway
        try:
            record = self._record(
                "refund.created", {"id": "re_1", "object": "refund"}
            )
            assert handle_platform_event(record) == "external_refund_held"
        finally:
            from apps.finance.providers.stripe_connect import get_connect_gateway

            module.get_connect_gateway = get_connect_gateway
        assert PaymentRefund.objects.count() == 0
        assert FinanceHold.objects.filter(
            kind="refund", cleared_at__isnull=True
        ).exists()
        with pytest.raises(PayoutBlocked):
            execute_payout(payout.pk, gateway=FakeConnect())

    def test_an_unexpected_connected_payout_quarantines_the_account(self, world):
        _, payout, account, _ = world
        import apps.finance.payout_provider_events as module
        from apps.finance.payout_provider_events import handle_connect_payout_event

        gateway = FakeConnect()
        gateway.payouts["external"] = gateway._payout_snapshot("po_outside", 9999)
        module.get_connect_gateway = lambda: gateway
        try:
            note = handle_connect_payout_event(
                {"data": {"object": {"id": "po_outside", "object": "payout"}}},
                CONNECTED,
            )
        finally:
            from apps.finance.providers.stripe_connect import get_connect_gateway

            module.get_connect_gateway = get_connect_gateway
        assert note == "unexpected_dashboard_payout"
        assert FinanceHold.objects.filter(
            account=account, kind="compliance", cleared_at__isnull=True
        ).exists()

    def test_the_payout_events_are_spelled_the_way_stripe_spells_them(self):
        from apps.finance.connect_webhooks import PAYOUT_EVENTS
        from apps.finance.payout_provider_events import (
            CONNECT_PAYOUT_EVENTS,
            PLATFORM_PAYOUT_EVENTS,
        )

        assert "payout.canceled" in PAYOUT_EVENTS  # one `l`, Stripe's spelling
        assert "payout.cancelled" not in PAYOUT_EVENTS
        assert PAYOUT_EVENTS == CONNECT_PAYOUT_EVENTS
        assert {"transfer.created", "transfer.reversed"} <= PLATFORM_PAYOUT_EVENTS
        assert "transfer.paid" not in PLATFORM_PAYOUT_EVENTS
        assert "transfer.failed" not in PLATFORM_PAYOUT_EVENTS


# ---------------------------------------------------------------------------
# Mode isolation
# ---------------------------------------------------------------------------


class TestModeIsolation:
    def test_a_test_obligation_is_not_dispatched_by_a_live_deployment(self, world):
        """The dangerous direction, stated the way it would actually happen.

        Nobody edits a payout's mode. What happens is that a deployment's
        credentials and expected mode move to live while TEST obligations are
        still in the table — and those must never be settled with real money.
        """

        _, payout, _, _ = world
        gateway = FakeConnect()
        with override_settings(STRIPE_CONNECT_EXPECTED_MODE="live"):
            with pytest.raises(PayoutBlocked) as caught:
                execute_payout(payout.pk, gateway=gateway)
        assert caught.value.code == "mode"
        assert gateway.calls == []

    def test_the_database_refuses_to_rewrite_a_funded_payout_mode(self, world):
        """H1's snapshot guard, which is what makes the rule above unbypassable.

        Only asserted on PostgreSQL: the guard is a trigger, and SQLite has no
        trigger to refuse with. This exact `update()` passed silently on SQLite
        and was rejected by the real database, which is why the concurrency and
        constraint tiers are not optional.
        """

        from django.db import DatabaseError, connection

        if connection.vendor != "postgresql":
            pytest.skip("The snapshot guard is a PostgreSQL trigger.")
        _, payout, _, _ = world
        with pytest.raises(DatabaseError):
            Payout.objects.filter(pk=payout.pk).update(provider_mode="live")

    def test_every_execution_row_carries_the_deployment_mode(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        assert set(
            PayoutProviderOperation.objects.values_list("provider_mode", flat=True)
        ) == {"test"}
        assert StripeDisbursement.objects.get().provider_mode == "test"
        assert PayoutFundingAllocation.objects.get().provider_mode == "test"


# ---------------------------------------------------------------------------
# Admin surface
# ---------------------------------------------------------------------------


class TestAdminSurface:
    def test_there_is_no_mark_paid_on_the_stripe_rail(self, world):
        _, payout, _, _ = world
        from apps.finance.services import PayoutNotReleasable, complete_manual_payout

        with pytest.raises(PayoutNotReleasable):
            complete_manual_payout(
                payout_id=payout.pk,
                admin_actor_id=payout.traveler_id,
                payout_currency="EUR",
                payout_amount_minor=6000,
                reference="hand-made",
            )

    def test_each_recovery_action_needs_its_own_capability(self, world):
        """A capability is not a role. Ops seeing a payout is not Ops paying one."""

        from django.core.exceptions import PermissionDenied

        from apps.admin_panel.permissions import assign_admin_roles
        from apps.finance.payout_execution import (
            admin_flag_unresolved_operation,
            admin_refresh_payout,
            admin_retry_bank_payout,
        )

        scenario, payout, _, _ = world
        assign_admin_roles(scenario.admin, ["support"])
        for call in (
            lambda: admin_refresh_payout(actor=scenario.admin, payout_id=payout.pk),
            lambda: admin_retry_bank_payout(
                actor=scenario.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            ),
            lambda: admin_flag_unresolved_operation(
                actor=scenario.admin, payout_id=payout.pk, reason="review"
            ),
        ):
            with pytest.raises(PermissionDenied):
                call()

    def test_a_retry_is_refused_while_an_operation_is_unresolved(self, world):
        scenario, payout, _, _ = world
        from apps.finance.payout_execution import admin_retry_bank_payout

        gateway = FakeConnect()
        gateway.fail["create_transfer"] = timeout()
        drive(payout, gateway)
        Payout.objects.filter(pk=payout.pk).update(status="failed")
        payout.refresh_from_db()
        with pytest.raises(PayoutBlocked) as caught:
            admin_retry_bank_payout(
                actor=scenario.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            )
        assert caught.value.code == "operation_unresolved"

    def test_a_retry_needs_the_current_state_version(self, world):
        scenario, payout, _, _ = world
        from apps.finance.payout_execution import admin_retry_bank_payout

        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "failed"
        reconcile_payout(payout.pk, gateway=gateway)
        payout.refresh_from_db()
        with pytest.raises(PayoutBlocked) as caught:
            admin_retry_bank_payout(
                actor=scenario.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version - 1,
            )
        assert caught.value.code == "state_conflict"
        assert (
            admin_retry_bank_payout(
                actor=scenario.admin,
                payout_id=payout.pk,
                expected_state_version=payout.state_version,
            )
            == "bank_payout_retry_armed"
        )


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------


class TestNotifications:
    def test_no_provider_identifier_reaches_a_notification(self, world):
        _, payout, _, _ = world
        from apps.notifications.models import OutboundMessage

        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        messages = list(
            OutboundMessage.objects.filter(kind=OutboundMessage.Kind.PAYOUT_STATUS)
        )
        assert messages
        blob = "".join(str(message.context) for message in messages)
        for forbidden in ("acct_", "tr_", "po_", "ch_", "ba_"):
            assert forbidden not in blob
        # Email stays disabled: the obligation is recorded, not dispatched.
        assert all(
            message.status != OutboundMessage.Status.DISPATCHED for message in messages
        )

    def test_every_state_change_leaves_a_durable_event(self, world):
        _, payout, _, _ = world
        gateway = FakeConnect()
        drive(payout, gateway, times=2)
        gateway.payout_status = "paid"
        reconcile_payout(payout.pk, gateway=gateway)
        reasons = list(payout.events.order_by("sequence").values_list(
            "reason_code", flat=True
        ))
        assert "dispatch_reserved" in reasons
        assert "dispatch_committed" in reasons
        assert "transfer_accepted" in reasons
        assert "bank_payout_submitted" in reasons
        assert "bank_payout_paid" in reasons
