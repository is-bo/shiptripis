"""Rule G-E: the obligation to follow a checkout cannot be lost.

Every outstanding attempt (`OUTSTANDING`: a checkout that can still collect,
or a held payment) has a settle job that is pending or running. The job loop's
sweep restores one wherever it is missing, and the job reports done only once
the attempt is no longer outstanding. A close intent is committed together
with the wake of its settle job (R2, R3).
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.utils import timezone

from apps.finance import jobs, services
from apps.finance.models import PaymentAttempt, ScheduledJob
from apps.finance.providers import ProviderUnavailable
from apps.finance.providers.mock import MockGateway
from apps.finance.services import (
    CHECKOUT_JOB_ATTEMPTS,
    CheckoutInProgress,
    cancel_order,
)

from .factories import claim
from .test_held_payments import HeldPaymentTestCase

#: The retry delay's cap: how long a settle job whose tries ran out waits
#: before the sweep's next read.
CAPPED = timedelta(hours=6)


class WorkerDied(BaseException):
    """The process stops here: nothing after this line runs."""


class TheCloseIntentCommitsWithItsWake(HeldPaymentTestCase):
    def test_a_crash_after_the_close_intent_leaves_its_settle_job_due(self):
        own = self.owner_taps().attempt
        settle = self.settle_job(own)
        assert settle.run_at > timezone.now()

        # The guest's tap replaces the owner's checkout: it records the close
        # intent, commits, and dies before asking the provider.
        with (
            mock.patch.object(services, "settle_checkout", side_effect=WorkerDied),
            self.assertRaises(WorkerDied),
        ):
            self.guest_taps()

        own.refresh_from_db()
        assert own.close_requested_at is not None
        settle.refresh_from_db()
        assert settle.status == ScheduledJob.Status.PENDING
        assert settle.run_at <= timezone.now()

    def test_a_crash_before_it_commits_leaves_neither(self):
        own = self.owner_taps().attempt
        before = self.settle_job(own)
        real = services._record_close_intent

        def dies_after(attempt, **kwargs):
            real(attempt, **kwargs)
            raise WorkerDied

        with (
            mock.patch.object(services, "_record_close_intent", new=dies_after),
            self.assertRaises(WorkerDied),
        ):
            self.guest_taps()

        own.refresh_from_db()
        assert own.close_requested_at is None
        settle = self.settle_job(own)
        assert (settle.status, settle.run_at) == (before.status, before.run_at)

    def test_a_close_asked_for_again_keeps_the_jobs_backoff(self):
        own = self.owner_taps().attempt
        MockGateway.fail_close(own.provider_session_id, ProviderUnavailable("down"))
        with self.assertRaises(CheckoutInProgress):
            self.guest_taps()
        settle = self.settle_job(own)
        assert settle.run_at <= timezone.now()

        assert jobs.run_job(claim(settle)) == "failed"
        settle.refresh_from_db()
        backoff = settle.run_at
        assert backoff > timezone.now()

        # The provider is still down: the guest's next tap asks for the same
        # close and does not read it hot.
        with self.assertRaises(CheckoutInProgress):
            self.guest_taps()
        settle.refresh_from_db()
        assert (settle.status, settle.run_at) == (ScheduledJob.Status.PENDING, backoff)


class TheSweepArmsEveryOutstandingAttempt(HeldPaymentTestCase):
    def sweep(self):
        jobs._sweep_outstanding_attempts()

    def armed(self, attempt_ids):
        return set(
            ScheduledJob.objects.filter(
                key__in=[f"provider_reconcile:{pk}" for pk in attempt_ids],
                status__in=(ScheduledJob.Status.PENDING, ScheduledJob.Status.RUNNING),
            ).values_list("key", flat=True)
        )

    def test_more_than_its_limit_within_two_cycles(self):
        template = self.owner_taps().attempt
        rows = []
        for number in range(101):
            row = PaymentAttempt.objects.get(pk=template.pk)
            row.pk = None
            row.status = PaymentAttempt.Status.CANCELLED
            row.provider_session_id = f"never_closed_{number}"
            row.idempotency_key = f"never-closed-{number}"
            rows.append(row)
        ids = sorted(row.pk for row in PaymentAttempt.objects.bulk_create(rows))
        assert services.arm_outstanding_attempts.__kwdefaults__["limit"] == 100

        self.sweep()
        assert self.armed(ids) == {f"provider_reconcile:{pk}" for pk in ids[:100]}
        self.sweep()
        assert len(self.armed(ids)) == 101
        assert services.arm_outstanding_attempts() == 0

    def test_a_job_whose_tries_ran_out_is_armed_after_the_capped_delay(self):
        own = self.owner_taps().attempt
        cancel_order(order_id=self.order.pk, reason="g1b test")
        settle = self.settle_job(own)
        MockGateway.fail_close(own.provider_session_id, ProviderUnavailable("down"))
        ScheduledJob.objects.filter(pk=settle.pk).update(
            attempts=CHECKOUT_JOB_ATTEMPTS - 1
        )
        assert jobs.run_job(claim(settle)) == "failed"
        settle.refresh_from_db()
        assert settle.status == ScheduledJob.Status.FAILED

        before = timezone.now()
        self.sweep()
        settle.refresh_from_db()
        assert (settle.status, settle.attempts) == (ScheduledJob.Status.PENDING, 0)
        assert before + CAPPED <= settle.run_at <= timezone.now() + CAPPED
        due = settle.run_at
        self.sweep()
        settle.refresh_from_db()
        assert settle.run_at == due

    def test_a_held_payment_whose_job_ran_out(self):
        own = self.held(amount_delta=1)
        assert own.checkout_final_at is not None
        settle = self.settle_job(own)
        ScheduledJob.objects.filter(pk=settle.pk).update(
            status=ScheduledJob.Status.FAILED, completed_at=timezone.now()
        )

        before = timezone.now()
        self.sweep()
        settle.refresh_from_db()
        assert settle.status == ScheduledJob.Status.PENDING
        assert settle.run_at >= before + CAPPED

    def test_never_pulls_a_pending_job_forward(self):
        own = self.owner_taps().attempt
        settle = self.settle_job(own)
        assert settle.run_at > timezone.now()

        self.sweep()
        assert self.settle_job(own).run_at == settle.run_at

    def test_a_settle_job_reports_done_only_once_the_attempt_is_accounted_for(self):
        own = self.owner_taps().attempt
        with mock.patch.object(
            services, "settle_checkout", return_value="attempt_cancelled"
        ):
            assert jobs.run_job(claim(self.settle_job(own))) == "failed"
        settle = self.settle_job(own)
        assert settle.status == ScheduledJob.Status.PENDING
        assert settle.last_error_code == "outstanding_attempt_cancelled"
