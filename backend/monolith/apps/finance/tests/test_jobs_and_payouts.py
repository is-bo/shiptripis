"""Durable scheduled work and the payout abstraction.

The scheduling contract under test is that the database — not Redis, not a
worker's memory — is the record of a delayed financial obligation. A job that
exists here runs eventually; one that does not was never promised. Handlers are
idempotent, so a crashed worker, a duplicate claim or a manual requeue costs
nothing.

The payout tests check the capability abstraction (never a country heuristic)
and the manual fallback, and confirm again from the scheduling side that Phase
3 cannot release traveler money.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealLegAllocation
from apps.finance import jobs
from apps.finance.models import (
    PaymentAttempt,
    PaymentOrder,
    PaymentRefund,
    Payout,
    ScheduledJob,
    TravelerPayoutMethod,
)
from apps.finance.policy import Phase3Policy, phase3_policy
from apps.finance.providers.base import PayoutCapability
from apps.finance.services import (
    PayoutNotReleasable,
    complete_manual_payout,
    ensure_payout_for_deal,
    resolve_payout_method,
    schedule_job,
)

from .factories import build_scenario, open_mock_checkout, pay_order_with_mock


def _enable_mock():
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class ScheduledJobTests(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="jobs")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()

    def test_acceptance_records_the_grace_release_obligation_in_the_database(self):
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.PAYMENT_GRACE_RELEASE,
            payload__deal_id=self.scenario.deal.pk,
        )

        assert job.status == ScheduledJob.Status.PENDING
        assert job.run_at > timezone.now()

    def test_scheduling_the_same_obligation_twice_records_it_once(self):
        run_at = timezone.now() + timedelta(hours=1)

        first = schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="dup-key",
            run_at=run_at,
            payload={"attempt_id": 1},
        )
        second = schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="dup-key",
            run_at=run_at,
            payload={"attempt_id": 1},
        )

        assert first.pk == second.pk
        assert ScheduledJob.objects.filter(key="dup-key").count() == 1

    def test_a_job_that_is_not_due_is_not_claimed(self):
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="future",
            run_at=timezone.now() + timedelta(days=1),
            payload={"attempt_id": 1},
        )

        claimed = jobs.claim_due_jobs(limit=10)

        assert all(job.key != "future" for job in claimed)

    def test_claiming_marks_the_job_running_and_stamps_the_worker(self):
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="claimable",
            run_at=timezone.now() - timedelta(minutes=1),
            payload={"attempt_id": 999_999},
        )

        claimed = jobs.claim_due_jobs(limit=10)
        row = next(job for job in claimed if job.key == "claimable")

        assert row.status == ScheduledJob.Status.RUNNING
        assert row.locked_by
        assert row.locked_at is not None

    def test_a_failing_handler_retries_with_backoff_and_never_kills_the_loop(self):
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="will-fail",
            run_at=timezone.now() - timedelta(minutes=1),
            payload={"attempt_id": "not-an-int"},
        )

        report = jobs.run_due_jobs(limit=10)

        assert report.failed >= 1
        row = ScheduledJob.objects.get(key="will-fail")
        assert row.status == ScheduledJob.Status.PENDING
        assert row.attempts == 1
        assert row.run_at > timezone.now()
        assert "JobFailed" in row.last_error

    def test_a_job_that_exhausts_its_attempts_is_marked_failed(self):
        schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="doomed",
            run_at=timezone.now() - timedelta(minutes=1),
            payload={"attempt_id": None},
            max_attempts=1,
        )

        jobs.run_due_jobs(limit=10)

        row = ScheduledJob.objects.get(key="doomed")
        assert row.status == ScheduledJob.Status.FAILED
        assert row.completed_at is not None

    def test_an_unknown_job_kind_fails_loudly_rather_than_silently(self):
        ScheduledJob.objects.create(
            key="unknown-kind",
            kind="not_a_real_kind",
            run_at=timezone.now() - timedelta(minutes=1),
        )

        jobs.run_due_jobs(limit=10)

        row = ScheduledJob.objects.get(key="unknown-kind")
        assert row.status == ScheduledJob.Status.FAILED
        assert "No handler" in row.last_error

    def test_a_worker_that_died_mid_run_has_its_job_returned_to_the_queue(self):
        job = schedule_job(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            key="orphaned",
            run_at=timezone.now() - timedelta(hours=2),
            payload={"attempt_id": 1},
        )
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.RUNNING,
            locked_at=timezone.now() - timedelta(hours=1),
            locked_by="dead-worker:1",
        )

        requeued = jobs.requeue_stuck_jobs(stale_after_seconds=60)

        assert requeued == 1
        row = ScheduledJob.objects.get(pk=job.pk)
        assert row.status == ScheduledJob.Status.PENDING
        assert row.locked_by == ""

    def test_an_expired_checkout_is_closed_by_its_own_scheduled_job(self):
        attempt = open_mock_checkout(self.order)
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY, payload__attempt_id=attempt.pk
        ).update(run_at=timezone.now() - timedelta(minutes=1))

        jobs.run_due_jobs(limit=10)

        attempt.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.EXPIRED
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.PENDING

    def test_the_grace_release_job_frees_capacity_and_closes_the_obligation(self):
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.PAYMENT_GRACE_RELEASE,
            payload__deal_id=self.scenario.deal.pk,
        )
        DealLegAllocation.objects.filter(deal=self.scenario.deal).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        ScheduledJob.objects.filter(pk=job.pk).update(
            run_at=timezone.now() - timedelta(minutes=1)
        )

        jobs.run_due_jobs(limit=10)

        deal = Deal.objects.get(pk=self.scenario.deal.pk)
        self.order.refresh_from_db()
        assert deal.status == Deal.Status.EXPIRED
        assert self.order.status == PaymentOrder.Status.CANCELLED
        assert not DealLegAllocation.objects.filter(
            deal=deal, status=DealLegAllocation.Status.PENDING_PAYMENT
        ).exists()

    def test_running_the_grace_release_twice_changes_nothing_the_second_time(self):
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.PAYMENT_GRACE_RELEASE,
            payload__deal_id=self.scenario.deal.pk,
        )
        DealLegAllocation.objects.filter(deal=self.scenario.deal).update(
            expires_at=timezone.now() - timedelta(minutes=1)
        )
        ScheduledJob.objects.filter(pk=job.pk).update(
            run_at=timezone.now() - timedelta(minutes=1)
        )
        jobs.run_due_jobs(limit=10)
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.PENDING,
            run_at=timezone.now() - timedelta(minutes=1),
        )

        jobs.run_due_jobs(limit=10)

        assert ScheduledJob.objects.get(pk=job.pk).last_result == "no_op"
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.EXPIRED

    def test_reconciliation_recovers_a_payment_whose_webhook_never_arrived(self):
        """Providers do not guarantee delivery; polling is the safety net."""

        from apps.finance.providers.mock import MockGateway

        attempt = open_mock_checkout(self.order)
        MockGateway.mark(attempt.provider_session_id, "succeeded")
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE, payload__attempt_id=attempt.pk
        ).update(run_at=timezone.now() - timedelta(minutes=1))

        jobs.run_due_jobs(limit=10)

        attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert self.order.status == PaymentOrder.Status.PAID
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.FUNDED
        MockGateway.reset()

    def test_cancelling_an_order_preserves_external_money_reconciliation(self):
        from apps.finance.services import cancel_order

        attempt = open_mock_checkout(self.order)

        cancel_order(order_id=self.order.pk, reason="test")

        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
            payload__attempt_id=attempt.pk,
            status=ScheduledJob.Status.CANCELLED,
        ).exists()
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            payload__attempt_id=attempt.pk,
            status=ScheduledJob.Status.PENDING,
        ).exists()


class PayoutCapabilityTests(TestCase):
    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="payout-cap")
        self.scenario.accept(reward_eur_cents=3_200)

    def _policy_with_auto_payout(self) -> Phase3Policy:
        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["payout"]["auto_stripe_enabled"] = True
        settings_version.policy = policy
        return Phase3Policy.from_settings(settings_version)

    def test_no_country_implies_a_payout_capability(self):
        """An Algerian traveler is not automatically Stripe-payable."""

        TravelerPayoutMethod.objects.create(
            traveler=self.scenario.traveler,
            method=TravelerPayoutMethod.Method.STRIPE_CONNECT,
            provider_account_id="acct_dz_1",
            country_code="DZ",
            payouts_enabled=False,
            is_default=True,
        )

        method, reason = resolve_payout_method(
            traveler_id=self.scenario.traveler.pk,
            funding_provider="stripe",
            policy=self._policy_with_auto_payout(),
        )

        assert method == Payout.Method.MANUAL
        assert reason == "capability_not_reported"

    def test_without_a_connected_account_the_fallback_is_manual(self):
        method, reason = resolve_payout_method(
            traveler_id=self.scenario.traveler.pk,
            funding_provider="stripe",
            policy=self._policy_with_auto_payout(),
        )

        assert method == Payout.Method.MANUAL
        assert reason == "no_connected_account"

    def test_automatic_payout_needs_the_provider_to_confirm_the_capability(self):
        TravelerPayoutMethod.objects.create(
            traveler=self.scenario.traveler,
            method=TravelerPayoutMethod.Method.STRIPE_CONNECT,
            provider_account_id="acct_live_1",
            country_code="FR",
            payouts_enabled=True,
            is_default=True,
        )

        with patch(
            "apps.finance.providers.StripeGateway.is_configured", return_value=True
        ), patch(
            "apps.finance.providers.StripeGateway.payout_capability",
            return_value=PayoutCapability(available=True, account_id="acct_live_1"),
        ):
            method, reason = resolve_payout_method(
                traveler_id=self.scenario.traveler.pk,
                funding_provider="stripe",
                policy=self._policy_with_auto_payout(),
            )

        assert method == Payout.Method.STRIPE_TRANSFER
        assert reason == ""

    def test_a_provider_that_reports_no_capability_falls_back_to_manual(self):
        TravelerPayoutMethod.objects.create(
            traveler=self.scenario.traveler,
            method=TravelerPayoutMethod.Method.STRIPE_CONNECT,
            provider_account_id="acct_live_2",
            country_code="FR",
            payouts_enabled=True,
            is_default=True,
        )

        with patch(
            "apps.finance.providers.StripeGateway.is_configured", return_value=True
        ), patch(
            "apps.finance.providers.StripeGateway.payout_capability",
            return_value=PayoutCapability(
                available=False, reason="capability_inactive"
            ),
        ):
            method, reason = resolve_payout_method(
                traveler_id=self.scenario.traveler.pk,
                funding_provider="stripe",
                policy=self._policy_with_auto_payout(),
            )

        assert method == Payout.Method.MANUAL
        assert reason == "capability_inactive"

    def test_the_policy_switch_alone_can_force_the_manual_queue(self):
        method, reason = resolve_payout_method(
            traveler_id=self.scenario.traveler.pk,
            funding_provider="stripe",
            policy=phase3_policy(),
        )

        assert method == Payout.Method.MANUAL
        assert reason == "auto_payout_disabled"

    def test_creating_the_payout_twice_creates_one_record(self):
        first = ensure_payout_for_deal(
            deal_id=self.scenario.deal.pk,
            traveler_id=self.scenario.traveler.pk,
            amount_eur_cents=3_200,
        )
        second = ensure_payout_for_deal(
            deal_id=self.scenario.deal.pk,
            traveler_id=self.scenario.traveler.pk,
            amount_eur_cents=3_200,
        )

        assert first.pk == second.pk
        assert Payout.objects.filter(deal=self.scenario.deal).count() == 1

    def test_creating_the_payout_arms_a_release_check_that_holds_it_shut(self):
        """Phase 4 turned this job into a real gate, and it still refuses.

        The payout is armed at funding, long before anyone knows when delivery
        will be confirmed, so this job is the safety net rather than the
        trigger. Running it on a Deal that has not been delivered must leave
        the payout exactly where it was.
        """

        payout = ensure_payout_for_deal(
            deal_id=self.scenario.deal.pk,
            traveler_id=self.scenario.traveler.pk,
            amount_eur_cents=3_200,
        )
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.PAYOUT_RELEASE_CHECK,
            payload__payout_id=payout.pk,
        )
        ScheduledJob.objects.filter(pk=job.pk).update(
            run_at=timezone.now() - timedelta(minutes=1)
        )

        jobs.run_due_jobs(limit=10)

        payout.refresh_from_db()
        assert payout.status == Payout.Status.NOT_ELIGIBLE
        assert payout.eligible_at is None

        # And the obligation survives its own early fire. Marking it succeeded
        # would consume the safety net 48 hours after funding — before the
        # delivery it is meant to watch has even happened.
        rearmed = ScheduledJob.objects.get(pk=job.pk)
        assert rearmed.status == ScheduledJob.Status.PENDING
        assert "delivery_not_confirmed" in rearmed.last_error
        assert rearmed.run_at > timezone.now()


class ManualPayoutTests(TestCase):
    """Settlement primitives exist; the Phase 4 gate still holds them shut."""

    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="manual-payout")
        self.scenario.accept(reward_eur_cents=3_200)
        pay_order_with_mock(self.client, self.scenario.balance_order())
        self.payout = Payout.objects.get(deal=self.scenario.deal)

    def _release_for_phase_four(self):
        """Stand in for the Phase 4 release service so we can test settlement."""

        Payout.objects.filter(pk=self.payout.pk).update(
            eligible_at=timezone.now(), status=Payout.Status.ELIGIBLE
        )
        self.payout.refresh_from_db()

    def test_settlement_is_refused_while_the_payout_is_gated(self):
        with self.assertRaises(PayoutNotReleasable) as caught:
            complete_manual_payout(
                payout_id=self.payout.pk,
                admin_actor_id=self.scenario.admin.pk,
                payout_currency="EUR",
                payout_amount_minor=3_200,
                reference="TRF-1",
            )

        assert caught.exception.code == "payout_not_releasable"
        assert caught.exception.details()["payout_status"] == "not_eligible"

    def test_a_released_payout_settles_with_a_full_audit_record(self):
        self._release_for_phase_four()

        settled = complete_manual_payout(
            payout_id=self.payout.pk,
            admin_actor_id=self.scenario.admin.pk,
            payout_currency="DZD",
            payout_amount_minor=48_000,
            fx_rate_micros=150_000_000,
            reference="BANK-REF-77",
            receipt_url="https://receipts.test/77",
            notes="Settled by wire",
        )

        assert settled.status == Payout.Status.PAID
        assert settled.method == Payout.Method.MANUAL
        assert settled.payout_currency == "DZD"
        assert settled.payout_amount_minor == 48_000
        assert settled.payout_amount_exponent == 0
        assert settled.fx_rate_micros == 150_000_000
        assert settled.admin_actor_id == self.scenario.admin.pk
        assert settled.reference == "BANK-REF-77"
        assert settled.paid_at is not None
        # The EUR obligation is what the ledger discharges.
        from apps.finance import ledger
        from apps.finance.models import LedgerAccount

        assert (
            ledger.account_balance(
                LedgerAccount.TRAVELER_PAYABLE, user_id=self.scenario.traveler.pk
            )
            == 0
        )

    def test_settling_twice_pays_once(self):
        self._release_for_phase_four()
        first = complete_manual_payout(
            payout_id=self.payout.pk,
            admin_actor_id=self.scenario.admin.pk,
            payout_currency="EUR",
            payout_amount_minor=3_200,
            reference="TRF-2",
        )
        second = complete_manual_payout(
            payout_id=self.payout.pk,
            admin_actor_id=self.scenario.admin.pk,
            payout_currency="EUR",
            payout_amount_minor=3_200,
            reference="TRF-2",
        )

        from apps.finance.models import LedgerTransaction

        assert first.pk == second.pk
        assert first.paid_at == second.paid_at
        assert LedgerTransaction.objects.filter(kind="payout").count() == 1

    def test_settlement_without_a_reference_is_refused(self):
        self._release_for_phase_four()

        with self.assertRaises(PayoutNotReleasable):
            complete_manual_payout(
                payout_id=self.payout.pk,
                admin_actor_id=self.scenario.admin.pk,
                payout_currency="EUR",
                payout_amount_minor=3_200,
                reference="   ",
            )

    def test_a_non_eur_settlement_must_record_the_rate_that_was_used(self):
        self._release_for_phase_four()

        with self.assertRaises(PayoutNotReleasable):
            complete_manual_payout(
                payout_id=self.payout.pk,
                admin_actor_id=self.scenario.admin.pk,
                payout_currency="DZD",
                payout_amount_minor=48_000,
                reference="TRF-3",
            )

    def test_an_unsupported_settlement_currency_is_refused(self):
        self._release_for_phase_four()

        with self.assertRaises(PayoutNotReleasable):
            complete_manual_payout(
                payout_id=self.payout.pk,
                admin_actor_id=self.scenario.admin.pk,
                payout_currency="USD",
                payout_amount_minor=3_500,
                fx_rate_micros=1_100_000,
                reference="TRF-4",
            )

    def test_a_refund_and_a_payout_never_both_claim_the_same_money(self):
        """The traveler payable is only created once the sender's cash is in."""

        from apps.finance import ledger
        from apps.finance.models import LedgerAccount

        order = self.scenario.balance_order()
        attempt = PaymentAttempt.objects.get(
            order=order, status=PaymentAttempt.Status.SUCCEEDED
        )

        from apps.finance.services import request_refund

        with self.captureOnCommitCallbacks(execute=True):
            request_refund(
                order_id=order.pk,
                attempt_id=attempt.pk,
                amount_eur_cents=int(attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        # Refunding the customer does not silently erase what the traveler is
        # owed; that is a Phase 4 dispute decision, and the books show both.
        assert ledger.account_balance(LedgerAccount.PROVIDER_CLEARING) == 0
        assert (
            ledger.account_balance(
                LedgerAccount.TRAVELER_PAYABLE, user_id=self.scenario.traveler.pk
            )
            < 0
        )
        self.payout.refresh_from_db()
        assert self.payout.status == Payout.Status.NOT_ELIGIBLE


class ManualRefundSettlementTests(TestCase):
    """A rail with no refund API still has to be able to finish a refund.

    Found by the Phase 3 finance-state review: a Chargily refund was left
    `pending` with the order stuck in `refund_pending` and no operator path to
    close it — an obligation the system could see and not discharge.
    """

    def setUp(self):
        _enable_mock()
        self.scenario = build_scenario(prefix="manual-refund")
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()
        self.attempt = pay_order_with_mock(self.client, self.order)
        # Re-badge the capture as Chargily: that rail has no refund endpoint.
        PaymentAttempt.objects.filter(pk=self.attempt.pk).update(provider="chargily")
        self.attempt.refresh_from_db()

    def _client(self, user):
        from rest_framework.test import APIClient

        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def _pending_refund(self) -> PaymentRefund:
        from apps.finance.services import request_refund

        with self.captureOnCommitCallbacks(execute=True):
            refund = request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )
        refund.refresh_from_db()
        return refund

    def test_a_rail_without_a_refund_api_leaves_the_refund_pending(self):
        refund = self._pending_refund()

        assert refund.status == PaymentRefund.Status.PENDING
        assert refund.failure_code == "refund_not_supported"
        assert refund.requires_manual_action is True
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
            status=ScheduledJob.Status.PENDING,
        ).exists()
        self.order.refresh_from_db()
        assert self.order.status == PaymentOrder.Status.REFUND_PENDING

    def test_an_operator_can_settle_it_with_evidence(self):
        refund = self._pending_refund()

        response = self._client(self.scenario.admin).post(
            reverse("finance-admin-refund-settle", args=[refund.pk]),
            {"settlement_reference": "BANK-OUT-91", "settlement_note": "CCP transfer"},
            format="json",
        )

        assert response.status_code == 200, response.data
        refund.refresh_from_db()
        self.order.refresh_from_db()
        assert refund.status == PaymentRefund.Status.SUCCEEDED
        assert refund.settled_by_id == self.scenario.admin.pk
        assert refund.settlement_reference == "BANK-OUT-91"
        assert refund.requires_manual_action is False
        assert self.order.status == PaymentOrder.Status.REFUNDED
        assert self.order.refunded_eur_cents == int(self.attempt.amount_eur_cents)
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
            status=ScheduledJob.Status.SUCCEEDED,
        ).exists()

    def test_settlement_writes_exactly_one_ledger_refund(self):
        from apps.finance.models import LedgerTransaction

        refund = self._pending_refund()
        self._client(self.scenario.admin).post(
            reverse("finance-admin-refund-settle", args=[refund.pk]),
            {"settlement_reference": "BANK-OUT-92"},
            format="json",
        )
        # A double submit changes nothing.
        self._client(self.scenario.admin).post(
            reverse("finance-admin-refund-settle", args=[refund.pk]),
            {"settlement_reference": "BANK-OUT-92"},
            format="json",
        )

        assert LedgerTransaction.objects.filter(kind="refund").count() == 1

    def test_settlement_without_a_reference_is_refused(self):
        """Refused at three levels: serializer, service, and check constraint."""

        from apps.finance.services import RefundNotPermitted, settle_refund_manually

        refund = self._pending_refund()

        # The HTTP layer refuses a blank reference outright.
        response = self._client(self.scenario.admin).post(
            reverse("finance-admin-refund-settle", args=[refund.pk]),
            {"settlement_reference": "   "},
            format="json",
        )
        assert response.status_code == 400, response.data

        # And so does the service, for any caller that bypasses it.
        with self.assertRaises(RefundNotPermitted):
            settle_refund_manually(
                refund_id=refund.pk,
                admin_actor_id=self.scenario.admin.pk,
                settlement_reference="   ",
            )

        refund.refresh_from_db()
        assert refund.status == PaymentRefund.Status.PENDING

    def test_only_staff_may_settle_a_refund(self):
        refund = self._pending_refund()

        for user in (self.scenario.sender, self.scenario.traveler, self.scenario.outsider):
            response = self._client(user).post(
                reverse("finance-admin-refund-settle", args=[refund.pk]),
                {"settlement_reference": "X"},
                format="json",
            )
            assert response.status_code == 403, user

    def test_the_database_refuses_a_settled_refund_with_no_reference(self):
        from django.db import IntegrityError, transaction

        refund = self._pending_refund()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                PaymentRefund.objects.filter(pk=refund.pk).update(
                    settled_by_id=self.scenario.admin.pk, settlement_reference=""
                )
