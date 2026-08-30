"""Crash-point and at-least-once recovery regressions for financial work."""

from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from importlib import import_module
from unittest.mock import patch

from django.db import connection
from django.test import TransactionTestCase
from django.test.client import Client
from django.utils import timezone

from apps.core.business_settings import get_active_business_settings
from apps.core.models import BusinessSettingsVersion
from apps.deals.models import Deal, DealLegAllocation
from apps.deals.services import release_pending_deal_reservation
from apps.finance import jobs
from apps.finance.models import (
    LedgerTransaction,
    PaymentAttempt,
    PaymentOrder,
    PaymentProviderEvent,
    PaymentRefund,
    ScheduledJob,
)
from apps.finance.providers.mock import MockGateway
from apps.finance.providers.base import (
    ProviderEvent,
    ProviderUnavailable,
    RefundResult,
)
from apps.finance.services import (
    REFUND_MANUAL_ESCALATION_ATTEMPTS,
    _settle_refund_with_provider,
    apply_provider_event,
    ensure_posting_deposit_order,
    request_refund,
    settle_refund_manually,
)

from .assertions import (
    assert_financial_conservation,
    assert_provider_funds_are_locally_accounted,
)
from .factories import (
    build_scenario,
    deliver_mock_webhook,
    open_mock_checkout,
    succeed_attempt,
)


def _seed_and_enable_mock() -> None:
    active = BusinessSettingsVersion.objects.filter(status="active").first()
    if active is None:
        document = import_module(
            "apps.core.migrations.0005_seed_phase3_payment_settings"
        ).PHASE3_POLICY
        active = BusinessSettingsVersion.objects.create(
            version=3,
            status=BusinessSettingsVersion.Status.ACTIVE,
            canonical_currency="EUR",
            commission_rate_bps=2_500,
            pricing_version="v1-payments-1",
            policy=deepcopy(document),
            activated_at=timezone.now(),
        )
    settings_version = get_active_business_settings()
    policy = deepcopy(settings_version.policy)
    policy["payments"]["providers"]["mock_enabled"] = True
    BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
        policy=policy
    )


class RecoveryTestCase(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_and_enable_mock()
        self.scenario = build_scenario(prefix=self.__class__.__name__.lower())
        self.scenario.accept(reward_eur_cents=3_200)
        self.order = self.scenario.balance_order()
        self.attempt = open_mock_checkout(self.order)
        # The provider's own handle, captured before anything can roll back.
        # Conservation is asserted against the rail's record, not against the
        # database row the code under test is allowed to lose.
        self.session_id = self.attempt.provider_session_id
        MockGateway.mark(self.session_id, "succeeded")
        self.body = succeed_attempt(self.attempt, event_id="evt_recovery")

    def _event(self) -> PaymentProviderEvent:
        return PaymentProviderEvent.objects.get(provider_event_id="evt_recovery")

    def _make_event_job_due(self, event: PaymentProviderEvent) -> None:
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
            payload__event_id=event.pk,
        ).update(status=ScheduledJob.Status.PENDING, run_at=timezone.now())

    def _assert_applied_once(self) -> None:
        event = self._event()
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        assert event.processing_result == PaymentProviderEvent.ProcessingResult.APPLIED
        assert self.attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert self.order.status == PaymentOrder.Status.PAID
        assert LedgerTransaction.objects.filter(kind="customer_payment").count() == 1
        assert LedgerTransaction.objects.filter(kind="deal_funding").count() == 1
        assert_provider_funds_are_locally_accounted(
            order_ids=[self.order.pk], session_ids=[self.session_id]
        )


