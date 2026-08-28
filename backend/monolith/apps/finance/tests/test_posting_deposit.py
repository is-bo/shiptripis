"""Posting deposit: formula, publication gating, credit, and refunds.

The deposit is the first place a client could be tempted to assert a payment.
These tests hold the opposite line at every step: the amount is computed by the
server, publication is the effect of a reconciled provider event, the credit is
applied once and only to the right Deal, and every way a deposited request can
end without a delivery returns the money.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.business_settings import get_active_business_settings
from apps.deals.models import Deal
from apps.finance import jobs
from apps.finance.models import (
    LedgerAccount,
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    ScheduledJob,
)
from apps.finance.policy import Phase3Policy
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    ensure_posting_deposit_order,
    quote_posting_deposit,
)
from apps.finance import ledger
from apps.parcels.models import DeliveryRequest, ParcelRequest

from .factories import (
    build_scenario,
    deliver_mock_webhook,
    open_mock_checkout,
    pay_order_with_mock,
    succeed_attempt,
)


def _enable_mock_provider(policy_dict: dict) -> dict:
    policy = deepcopy(policy_dict)
    policy["payments"]["providers"]["mock_enabled"] = True
    return policy


class DepositTestCase(TestCase):
    """Every deposit test needs the mock rail switched on in policy."""

    prefix = "dep"

    def setUp(self):
        MockGateway.reset()
        settings_version = get_active_business_settings()
        # Business policy is immutable in the database; for tests we enable the
        # mock rail on an in-memory copy and let the service read that.
        settings_version.policy = _enable_mock_provider(settings_version.policy)
        type(settings_version).objects.filter(pk=settings_version.pk).update(
            policy=settings_version.policy
        )
        self.scenario = build_scenario(prefix=self.prefix, open_request=False)
        self.scenario.policy = Phase3Policy.from_settings(
            get_active_business_settings()
        )

    def client_for(self, user) -> APIClient:
        client = APIClient()
        client.force_authenticate(user=user)
        return client


class DepositFormulaTests(DepositTestCase):
    prefix = "dep-formula"

    def test_the_deposit_is_ten_percent_of_the_recommended_sender_total(self):
        quote = quote_posting_deposit(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        expected = round(quote.estimated_sender_total_eur_cents * 0.10)
        assert quote.percent_bps == 1_000
        # Inside the clamp, the deposit is exactly the percentage.
        if 300 <= expected <= 700:
            assert quote.amount_eur_cents == expected
        assert 300 <= quote.amount_eur_cents <= 700

    def test_the_lower_clamp_binds_for_a_cheap_delivery(self):
        def mutate(policy):
            # 0.1% of any realistic total is far below EUR 3.00.
            policy["payments"]["posting_deposit"]["percent_bps"] = 10

        quote = quote_posting_deposit(
            delivery_request=self.scenario.delivery_request,
            policy=self._policy_with(mutate),
        )

        assert quote.amount_eur_cents == 300
        assert quote.clamped == "min"

    def test_the_upper_clamp_binds_for_an_expensive_delivery(self):
        def mutate(policy):
            policy["payments"]["posting_deposit"]["percent_bps"] = 9_000

        quote = quote_posting_deposit(
            delivery_request=self.scenario.delivery_request,
            policy=self._policy_with(mutate),
        )

        assert quote.amount_eur_cents == 700
        assert quote.clamped == "max"

    def test_the_quote_records_its_own_inputs_for_audit(self):
        quote = quote_posting_deposit(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        assert quote.inputs["estimate_method"].startswith("posting_deposit_estimate")
        assert quote.inputs["estimate_distance_meters"] > 0
        assert quote.inputs["recommended_sender_total_eur_cents"] > 0

    def test_the_order_freezes_the_inputs_that_priced_it(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        inputs = order.terms_snapshot["posting_deposit_inputs"]
        assert inputs["raw_percentage_eur_cents"] > 0
        assert inputs["recommended_sender_total_eur_cents"] > 0
        assert order.terms_snapshot["payments"]["posting_deposit"]["percent_bps"] == 1_000
        assert order.business_settings_version_id is not None
        assert order.currency == "EUR"

    def test_creating_the_deposit_order_twice_prices_it_once(self):
        first = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        second = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        assert first.pk == second.pk
        assert (
            PaymentOrder.objects.filter(
                delivery_request=self.scenario.delivery_request,
                purpose=PaymentOrder.Purpose.POSTING_DEPOSIT,
            ).count()
            == 1
        )

    def _policy_with(self, mutate) -> Phase3Policy:
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        mutate(policy)
        settings_version.policy = policy
        return Phase3Policy.from_settings(settings_version)


class DepositPublicationTests(DepositTestCase):
    prefix = "dep-publish"

    def test_a_new_request_is_created_unpublished_in_deposit_mode(self):
        pickup = self.scenario.delivery_request.pickup_location
        dropoff = self.scenario.delivery_request.delivery_location
        at = timezone.now()
        response = self.client_for(self.scenario.sender).post(
            reverse("parcels-delivery-v1-create"),
            {
                "pickup_location_id": pickup.pk,
                "delivery_location_id": dropoff.pk,
                "ready_window_start": (at + timedelta(hours=1)).isoformat(),
                "ready_window_end": (at + timedelta(hours=6)).isoformat(),
                "deadline_at": (at + timedelta(days=2)).isoformat(),
                "actual_weight_kg": "2.00",
                "length_cm": "20",
                "width_cm": "20",
                "height_cm": "20",
                "declared_value_eur_cents": 10_000,
                "sender_proposed_reward_eur_cents": 2_000,
                "title": "Deposit gated parcel",
                "description": "Safe test parcel",
                "category": "documents",
                "description_is_accurate": True,
                "item_is_legal": True,
                "no_prohibited_goods": True,
                "declared_value_is_accurate": True,
                "customs_responsibilities_understood": True,
            },
            format="json",
        )

        assert response.status_code == 201, response.data
        created = DeliveryRequest.objects.get(pk=response.data["id"])
        assert created.status == ParcelRequest.Status.AWAITING_DEPOSIT
        assert response.data["posting_deposit"]["status"] == "pending"
        assert response.data["posting_deposit"]["amount_eur_cents"] >= 300

    def test_an_unpublished_request_is_not_discoverable_or_proposable(self):
        response = self.client_for(self.scenario.traveler).get(
            reverse("parcels-open-search")
        )

        assert response.status_code == 200
        assert all(
            row["id"] != self.scenario.delivery_request.pk for row in response.data
        )

        from apps.matching.v1_services import RequestNotOpen, create_sender_offer

        with self.assertRaises(RequestNotOpen):
            create_sender_offer(
                sender=self.scenario.sender,
                delivery_request=self.scenario.delivery_request,
                journey=self.scenario.journey,
                start_leg_id=self.scenario.leg.pk,
                end_leg_id=self.scenario.leg.pk,
                traveler_reward_eur_cents=2_000,
            )

    def test_a_reconciled_deposit_payment_publishes_the_request(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        pay_order_with_mock(self.client, order)

        self.scenario.delivery_request.refresh_from_db()
        order.refresh_from_db()
        assert order.status == PaymentOrder.Status.PAID
        assert self.scenario.delivery_request.status == ParcelRequest.Status.OPEN

    def test_a_redirect_alone_never_publishes_the_request(self):
        """Opening a checkout is not paying for it."""

        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        attempt = open_mock_checkout(order)

        assert attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING
        order.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()
        assert order.status == PaymentOrder.Status.PENDING
        assert (
            self.scenario.delivery_request.status
            == ParcelRequest.Status.AWAITING_DEPOSIT
        )

    def test_publication_arms_the_expiry_refund_obligation(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        pay_order_with_mock(self.client, order)

        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND,
            payload__delivery_request_id=self.scenario.delivery_request.pk,
        )
        assert job.status == ScheduledJob.Status.PENDING
        assert job.run_at == self.scenario.delivery_request.deadline_at

    def test_the_capture_is_recorded_in_the_ledger_as_a_held_deposit(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        pay_order_with_mock(self.client, order)
        order.refresh_from_db()

        assert (
            ledger.account_balance(LedgerAccount.PROVIDER_CLEARING)
            == order.amount_eur_cents
        )
        assert ledger.account_balance(
            LedgerAccount.SENDER_DEPOSIT, user_id=self.scenario.sender.pk
        ) == -order.amount_eur_cents


class DepositCreditTests(DepositTestCase):
    prefix = "dep-credit"

    def _paid_deposit(self) -> PaymentOrder:
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        pay_order_with_mock(self.client, order)
        order.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()
        return order

    def test_the_deposit_is_credited_not_charged_again(self):
        deposit = self._paid_deposit()
        deal = self.scenario.accept(reward_eur_cents=3_200)

        balance = self.scenario.balance_order()
        terms = deal.terms

        assert balance.amount_eur_cents == terms.sender_total_minor
        assert balance.credited_eur_cents == deposit.paid_eur_cents
        assert balance.outstanding_eur_cents == (
            int(terms.sender_total_minor) - int(deposit.paid_eur_cents)
        )
        # The sender is never asked for total + deposit.
        assert (
            balance.outstanding_eur_cents + int(deposit.paid_eur_cents)
            == int(terms.sender_total_minor)
        )

    def test_the_credit_links_the_exact_deposit_it_consumed(self):
        deposit = self._paid_deposit()
        self.scenario.accept()

        balance = self.scenario.balance_order()
        assert balance.credit_source_id == deposit.pk

    def test_the_credit_is_a_balanced_ledger_move_with_no_new_cash(self):
        deposit = self._paid_deposit()
        clearing_before = ledger.account_balance(LedgerAccount.PROVIDER_CLEARING)
        self.scenario.accept()

        # No money entered the platform: the deposit liability became deal funds.
        assert (
            ledger.account_balance(LedgerAccount.PROVIDER_CLEARING)
            == clearing_before
        )
        assert (
            ledger.account_balance(
                LedgerAccount.SENDER_DEPOSIT, user_id=self.scenario.sender.pk
            )
            == 0
        )
        assert ledger.account_balance(
            LedgerAccount.DEAL_FUNDS
        ) == -int(deposit.paid_eur_cents)

    def test_an_unpaid_deposit_credits_nothing(self):
        ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        ParcelRequest.objects.filter(pk=self.scenario.delivery_request.pk).update(
            status=ParcelRequest.Status.OPEN
        )
        self.scenario.delivery_request.refresh_from_db()

        deal = self.scenario.accept()

        balance = self.scenario.balance_order()
        assert balance.credited_eur_cents == 0
        assert balance.outstanding_eur_cents == int(deal.terms.sender_total_minor)

    def test_another_senders_deposit_can_never_be_applied(self):
        """Credit eligibility is owner- and request-scoped, not amount-scoped."""

        self._paid_deposit()
        stranger = build_scenario(prefix="dep-credit-other", open_request=False)
        stranger_deposit = ensure_posting_deposit_order(
            delivery_request=stranger.delivery_request, policy=stranger.policy
        )
        pay_order_with_mock(self.client, stranger_deposit)

        self.scenario.accept()
        balance = self.scenario.balance_order()

        assert balance.credit_source_id != stranger_deposit.pk
        stranger_deposit.refresh_from_db()
        assert stranger_deposit.credited_eur_cents == 0

    def test_paying_the_credited_balance_funds_the_deal_exactly_once(self):
        deposit = self._paid_deposit()
        deal = self.scenario.accept(reward_eur_cents=3_200)
        balance = self.scenario.balance_order()

        attempt = pay_order_with_mock(self.client, balance)

        deal.refresh_from_db()
        balance.refresh_from_db()
        assert deal.status == Deal.Status.FUNDED
        assert balance.status == PaymentOrder.Status.PAID
        assert balance.outstanding_eur_cents == 0
        assert int(attempt.amount_eur_cents) == (
            int(deal.terms.sender_total_minor) - int(deposit.paid_eur_cents)
        )

    def test_the_worked_example_from_the_specification(self):
        """Total EUR 40, deposit EUR 4 -> outstanding EUR 36, never EUR 44."""

        deposit = self._paid_deposit()
        PaymentOrder.objects.filter(pk=deposit.pk).update(
            amount_eur_cents=400, paid_eur_cents=400
        )
        PaymentAttempt.objects.filter(order=deposit).update(amount_eur_cents=400)
        deposit.refresh_from_db()

        self.scenario.accept(reward_eur_cents=3_200)
        balance = self.scenario.balance_order()

        assert balance.amount_eur_cents == 4_000
        assert balance.credited_eur_cents == 400
        assert balance.outstanding_eur_cents == 3_600


class DepositRefundTests(DepositTestCase):
    prefix = "dep-refund"

    def _paid_deposit(self) -> PaymentOrder:
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        pay_order_with_mock(self.client, order)
        order.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()
        return order

    def test_an_unmatched_expiry_refunds_the_deposit(self):
        deposit = self._paid_deposit()
        DeliveryRequest.objects.filter(pk=self.scenario.delivery_request.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )

        with self.captureOnCommitCallbacks(execute=True):
            report = jobs.run_due_jobs(
                limit=10, at=timezone.now() + timedelta(hours=48)
            )

        assert report.claimed >= 1
        deposit.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()
        assert self.scenario.delivery_request.status == ParcelRequest.Status.EXPIRED
        assert deposit.status == PaymentOrder.Status.REFUNDED
        assert deposit.refunded_eur_cents == deposit.paid_eur_cents

    def test_the_expiry_refund_runs_once_no_matter_how_often_it_fires(self):
        deposit = self._paid_deposit()
        DeliveryRequest.objects.filter(pk=self.scenario.delivery_request.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )
        later = timezone.now() + timedelta(hours=48)

        with self.captureOnCommitCallbacks(execute=True):
            jobs.run_due_jobs(limit=10, at=later)
        # Force the same obligation to run again, as a crashed worker would.
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.DEPOSIT_EXPIRY_REFUND
        ).update(status=ScheduledJob.Status.PENDING, run_at=timezone.now())
        jobs.run_due_jobs(limit=10, at=later)
        jobs.run_due_jobs(limit=10, at=later)

        deposit.refresh_from_db()
        assert PaymentRefund.objects.filter(order=deposit).count() == 1
        assert deposit.refunded_eur_cents == deposit.paid_eur_cents

    def test_a_matched_request_is_not_refunded_by_the_expiry_job(self):
        deposit = self._paid_deposit()
        self.scenario.accept()
        DeliveryRequest.objects.filter(pk=self.scenario.delivery_request.pk).update(
            deadline_at=timezone.now() - timedelta(minutes=1)
        )

        jobs.run_due_jobs(limit=10, at=timezone.now() + timedelta(hours=48))

        deposit.refresh_from_db()
        assert deposit.refunded_eur_cents == 0
        assert PaymentRefund.objects.filter(order=deposit).count() == 0

    def test_cancelling_before_an_accepted_offer_refunds_in_full(self):
        deposit = self._paid_deposit()

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client_for(self.scenario.sender).post(
                reverse("parcels-cancel", args=[self.scenario.delivery_request.pk])
            )

        assert response.status_code == 200, response.data
        deposit.refresh_from_db()
        assert deposit.refunded_eur_cents == deposit.paid_eur_cents
        assert PaymentRefund.objects.get(order=deposit).reason == (
            PaymentRefund.Reason.SENDER_CANCELLED
        )

    def test_cancelling_an_unpaid_request_closes_the_obligation(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )

        response = self.client_for(self.scenario.sender).post(
            reverse("parcels-cancel", args=[self.scenario.delivery_request.pk])
        )

        assert response.status_code == 200, response.data
        order.refresh_from_db()
        assert order.status == PaymentOrder.Status.CANCELLED
        assert PaymentRefund.objects.filter(order=order).count() == 0

    def test_a_refund_leaves_the_original_capture_intact(self):
        deposit = self._paid_deposit()
        attempt = PaymentAttempt.objects.get(order=deposit)

        with self.captureOnCommitCallbacks(execute=True):
            self.client_for(self.scenario.sender).post(
                reverse("parcels-cancel", args=[self.scenario.delivery_request.pk])
            )

        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert attempt.succeeded_at is not None
        # The ledger nets to zero but both facts are still on the record.
        assert ledger.account_balance(LedgerAccount.PROVIDER_CLEARING) == 0
        assert (
            ledger.LedgerTransaction.objects.filter(kind="customer_payment").count()
            == 1
        )
        assert ledger.LedgerTransaction.objects.filter(kind="refund").count() == 1

    def test_a_late_success_after_cancellation_is_refunded_not_applied(self):
        order = ensure_posting_deposit_order(
            delivery_request=self.scenario.delivery_request,
            policy=self.scenario.policy,
        )
        attempt = open_mock_checkout(order)
        self.client_for(self.scenario.sender).post(
            reverse("parcels-cancel", args=[self.scenario.delivery_request.pk])
        )

        response = deliver_mock_webhook(self.client, succeed_attempt(attempt))

        assert response.status_code == 200
        attempt.refresh_from_db()
        order.refresh_from_db()
        self.scenario.delivery_request.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert attempt.is_unapplied is True
        # The cancelled request is not revived by a late payment.
        assert self.scenario.delivery_request.status == ParcelRequest.Status.CANCELLED
        assert order.status == PaymentOrder.Status.CANCELLED
        assert PaymentRefund.objects.filter(
            attempt=attempt, reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT
        ).exists()
