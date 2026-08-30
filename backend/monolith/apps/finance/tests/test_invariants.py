"""Adversarial tests against the financial state machine.

Each test here is an attempt to reach a state that must be unreachable: a free
funded Deal, a double-funded Deal, a refund larger than the payment, a deposit
credited twice, money created by a duplicate webhook. They are written as
attacks rather than as happy paths, because a state machine that has never been
attacked has only been described.

Where an invariant is enforced at more than one level, the test says which
level caught it — service guard, recomputation, or database constraint — so a
later refactor that removes one layer fails loudly here.
"""

from __future__ import annotations

from copy import deepcopy

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.test import TestCase
from django.urls import reverse

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealLegAllocation
from apps.finance import ledger
from apps.finance.ledger import Leg, UnbalancedLedgerTransaction
from apps.finance.models import (
    LedgerAccount,
    LedgerEntry,
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    Payout,
    ScheduledJob,
)
from apps.finance.services import (
    RefundExceedsCapture,
    apply_posting_deposit_credit,
    ensure_posting_deposit_order,
    reconcile_attempt,
    request_refund,
)

from .factories import (
    build_scenario,
    deliver_mock_webhook,
    mock_event_body,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)


def _enable_mock():
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class FinanceStateAttackTests(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="attack")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()

    # --- free / double funding -------------------------------------------

    def test_a_deal_cannot_be_funded_without_a_covered_order(self):
        """Nothing but a covered PaymentOrder reaches the funding service."""

        assert self.scenario.deal.status == Deal.Status.PAYMENT_REQUIRED
        assert self.order.outstanding_eur_cents > 0

        from apps.finance.services import _fund_deal_if_covered

        assert _fund_deal_if_covered(self.order) is False
        self.scenario.deal.refresh_from_db()
        assert self.scenario.deal.status == Deal.Status.PAYMENT_REQUIRED

    def test_a_duplicate_success_event_cannot_fund_twice(self):
        attempt = open_mock_checkout(self.order)
        body = succeed_attempt(attempt, event_id="evt_dup")

        first = deliver_mock_webhook(self.client, body)
        second = deliver_mock_webhook(self.client, body)
        third = deliver_mock_webhook(self.client, body)

        assert first.status_code == 200
        assert second.json()["duplicate"] is True
        assert third.json()["duplicate"] is True

        self.order.refresh_from_db()
        self.scenario.deal.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.scenario.deal.status == Deal.Status.FUNDED
        assert PaymentProviderEvent.objects.filter(provider_event_id="evt_dup").count() == 1
        assert (
            LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        )
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1

    def test_two_distinct_success_events_on_one_attempt_do_not_double_credit(self):
        """Different event ids, same underlying payment: money counted once."""

        attempt = open_mock_checkout(self.order)
        deliver_mock_webhook(self.client, succeed_attempt(attempt, event_id="evt_a"))
        deliver_mock_webhook(self.client, succeed_attempt(attempt, event_id="evt_b"))

        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.outstanding_eur_cents == 0
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1

    def test_a_second_succeeded_attempt_becomes_unapplied_and_is_refunded(self):
        """The residual double-pay race: real money, but not a second funding."""

        first = open_mock_checkout(self.order)
        deliver_mock_webhook(self.client, succeed_attempt(first, event_id="evt_1"))

        # Simulate a checkout the customer completed after we moved on.
        second = PaymentAttempt.objects.create(
            order=self.order,
            provider="mock",
            payer_id=self.scenario.sender.pk,
            amount_eur_cents=first.amount_eur_cents,
            payment_currency="EUR",
            provider_amount_minor=first.provider_amount_minor,
            provider_amount_exponent=2,
            idempotency_key="second-race-key",
            provider_session_id="mock_cs_race",
            status=PaymentAttempt.Status.CHECKOUT_PENDING,
        )
        deliver_mock_webhook(
            self.client, succeed_attempt(second, event_id="evt_2")
        )

        self.order.refresh_from_db()
        second.refresh_from_db()
        assert second.status == PaymentAttempt.Status.SUCCEEDED
        assert second.is_unapplied is True
        # The order is paid exactly once.
        assert self.order.paid_eur_cents == int(first.amount_eur_cents)
        assert PaymentRefund.objects.filter(
            attempt=second, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
        ).exists()
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.FUNDED

    def test_the_database_refuses_an_over_collected_order(self):
        """Even bypassing every service, the constraint holds."""

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.filter(pk=self.order.pk).update(
                    paid_eur_cents=int(self.order.amount_eur_cents) + 1
                )

    def test_the_database_refuses_a_credit_that_exceeds_the_obligation(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.filter(pk=self.order.pk).update(
                    credited_eur_cents=int(self.order.amount_eur_cents) + 1
                )

    # --- refunds ----------------------------------------------------------

    def test_a_refund_cannot_exceed_the_captured_amount(self):
        attempt = pay_order_with_mock(self.client, self.order)

        with self.assertRaises(RefundExceedsCapture) as caught:
            request_refund(
                order_id=self.order.pk,
                attempt_id=attempt.pk,
                amount_eur_cents=int(attempt.amount_eur_cents) + 1,
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        assert caught.exception.code == "refund_exceeds_capture"
        assert caught.exception.details()["captured_eur_cents"] == int(
            attempt.amount_eur_cents
        )

    def test_two_partial_refunds_cannot_together_exceed_the_capture(self):
        attempt = pay_order_with_mock(self.client, self.order)
        half = int(attempt.amount_eur_cents) // 2

        request_refund(
            order_id=self.order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=half,
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key="partial-1",
        )
        with self.assertRaises(RefundExceedsCapture):
            request_refund(
                order_id=self.order.pk,
                attempt_id=attempt.pk,
                amount_eur_cents=int(attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
                idempotency_key="partial-2",
            )

    def test_a_repeated_refund_request_is_the_same_refund(self):
        attempt = pay_order_with_mock(self.client, self.order)

        first = request_refund(
            order_id=self.order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=100,
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key="same-key",
        )
        second = request_refund(
            order_id=self.order.pk,
            attempt_id=attempt.pk,
            amount_eur_cents=100,
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
            idempotency_key="same-key",
        )

        assert first.pk == second.pk
        assert PaymentRefund.objects.filter(order=self.order).count() == 1

    def test_the_database_refuses_refunds_beyond_captures(self):
        pay_order_with_mock(self.client, self.order)
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents > 0

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.filter(pk=self.order.pk).update(
                    refunded_eur_cents=int(self.order.paid_eur_cents) + 1
                )

    def test_a_refund_does_not_erase_the_original_payment(self):
        attempt = pay_order_with_mock(self.client, self.order)

        with self.captureOnCommitCallbacks(execute=True):
            request_refund(
                order_id=self.order.pk,
                attempt_id=attempt.pk,
                amount_eur_cents=int(attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert self.order.paid_eur_cents == int(attempt.amount_eur_cents)
        assert self.order.status == PaymentOrder.Status.REFUNDED
        assert LedgerTransaction.objects.filter(kind="customer_payment").exists()
        assert LedgerTransaction.objects.filter(kind="refund").exists()

    # --- deposit credit ---------------------------------------------------

    def test_a_deposit_cannot_be_credited_to_two_deals(self):
        scenario = build_scenario(prefix="attack-credit", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request, policy=scenario.policy
        )
        pay_order_with_mock(self.client, deposit)
        scenario.delivery_request.refresh_from_db()
        scenario.accept()
        first_balance = scenario.balance_order()

        assert first_balance.credit_source_id == deposit.pk

        # Retire the first obligation so the one-live-balance-per-deal index
        # allows a replacement, then have the replacement try to spend the
        # deposit a second time.
        from django.utils import timezone

        PaymentOrder.objects.filter(pk=first_balance.pk).update(
            status=PaymentOrder.Status.CANCELLED, cancelled_at=timezone.now()
        )
        second = PaymentOrder.objects.create(
            owner_id=scenario.sender.pk,
            purpose=PaymentOrder.Purpose.DEAL_BALANCE,
            amount_eur_cents=5_000,
            deal_id=scenario.deal.pk,
            delivery_request_id=scenario.delivery_request.pk,
            status=PaymentOrder.Status.PENDING,
        )
        credited = apply_posting_deposit_credit(order=second, deal=scenario.deal)

        assert credited == 0
        second.refresh_from_db()
        assert second.credit_source_id is None
        assert (
            LedgerTransaction.objects.filter(kind="deposit_credit").count() == 1
        )

    def test_applying_the_credit_twice_is_a_no_op(self):
        scenario = build_scenario(prefix="attack-credit2", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request, policy=scenario.policy
        )
        pay_order_with_mock(self.client, deposit)
        scenario.delivery_request.refresh_from_db()
        scenario.accept()
        balance = scenario.balance_order()
        before = int(balance.credited_eur_cents)

        again = apply_posting_deposit_credit(order=balance, deal=scenario.deal)

        balance.refresh_from_db()
        assert again == before
        assert int(balance.credited_eur_cents) == before
        assert (
            LedgerTransaction.objects.filter(kind="deposit_credit").count() == 1
        )

    def test_the_database_refuses_two_orders_claiming_one_deposit(self):
        scenario = build_scenario(prefix="attack-credit3", open_request=False)
        deposit = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request, policy=scenario.policy
        )
        pay_order_with_mock(self.client, deposit)
        scenario.delivery_request.refresh_from_db()
        scenario.accept()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentOrder.objects.create(
                    owner_id=scenario.sender.pk,
                    purpose=PaymentOrder.Purpose.DEAL_BALANCE,
                    amount_eur_cents=1_000,
                    deal_id=scenario.deal.pk,
                    credit_source=deposit,
                )

    # --- amount / currency tampering --------------------------------------

    def test_a_success_reporting_the_wrong_amount_is_not_applied(self):
        attempt = open_mock_checkout(self.order)
        body = succeed_attempt(attempt, event_id="evt_tamper", amount_minor=1)

        deliver_mock_webhook(self.client, body)

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.FAILED
        assert attempt.failure_code == "amount_mismatch"
        assert self.order.paid_eur_cents == 0
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == (
            Deal.Status.PAYMENT_REQUIRED
        )

    def test_a_success_reporting_the_wrong_currency_is_not_applied(self):
        attempt = open_mock_checkout(self.order)
        body = mock_event_body(
            event_id="evt_currency",
            outcome="succeeded",
            session_id=attempt.provider_session_id,
            reference=str(self.order.public_reference),
            amount=int(attempt.provider_amount_minor),
            currency="DZD",
        )

        deliver_mock_webhook(self.client, body)

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.failure_code == "currency_mismatch"
        assert self.order.paid_eur_cents == 0

    def test_an_event_for_an_unknown_attempt_moves_no_money(self):
        body = mock_event_body(
            event_id="evt_orphan",
            outcome="succeeded",
            session_id="mock_cs_does_not_exist",
            amount=1_000,
        )

        response = deliver_mock_webhook(self.client, body)

        assert response.status_code == 200
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == 0
        record = PaymentProviderEvent.objects.get(provider_event_id="evt_orphan")
        assert (
            record.processing_result
            == PaymentProviderEvent.ProcessingResult.RETRYABLE
        )
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
            payload__event_id=record.pk,
            status=ScheduledJob.Status.PENDING,
        ).exists()

    # --- out-of-order events ---------------------------------------------

    def test_a_late_failure_cannot_unfund_a_paid_order(self):
        attempt = pay_order_with_mock(self.client, self.order)

        deliver_mock_webhook(
            self.client,
            mock_event_body(
                event_id="evt_late_fail",
                outcome="failed",
                session_id=attempt.provider_session_id,
                amount=int(attempt.provider_amount_minor),
            ),
        )

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert self.order.status == PaymentOrder.Status.PAID
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.FUNDED

    def test_a_success_arriving_after_an_expiry_is_still_honoured(self):
        attempt = open_mock_checkout(self.order)
        reconcile_attempt(attempt_id=attempt.pk, outcome="expired")
        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.EXPIRED

        deliver_mock_webhook(self.client, succeed_attempt(attempt, event_id="evt_late_ok"))

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert attempt.is_unapplied is False
        assert self.order.status == PaymentOrder.Status.PAID

    def test_a_late_success_after_the_reservation_lapsed_does_not_revive_the_deal(self):
        from apps.deals.services import release_pending_deal_reservation

        attempt = open_mock_checkout(self.order)
        release_pending_deal_reservation(
            deal_id=self.scenario.deal.pk, reason="payment_grace_expired"
        )

        deliver_mock_webhook(self.client, succeed_attempt(attempt, event_id="evt_zombie"))

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        deal = Deal.objects.get(pk=self.scenario.deal.pk)
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert attempt.is_unapplied is True
        assert deal.status == Deal.Status.EXPIRED
        assert self.order.status == PaymentOrder.Status.CANCELLED
        assert not DealLegAllocation.objects.filter(
            deal=deal, status=DealLegAllocation.Status.FUNDED
        ).exists()
        assert PaymentRefund.objects.filter(attempt=attempt).exists()


class LedgerIntegrityTests(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="ledger")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()

    def test_every_transaction_balances_to_zero(self):
        pay_order_with_mock(self.client, self.order)

        for ledger_transaction in LedgerTransaction.objects.all():
            total = ledger_transaction.entries.aggregate(
                total=Sum("amount_eur_cents")
            )["total"]
            assert total == 0, f"{ledger_transaction.kind} nets {total}"

    def test_an_unbalanced_transaction_is_refused(self):
        with self.assertRaises(UnbalancedLedgerTransaction):
            ledger.post(
                key="broken",
                kind=LedgerTransaction.Kind.CORRECTION,
                legs=[Leg(account=LedgerAccount.PROVIDER_CLEARING, amount_eur_cents=100)],
            )

        assert not LedgerTransaction.objects.filter(key="broken").exists()

    def test_a_zero_amount_entry_is_refused(self):
        with self.assertRaises(UnbalancedLedgerTransaction):
            ledger.post(
                key="zero",
                kind=LedgerTransaction.Kind.CORRECTION,
                legs=[
                    Leg(account=LedgerAccount.PROVIDER_CLEARING, amount_eur_cents=0),
                    Leg(account=LedgerAccount.DEAL_FUNDS, amount_eur_cents=0),
                ],
            )

    def test_posting_the_same_key_twice_records_one_transaction(self):
        legs = [
            Leg(account=LedgerAccount.PROVIDER_CLEARING, amount_eur_cents=100),
            Leg(account=LedgerAccount.DEAL_FUNDS, amount_eur_cents=-100),
        ]

        first = ledger.post(key="dup", kind=LedgerTransaction.Kind.CORRECTION, legs=legs)
        second = ledger.post(key="dup", kind=LedgerTransaction.Kind.CORRECTION, legs=legs)

        assert first.created is True
        assert second.created is False
        assert second.transaction_id == first.transaction_id
        assert LedgerEntry.objects.filter(transaction_id=first.transaction_id).count() == 2

    def test_ledger_history_cannot_be_edited_or_deleted(self):
        pay_order_with_mock(self.client, self.order)
        entry = LedgerEntry.objects.first()
        ledger_transaction = LedgerTransaction.objects.first()

        entry.amount_eur_cents = 1
        with self.assertRaises(ValidationError):
            entry.save()
        with self.assertRaises(ValidationError):
            entry.delete()
        with self.assertRaises(ValidationError):
            ledger_transaction.save()
        with self.assertRaises(ValidationError):
            ledger_transaction.delete()

    def test_a_correction_is_a_new_linked_transaction(self):
        pay_order_with_mock(self.client, self.order)
        original = LedgerTransaction.objects.get(kind="customer_payment")
        original_entries = list(
            original.entries.values_list("account", "amount_eur_cents")
        )

        ledger.record_correction(
            key="correction:test",
            note="Reversing a mis-posted capture",
            reverses_id=original.pk,
            legs=[
                Leg(account=account, amount_eur_cents=-amount)
                for account, amount in original_entries
            ],
        )

        correction = LedgerTransaction.objects.get(key="correction:test")
        assert correction.reverses_id == original.pk
        # The original is untouched.
        assert (
            list(original.entries.values_list("account", "amount_eur_cents"))
            == original_entries
        )

    def test_funding_recognises_the_traveler_liability_and_the_commission(self):
        pay_order_with_mock(self.client, self.order)
        terms = self.scenario.deal.terms

        assert ledger.account_balance(
            LedgerAccount.TRAVELER_PAYABLE, user_id=self.scenario.traveler.pk
        ) == -int(terms.traveler_reward_minor)
        assert ledger.account_balance(LedgerAccount.PLATFORM_COMMISSION) == -int(
            terms.platform_fee_minor
        )
        # The pooled deal-funds liability is fully released by the split.
        assert ledger.deal_balance(self.scenario.deal.pk, LedgerAccount.DEAL_FUNDS) == 0
        # And the platform still holds the cash.
        assert ledger.account_balance(LedgerAccount.PROVIDER_CLEARING) == int(
            terms.sender_total_minor
        )


class PayoutGateTests(TestCase):
    """Phase 3 must have no path that releases traveler money."""

    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="payout-gate")
        self.scenario.accept(reward_eur_cents=3_200)
        pay_order_with_mock(self.client, self.scenario.balance_order())
        self.payout = Payout.objects.get(deal=self.scenario.deal)

    def test_funding_creates_a_gated_payout_for_the_traveler_reward(self):
        assert self.payout.status == Payout.Status.NOT_ELIGIBLE
        assert self.payout.eligible_at is None
        assert self.payout.amount_eur_cents == int(
            self.scenario.deal.terms.traveler_reward_minor
        )

    def test_no_phase_three_path_marks_a_payout_eligible(self):
        from apps.finance import jobs

        jobs.run_due_jobs(limit=50)
        self.payout.refresh_from_db()

        assert self.payout.status == Payout.Status.NOT_ELIGIBLE

    def test_settling_a_payout_needs_more_than_staff_membership(self):
        """Sending the money is its own capability, not a side effect of `is_staff`.

        Phase 4 introduced named permissions because resolving a dispute moves
        money. This endpoint is the half that actually moves it, and it used to
        sit on bare `is_staff` while the decision authorising it required
        `disputes.resolve_dispute`.
        """

        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self.scenario.admin)
        response = client.post(
            reverse("finance-admin-payout-complete", args=[self.payout.pk]),
            {
                "payout_currency": "EUR",
                "payout_amount_minor": 3_200,
                "reference": "TRANSFER-123",
            },
            format="json",
        )
        assert response.status_code == 403, response.data

    def _grant_settle_payout(self):
        from apps.admin_panel.permissions import AdminRole, assign_admin_roles

        # /api/admin/* is owned by the Phase 6A permission matrix. Grant the
        # canonical Finance role rather than the retired model-level Phase 4
        # compatibility permission that happens to share this URL path.
        assign_admin_roles(self.scenario.admin, (AdminRole.FINANCE,))
        return type(self.scenario.admin).objects.get(pk=self.scenario.admin.pk)

    def test_an_admin_cannot_settle_a_payout_that_is_not_eligible(self):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=self._grant_settle_payout())

        response = client.post(
            reverse("finance-admin-payout-complete", args=[self.payout.pk]),
            {
                "payout_currency": "EUR",
                "payout_amount_minor": 3_200,
                "reference": "TRANSFER-123",
            },
            format="json",
        )

        assert response.status_code == 409, response.data
        assert response.data["code"] == "payout_not_releasable"
        self.payout.refresh_from_db()
        assert self.payout.status == Payout.Status.NOT_ELIGIBLE

    def test_the_database_refuses_a_released_payout_without_eligibility(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payout.objects.filter(pk=self.payout.pk).update(
                    status=Payout.Status.ELIGIBLE
                )

    def test_the_database_refuses_a_paid_payout_without_evidence(self):
        from django.utils import timezone

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payout.objects.filter(pk=self.payout.pk).update(
                    status=Payout.Status.PAID,
                    eligible_at=timezone.now(),
                    paid_at=timezone.now(),
                )

    def test_no_ledger_payout_entry_exists_before_release(self):
        assert not LedgerTransaction.objects.filter(kind="payout").exists()
        assert (
            ledger.account_balance(
                LedgerAccount.TRAVELER_PAYABLE, user_id=self.scenario.traveler.pk
            )
            < 0
        ), "The traveler is owed, and still owed."


class TrappedDepositRegressionTests(TestCase):
    """A deposit must never be stranded on a deal that never funded.

    Found by the Phase 3 finance-state review and reproduced before fixing: a
    sender pays the posting deposit, an offer is accepted, and the payment
    grace then lapses. The credit link marked the deposit "already credited",
    so the expiry refund declined to return it and a later acceptance declined
    to re-use it — the money sat in `deal_funds` against an expired deal with
    no path out.
    """

    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="trap", open_request=False)
        self.deposit = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        pay_order_with_mock(self.client, self.deposit)
        self.deposit.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()

    def _expire_the_grace(self):
        from apps.deals.services import release_pending_deal_reservation

        release_pending_deal_reservation(
            deal_id=self.scenario.deal.pk, reason="payment_grace_expired"
        )

    def test_an_expired_deal_returns_the_deposit_credit(self):
        self.scenario.accept(reward_eur_cents=3_200)
        balance = self.scenario.balance_order()
        assert balance.credit_source_id == self.deposit.pk

        self._expire_the_grace()

        balance.refresh_from_db()
        assert balance.status == PaymentOrder.Status.CANCELLED
        assert balance.credit_source_id is None
        assert balance.credited_eur_cents == 0
        # The money is back where the sender can reach it.
        assert ledger.account_balance(LedgerAccount.DEAL_FUNDS) == 0
        assert ledger.account_balance(
            LedgerAccount.SENDER_DEPOSIT, user_id=self.scenario.sender.pk
        ) == -int(self.deposit.paid_eur_cents)

    def test_the_release_is_a_compensating_entry_not_an_edit(self):
        self.scenario.accept(reward_eur_cents=3_200)
        balance = self.scenario.balance_order()
        original = LedgerTransaction.objects.get(
            key=f"deposit_credit:order:{balance.pk}"
        )
        original_entries = list(
            original.entries.values_list("account", "amount_eur_cents")
        )

        self._expire_the_grace()

        release = LedgerTransaction.objects.get(
            key=f"deposit_credit_release:order:{balance.pk}"
        )
        assert release.kind == LedgerTransaction.Kind.CORRECTION
        assert release.reverses_id == original.pk
        # History is untouched; the reversal is a new fact.
        assert (
            list(original.entries.values_list("account", "amount_eur_cents"))
            == original_entries
        )

    def test_the_released_deposit_is_refunded_when_the_request_expires(self):
        from datetime import timedelta

        from django.utils import timezone

        from apps.finance import jobs
        from apps.finance.models import ScheduledJob
        from apps.parcels.models import DeliveryRequest

        self.scenario.accept(reward_eur_cents=3_200)
        self._expire_the_grace()

        DeliveryRequest.objects.filter(pk=self.scenario.delivery_request.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND
        ).update(
            status=ScheduledJob.Status.PENDING,
            run_at=timezone.now() - timedelta(minutes=1),
        )
        with self.captureOnCommitCallbacks(execute=True):
            jobs.run_due_jobs(limit=10, at=timezone.now() + timedelta(hours=48))

        self.deposit.refresh_from_db()
        assert self.deposit.status == PaymentOrder.Status.REFUNDED
        assert self.deposit.refunded_eur_cents == self.deposit.paid_eur_cents
        assert PaymentRefund.objects.filter(order=self.deposit).count() == 1

    def test_the_released_deposit_can_credit_a_second_acceptance(self):
        """The request returns to open, so the next deal gets the credit."""

        self.scenario.accept(reward_eur_cents=3_200)
        self._expire_the_grace()
        self.scenario.delivery_request.refresh_from_db()
        assert self.scenario.delivery_request.status == "open"

        second = build_scenario(prefix="trap-second")
        # Re-negotiate the original request with the same traveler.
        self.scenario.offer = None
        self.scenario.deal = None
        deal = self.scenario.accept(reward_eur_cents=3_200)

        balance = PaymentOrder.objects.get(
            deal=deal, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        assert balance.credit_source_id == self.deposit.pk
        assert balance.credited_eur_cents == int(self.deposit.paid_eur_cents)
        assert second is not None

    def test_a_cancelled_order_with_no_credit_is_unaffected(self):
        scenario = build_scenario(prefix="trap-nocredit")
        scenario.accept(reward_eur_cents=3_200)
        balance = scenario.balance_order()
        assert balance.credited_eur_cents == 0

        from apps.finance.services import cancel_order

        cancel_order(order_id=balance.pk, reason="test")

        balance.refresh_from_db()
        assert balance.status == PaymentOrder.Status.CANCELLED
        assert not LedgerTransaction.objects.filter(
            key=f"deposit_credit_release:order:{balance.pk}"
        ).exists()