class ProviderEventRecoveryTests(RecoveryTestCase):
    def test_crash_after_event_persistence_is_recovered_by_the_durable_job(self):
        with patch(
            "apps.finance.services.process_provider_event",
            side_effect=RuntimeError("crash after durable receipt"),
        ):
            response = deliver_mock_webhook(Client(), self.body)

        assert response.status_code == 200
        event = self._event()
        assert event.processing_result == PaymentProviderEvent.ProcessingResult.RETRYABLE
        self.attempt.refresh_from_db()
        assert self.attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING

        self._make_event_job_due(event)
        report = jobs.run_due_jobs(limit=10)

        assert report.failed == 0, report.results
        self._assert_applied_once()

    def test_duplicate_event_retries_after_ledger_write_rolls_back(self):
        # Customer payment is posted immediately before Deal funding. Raising
        # here simulates a crash after the ledger write but before funding; the
        # whole economic transaction must roll back while event receipt stays.
        with patch(
            "apps.finance.services._fund_deal_if_covered",
            side_effect=RuntimeError("crash before funding"),
        ):
            first = deliver_mock_webhook(Client(), self.body)

        assert first.status_code == 200
        event = self._event()
        assert event.processing_result == PaymentProviderEvent.ProcessingResult.RETRYABLE
        assert not LedgerTransaction.objects.filter(kind="customer_payment").exists()
        self.order.refresh_from_db()
        assert self.order.paid_eur_cents == 0

        duplicate = deliver_mock_webhook(Client(), self.body)

        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        self._assert_applied_once()

    def test_failure_after_attempt_success_before_order_recompute_converges(self):
        with patch(
            "apps.finance.services._recompute_order_money",
            side_effect=RuntimeError("crash before order recompute"),
        ):
            first = deliver_mock_webhook(Client(), self.body)

        assert first.status_code == 200
        self.attempt.refresh_from_db()
        assert self.attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING
        assert not LedgerTransaction.objects.filter(kind="customer_payment").exists()

        self._make_event_job_due(self._event())
        assert jobs.run_due_jobs(limit=10).failed == 0
        self._assert_applied_once()

    def test_event_job_claimed_before_worker_crash_is_requeued_and_applied(self):
        with patch(
            "apps.finance.services.process_provider_event",
            side_effect=RuntimeError("worker stops before application"),
        ):
            deliver_mock_webhook(Client(), self.body)
        event = self._event()
        self._make_event_job_due(event)
        claimed = jobs.claim_due_jobs(limit=1)
        assert len(claimed) == 1
        job = claimed[0]
        assert job.kind == ScheduledJob.Kind.PROVIDER_EVENT_PROCESS
        ScheduledJob.objects.filter(pk=job.pk).update(
            locked_at=timezone.now() - timedelta(hours=1)
        )

        assert jobs.requeue_stuck_jobs(stale_after_seconds=60) == 1
        assert jobs.run_due_jobs(limit=1).failed == 0
        self._assert_applied_once()


    def test_a_redelivered_event_re_arms_an_exhausted_recovery_job(self):
        """A dead recovery job must not make the redelivery the only chance.

        The gap this closes is a *kill*, not an exception: if the process dies
        mid-apply, `_mark_event_retryable` never runs, so the re-arm has to
        have happened before processing started. `_Killed` derives from
        `BaseException` precisely so `apply_provider_event`'s `except Exception`
        cannot rescue it, exactly as SIGKILL cannot be rescued.
        """

        class _Killed(BaseException):
            pass

        with patch(
            "apps.finance.services.process_provider_event",
            side_effect=RuntimeError("crash after durable receipt"),
        ):
            assert deliver_mock_webhook(Client(), self.body).status_code == 200

        event = self._event()
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.PROVIDER_EVENT_PROCESS,
            payload__event_id=event.pk,
        )
        job_key = job.key
        ScheduledJob.objects.filter(pk=job.pk).update(
            status=ScheduledJob.Status.FAILED,
            attempts=32,
            completed_at=timezone.now(),
        )

        redelivery = ProviderEvent(
            provider="mock",
            event_id="evt_recovery",
            event_type="checkout.paid",
            outcome="succeeded",
            provider_session_id=self.attempt.provider_session_id,
            provider_payment_id=f"{self.attempt.provider_session_id}_pi",
            reference=str(self.order.public_reference),
            amount_minor=int(self.attempt.provider_amount_minor),
            currency=self.attempt.payment_currency,
            payload={"id": "evt_recovery", "type": "checkout.paid"},
        )
        with patch(
            "apps.finance.services.process_provider_event",
            side_effect=_Killed("worker killed mid-apply"),
        ):
            with self.assertRaises(_Killed):
                apply_provider_event(redelivery)

        job = ScheduledJob.objects.get(key=job_key)
        assert job.status == ScheduledJob.Status.PENDING
        assert job.attempts == 0
        assert (
            self._event().processing_result
            != PaymentProviderEvent.ProcessingResult.APPLIED
        )

        ScheduledJob.objects.filter(pk=job.pk).update(run_at=timezone.now())
        report = jobs.run_due_jobs(limit=10)

        assert report.failed == 0, report.results
        self._assert_applied_once()


class RefundRecoveryTests(RecoveryTestCase):
    def setUp(self):
        super().setUp()
        deliver_mock_webhook(Client(), self.body)
        self.attempt.refresh_from_db()

    def test_remote_refund_success_then_local_failure_reuses_provider_refund(self):
        key = f"refund:attempt:{self.attempt.pk}:{PaymentRefund.Reason.ADMIN}"
        with patch(
            "apps.finance.services.mark_refund_succeeded",
            side_effect=RuntimeError("process died after provider success"),
        ):
            refund = request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        refund.refresh_from_db()
        assert refund.status == PaymentRefund.Status.PROCESSING
        assert MockGateway.refund_count(key) == 1
        assert MockGateway.refund_call_count(key) == 1
        assert not LedgerTransaction.objects.filter(kind="refund").exists()

        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
        ).update(status=ScheduledJob.Status.PENDING, run_at=timezone.now())
        with patch.dict(
            jobs.HANDLERS,
            {ScheduledJob.Kind.OUTBOUND_MESSAGE: lambda _payload: "dispatched"},
        ):
            report = jobs.run_due_jobs(limit=10)

        assert report.failed == 0, report.results
        refund.refresh_from_db()
        assert refund.status == PaymentRefund.Status.SUCCEEDED
        assert MockGateway.refund_count(key) == 1
        assert MockGateway.refund_call_count(key) == 2
        assert LedgerTransaction.objects.filter(kind="refund").count() == 1

    def test_provider_refund_call_runs_after_financial_locks_commit(self):
        observed: list[bool] = []
        original = MockGateway.refund

        def observe_atomic(gateway, request):
            observed.append(connection.in_atomic_block)
            return original(gateway, request)

        with patch.object(MockGateway, "refund", observe_atomic):
            request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        assert observed == [False]

    def test_pending_refund_is_re_driven_until_terminal(self):
        with patch.object(
            MockGateway,
            "refund",
            return_value=RefundResult(
                provider_refund_id="mock_re_pending",
                succeeded=False,
            ),
        ):
            refund = request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )

        refund.refresh_from_db()
        assert refund.status == PaymentRefund.Status.PENDING
        assert refund.next_retry_at is not None
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
        ).update(status=ScheduledJob.Status.PENDING, run_at=timezone.now())

        with patch.dict(
            jobs.HANDLERS,
            {ScheduledJob.Kind.OUTBOUND_MESSAGE: lambda _payload: "dispatched"},
        ):
            report = jobs.run_due_jobs(limit=10)

        assert report.failed == 0, report.results
        refund.refresh_from_db()
        assert refund.status == PaymentRefund.Status.SUCCEEDED

    def test_retry_exhaustion_keeps_refund_visible_for_operator(self):
        pending = RefundResult(
            provider_refund_id="mock_re_needs_review",
            succeeded=False,
        )
        with patch.object(MockGateway, "refund", return_value=pending):
            refund = request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )
            ScheduledJob.objects.filter(
                kind=ScheduledJob.Kind.REFUND_RECONCILE,
                payload__refund_id=refund.pk,
            ).update(
                status=ScheduledJob.Status.PENDING,
                run_at=timezone.now(),
                max_attempts=1,
            )
            with patch.dict(
                jobs.HANDLERS,
                {ScheduledJob.Kind.OUTBOUND_MESSAGE: lambda _payload: "dispatched"},
            ):
                report = jobs.run_due_jobs(limit=10)

        assert report.failed == 1
        refund.refresh_from_db()
        job = ScheduledJob.objects.get(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
        )
        assert refund.status == PaymentRefund.Status.PENDING
        assert job.status == ScheduledJob.Status.FAILED
        assert job.last_error

        same = request_refund(
            order_id=self.order.pk,
            attempt_id=self.attempt.pk,
            amount_eur_cents=int(self.attempt.amount_eur_cents),
            reason=PaymentRefund.Reason.ADMIN,
            requested_by_id=self.scenario.admin.pk,
        )
        job.refresh_from_db()
        assert same.pk == refund.pk
        assert job.status == ScheduledJob.Status.PENDING
        assert job.attempts == 0


    def test_an_unreachable_rail_escalates_the_refund_to_an_operator(self):
        """Retrying forever is not a plan: the customer is owed this money.

        A rail that has been unreachable for the whole retry budget will not
        fix itself, so the refund joins the manual queue while the automatic
        retries continue.
        """

        with patch.object(
            MockGateway,
            "refund",
            side_effect=ProviderUnavailable("the rail is down"),
        ):
            refund = request_refund(
                order_id=self.order.pk,
                attempt_id=self.attempt.pk,
                amount_eur_cents=int(self.attempt.amount_eur_cents),
                reason=PaymentRefund.Reason.ADMIN,
                requested_by_id=self.scenario.admin.pk,
            )
            refund.refresh_from_db()
            assert refund.status == PaymentRefund.Status.PENDING
            assert refund.requires_manual_action is False

            while refund.processing_attempts < REFUND_MANUAL_ESCALATION_ATTEMPTS:
                _settle_refund_with_provider(refund_id=refund.pk)
                refund.refresh_from_db()

        assert refund.status == PaymentRefund.Status.PENDING
        assert refund.requires_manual_action is True
        # Escalating does not abandon the retry, and it does not invent a
        # refund the provider never made.
        assert refund.next_retry_at is not None
        assert refund.succeeded_at is None
        assert not LedgerTransaction.objects.filter(kind="refund").exists()
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
        ).exists()

        settled = settle_refund_manually(
            refund_id=refund.pk,
            admin_actor_id=self.scenario.admin.pk,
            settlement_reference="BANK-ESCALATED-1",
        )
        assert settled.status == PaymentRefund.Status.SUCCEEDED
        assert settled.requires_manual_action is False


class LateProviderSuccessRecoveryTests(RecoveryTestCase):
    def test_provider_poll_survives_grace_expiry_and_refunds_late_money(self):
        result = release_pending_deal_reservation(
            deal_id=self.scenario.deal.pk,
            reason="payment_grace_expired",
        )
        assert result.changed is True
        ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            payload__attempt_id=self.attempt.pk,
        ).update(status=ScheduledJob.Status.PENDING, run_at=timezone.now())

        report = jobs.run_due_jobs(limit=10)

        assert report.failed == 0, report.results
        self.attempt.refresh_from_db()
        self.order.refresh_from_db()
        refund = PaymentRefund.objects.get(
            attempt=self.attempt,
            reason=PaymentRefund.Reason.UNAPPLIED_PAYMENT,
        )
        assert self.attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert self.attempt.is_unapplied is True
        assert refund.status == PaymentRefund.Status.SUCCEEDED
        assert self.order.status == PaymentOrder.Status.CANCELLED
        assert Deal.objects.get(pk=self.scenario.deal.pk).status == Deal.Status.EXPIRED
        assert not DealLegAllocation.objects.filter(
            deal=self.scenario.deal,
            status=DealLegAllocation.Status.FUNDED,
        ).exists()
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            payload__attempt_id=self.attempt.pk,
            status=ScheduledJob.Status.SUCCEEDED,
        ).exists()
        assert_provider_funds_are_locally_accounted(
            order_ids=[self.order.pk], session_ids=[self.session_id]
        )


class CheckoutRecoveryTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_and_enable_mock()

    def test_checkout_handle_is_recovered_with_the_original_idempotency_key(self):
        scenario = build_scenario(prefix="checkout-recovery", open_request=False)
        order = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            policy=scenario.policy,
        )
        attempt = open_mock_checkout(order)
        original_session = attempt.provider_session_id
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            provider_session_id="",
            checkout_url="",
            status=PaymentAttempt.Status.CREATED,
        )

        from apps.finance.services import recover_checkout_attempt

        assert recover_checkout_attempt(attempt_id=attempt.pk) == (
            "checkout_handle_recovered"
        )
        attempt.refresh_from_db()
        assert attempt.provider_session_id == original_session
        assert attempt.status == PaymentAttempt.Status.CHECKOUT_PENDING

    def test_checkout_provider_call_runs_without_database_transaction(self):
        scenario = build_scenario(prefix="checkout-io", open_request=False)
        order = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            policy=scenario.policy,
        )
        observed: list[bool] = []
        original = MockGateway.create_checkout

        def observe_atomic(gateway, request):
            observed.append(connection.in_atomic_block)
            return original(gateway, request)

        with patch.object(MockGateway, "create_checkout", observe_atomic):
            open_mock_checkout(order)

        assert observed == [False]


class ChargilyLateSuccessTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        publisher = patch("apps.core.redis_bus.publish_after_commit")
        publisher.start()
        self.addCleanup(publisher.stop)
        MockGateway.reset()
        _seed_and_enable_mock()

    def test_request_cancellation_keeps_manual_refund_obligation_reachable(self):
        from apps.parcels.services import cancel_delivery_request

        scenario = build_scenario(prefix="chargily-late", open_request=False)
        order = ensure_posting_deposit_order(
            delivery_request=scenario.delivery_request,
            policy=scenario.policy,
        )
        attempt = open_mock_checkout(order)
        provider_amount = int(attempt.amount_eur_cents) * 150
        PaymentAttempt.objects.filter(pk=attempt.pk).update(
            provider="chargily",
            payment_currency="DZD",
            provider_amount_minor=provider_amount,
            provider_amount_exponent=0,
            fx_rate_micros=150_000_000,
            fx_source="test-frozen-rate",
            fx_snapshot_at=timezone.now(),
        )
        attempt.refresh_from_db()
        cancel_delivery_request(
            request_id=scenario.delivery_request.pk,
            actor_id=scenario.sender.pk,
        )

        outcome = apply_provider_event(
            ProviderEvent(
                provider="chargily",
                event_id="evt_chargily_late_cancel",
                event_type="checkout.paid",
                outcome="succeeded",
                provider_session_id=attempt.provider_session_id,
                provider_payment_id="pay_chargily_late",
                reference=str(order.public_reference),
                amount_minor=provider_amount,
                currency="DZD",
                payload={"id": "evt_chargily_late_cancel"},
            )
        )

        assert outcome.handled is True
        attempt.refresh_from_db()
        order.refresh_from_db()
        scenario.delivery_request.refresh_from_db()
        event = PaymentProviderEvent.objects.get(
            provider_event_id="evt_chargily_late_cancel"
        )
        refund = PaymentRefund.objects.get(attempt=attempt)
        assert scenario.delivery_request.status == "cancelled"
        assert attempt.status == PaymentAttempt.Status.SUCCEEDED
        assert attempt.is_unapplied is True
        assert order.status == PaymentOrder.Status.CANCELLED
        assert event.processing_result == PaymentProviderEvent.ProcessingResult.APPLIED
        assert refund.status == PaymentRefund.Status.PENDING
        assert refund.requires_manual_action is True
        assert ScheduledJob.objects.filter(
            kind=ScheduledJob.Kind.REFUND_RECONCILE,
            payload__refund_id=refund.pk,
            status=ScheduledJob.Status.PENDING,
        ).exists()
        # Chargily's own figure is `provider_amount` dinars at the attempt's
        # frozen rate. The EUR the platform is accountable for is derived from
        # what the provider reported, not re-read from the row afterwards.
        assert_financial_conservation(
            external_success_eur_cents=provider_amount // 150,
            order_ids=[order.pk],
        )

        settled = settle_refund_manually(
            refund_id=refund.pk,
            admin_actor_id=scenario.admin.pk,
            settlement_reference="BANK-CHARGILY-LATE-1",
            settlement_note="Manual repayment evidence",
        )
        duplicate = settle_refund_manually(
            refund_id=refund.pk,
            admin_actor_id=scenario.admin.pk,
            settlement_reference="BANK-CHARGILY-LATE-1",
        )

        assert duplicate.pk == settled.pk
        assert LedgerTransaction.objects.filter(kind="refund").count() == 1
        assert PaymentProviderEvent.objects.filter(pk=event.pk).exists()
