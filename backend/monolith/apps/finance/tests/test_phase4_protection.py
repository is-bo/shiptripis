"""The 48-hour protection window and the payout release gate.

Phase 3 shipped a payout record with no way out of `not_eligible`, and made that
structural with `fin_payout_release_requires_eligibility`. Phase 4 supplies the
key. These tests are about the lock on that door: what has to be true before it
opens, that it does not open a second early, and that everything which drives it
can be run twice, interrupted, or restarted without changing the answer.

The dispute half of the gate lives in `apps/disputes/tests` and in the
PostgreSQL concurrency suite; what is checked here is the timer.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from apps.deals.models import Deal, DealEvent
from apps.deals.tests.phase4_factories import (
    confirm_delivery,
    confirm_pickup,
    delivered_scenario,
    freeze_at,
    fund_scenario,
    record_recipient,
    release_delivery_code,
    rewind_deal,
)
from apps.finance.jobs import run_due_jobs
from apps.finance.models import PaymentRefund, Payout, ScheduledJob
from apps.finance.payout_release import evaluate_payout_release
from apps.notifications.models import OutboundMessage


class ProtectionWindowTests(TestCase):
    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="prot")
        self.deal = self.scenario.deal

    def payout(self) -> Payout:
        return Payout.objects.get(deal_id=self.deal.pk)

    def test_delivery_confirmation_opens_the_window_and_arms_the_job(self):
        deal = self.deal
        assert deal.status == Deal.Status.PROTECTION_WINDOW
        assert deal.protection_ends_at == deal.delivery_confirmed_at + timedelta(
            hours=48
        )
        job = ScheduledJob.objects.get(key=f"protection_expiry:{deal.pk}")
        assert job.kind == ScheduledJob.Kind.PROTECTION_EXPIRY
        assert job.run_at == deal.protection_ends_at
        assert job.status == ScheduledJob.Status.PENDING
        assert DealEvent.objects.filter(
            deal_id=deal.pk, kind=DealEvent.Kind.PROTECTION_STARTED
        ).exists()

    def test_the_payout_stays_not_eligible_for_the_whole_window(self):
        for offset in (
            timedelta(seconds=1),
            timedelta(hours=24),
            timedelta(hours=48) - timedelta(seconds=1),
        ):
            at = self.deal.delivery_confirmed_at + offset
            with freeze_at(at):
                assert evaluate_payout_release(deal_id=self.deal.pk) == "protection_open"
            assert self.payout().status == Payout.Status.NOT_ELIGIBLE
            assert self.payout().eligible_at is None

    def test_one_second_before_the_deadline_is_still_protected(self):
        with freeze_at(self.deal.protection_ends_at - timedelta(seconds=1)):
            assert evaluate_payout_release(deal_id=self.deal.pk) == "protection_open"
        assert self.payout().status == Payout.Status.NOT_ELIGIBLE

    def test_exactly_at_the_deadline_the_payout_becomes_eligible(self):
        boundary = self.deal.protection_ends_at
        with freeze_at(boundary):
            assert evaluate_payout_release(deal_id=self.deal.pk) == "released"
        payout = self.payout()
        assert payout.status == Payout.Status.ELIGIBLE
        assert payout.eligible_at == boundary
        deal = self.scenario.deal
        assert deal.status == Deal.Status.COMPLETED
        assert deal.completed_at == boundary

    def test_release_appends_the_expiry_and_eligibility_timeline_entries(self):
        with freeze_at(self.deal.protection_ends_at):
            evaluate_payout_release(deal_id=self.deal.pk)
        kinds = set(
            DealEvent.objects.filter(deal_id=self.deal.pk).values_list(
                "kind", flat=True
            )
        )
        assert DealEvent.Kind.PROTECTION_EXPIRED in kinds
        assert DealEvent.Kind.PAYOUT_ELIGIBLE in kinds

    def test_a_second_evaluation_is_a_no_op(self):
        boundary = self.deal.protection_ends_at
        with freeze_at(boundary):
            evaluate_payout_release(deal_id=self.deal.pk)
        eligible_at = self.payout().eligible_at
        events = DealEvent.objects.filter(
            deal_id=self.deal.pk, kind=DealEvent.Kind.PAYOUT_ELIGIBLE
        ).count()

        with freeze_at(boundary + timedelta(hours=1)):
            result = evaluate_payout_release(deal_id=self.deal.pk)
        assert result == "payout_eligible"
        assert self.payout().eligible_at == eligible_at
        assert (
            DealEvent.objects.filter(
                deal_id=self.deal.pk, kind=DealEvent.Kind.PAYOUT_ELIGIBLE
            ).count()
            == events
        )

    def test_both_parties_are_told_the_protection_window_closed(self):
        with freeze_at(self.deal.protection_ends_at):
            evaluate_payout_release(deal_id=self.deal.pk)
        recipients = set(
            OutboundMessage.objects.filter(
                deal_id=self.deal.pk, kind=OutboundMessage.Kind.PROTECTION_ENDED
            ).values_list("recipient_user_id", flat=True)
        )
        assert recipients == {self.deal.sender_id, self.deal.traveler_id}


class ProtectionJobDurabilityTests(TestCase):
    """The obligation is the row, not the timer that happened to be running."""

    def setUp(self):
        self.scenario = delivered_scenario(self.client, prefix="protjob")
        self.deal = self.scenario.deal

    def test_the_job_refuses_to_run_early_and_is_retried(self):
        from apps.finance.jobs import JobFailed, handle_protection_expiry

        with freeze_at(self.deal.protection_ends_at - timedelta(seconds=1)):
            with self.assertRaises(JobFailed):
                handle_protection_expiry({"deal_id": self.deal.pk})
        assert Payout.objects.get(deal_id=self.deal.pk).status == (
            Payout.Status.NOT_ELIGIBLE
        )

    def test_a_worker_that_was_down_for_the_whole_window_still_releases_once(self):
        """Stop the worker, let 48 hours pass, start it again."""

        rewind_deal(self.deal, timedelta(hours=49))
        job_key = f"protection_expiry:{self.deal.pk}"
        ScheduledJob.objects.filter(key=job_key).update(
            run_at=timezone.now() - timedelta(hours=1)
        )
        run_due_jobs(limit=50)
        # Assert on this job, not on the whole queue: the queue also carries
        # email obligations, and this host has no Redis for them to reach.
        job = ScheduledJob.objects.get(key=job_key)
        assert job.status == ScheduledJob.Status.SUCCEEDED, job.last_error
        assert job.last_result == "released"

        payout = Payout.objects.get(deal_id=self.deal.pk)
        assert payout.status == Payout.Status.ELIGIBLE
        assert (
            DealEvent.objects.filter(
                deal_id=self.deal.pk, kind=DealEvent.Kind.PAYOUT_ELIGIBLE
            ).count()
            == 1
        )

        # And running the queue again changes nothing.
        run_due_jobs(limit=50)
        assert (
            DealEvent.objects.filter(
                deal_id=self.deal.pk, kind=DealEvent.Kind.PAYOUT_ELIGIBLE
            ).count()
            == 1
        )

    def test_a_duplicate_protection_job_releases_exactly_once(self):
        rewind_deal(self.deal, timedelta(hours=49))
        original = ScheduledJob.objects.get(key=f"protection_expiry:{self.deal.pk}")
        ScheduledJob.objects.create(
            key=f"protection_expiry:{self.deal.pk}:duplicate",
            kind=ScheduledJob.Kind.PROTECTION_EXPIRY,
            payload={"deal_id": self.deal.pk},
            run_at=timezone.now() - timedelta(hours=1),
        )
        ScheduledJob.objects.filter(pk=original.pk).update(
            run_at=timezone.now() - timedelta(hours=1)
        )

        run_due_jobs(limit=50)
        assert (
            DealEvent.objects.filter(
                deal_id=self.deal.pk, kind=DealEvent.Kind.PAYOUT_ELIGIBLE
            ).count()
            == 1
        )
        assert Payout.objects.filter(deal_id=self.deal.pk).count() == 1


class PayoutGatePreconditionTests(TestCase):
    """Every precondition, refused on its own."""

    def test_a_deal_that_never_confirmed_delivery_cannot_release(self):
        scenario = fund_scenario(self.client, prefix="gate1")
        record_recipient(scenario)
        confirm_pickup(scenario)
        assert evaluate_payout_release(deal_id=scenario.deal.pk) == (
            "delivery_not_confirmed"
        )
        assert Payout.objects.get(deal_id=scenario.deal.pk).status == (
            Payout.Status.NOT_ELIGIBLE
        )

    def test_a_cancelled_deal_cannot_release(self):
        scenario = delivered_scenario(self.client, prefix="gate2")
        Deal.objects.filter(pk=scenario.deal.pk).update(status=Deal.Status.CANCELLED)
        assert evaluate_payout_release(deal_id=scenario.deal.pk) == "deal_closed"

    def test_a_refund_in_flight_blocks_the_release(self):
        """Money on its way back out is not money that can be paid out."""

        from apps.finance.models import PaymentAttempt, PaymentOrder
        from apps.finance.services import request_refund

        scenario = delivered_scenario(self.client, prefix="gate3")
        order = PaymentOrder.objects.get(
            deal_id=scenario.deal.pk, purpose=PaymentOrder.Purpose.DEAL_BALANCE
        )
        attempt = PaymentAttempt.objects.filter(
            order=order, status=PaymentAttempt.Status.SUCCEEDED
        ).first()
        assert attempt is not None
        PaymentRefund.objects.create(
            order=order,
            attempt=attempt,
            amount_eur_cents=100,
            provider=attempt.provider,
            idempotency_key=f"test-inflight-{order.pk}",
            reason=PaymentRefund.Reason.ADMIN,
            status=PaymentRefund.Status.PENDING,
        )
        del request_refund  # the row above is deliberately hand-made and pending

        rewind_deal(scenario.deal, timedelta(hours=49))
        result = evaluate_payout_release(deal_id=scenario.deal.pk)
        assert result == "financial_state_refund_in_flight"
        assert Payout.objects.get(deal_id=scenario.deal.pk).status == (
            Payout.Status.NOT_ELIGIBLE
        )

    def test_the_database_still_refuses_a_released_payout_without_eligibility(self):
        """Phase 3's structural gate is intact, not merely unused."""

        from django.db import IntegrityError, transaction

        scenario = delivered_scenario(self.client, prefix="gate4")
        payout = Payout.objects.get(deal_id=scenario.deal.pk)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Payout.objects.filter(pk=payout.pk).update(
                    status=Payout.Status.ELIGIBLE, eligible_at=None
                )

    def test_a_manual_settlement_is_refused_until_the_gate_opens(self):
        from apps.finance.services import PayoutNotReleasable, complete_manual_payout

        scenario = delivered_scenario(self.client, prefix="gate5")
        payout = Payout.objects.get(deal_id=scenario.deal.pk)
        with self.assertRaises(PayoutNotReleasable):
            complete_manual_payout(
                payout_id=payout.pk,
                admin_actor_id=scenario.admin.pk,
                payout_currency="EUR",
                payout_amount_minor=int(payout.amount_eur_cents),
                reference="TEST-REF-1",
            )

        rewind_deal(scenario.deal, timedelta(hours=49))
        evaluate_payout_release(deal_id=scenario.deal.pk)
        settled = complete_manual_payout(
            payout_id=payout.pk,
            admin_actor_id=scenario.admin.pk,
            payout_currency="EUR",
            payout_amount_minor=int(payout.amount_eur_cents),
            reference="TEST-REF-1",
        )
        assert settled.status == Payout.Status.PAID


class ProtectionSnapshotTests(TestCase):
    def test_the_window_comes_from_the_deal_snapshot_not_live_settings(self):
        from copy import deepcopy

        from apps.core.business_settings import get_active_business_settings
        from apps.core.models import BusinessSettingsVersion

        scenario = fund_scenario(self.client, prefix="protsnap")
        record_recipient(scenario)
        confirm_pickup(scenario)

        settings_version = get_active_business_settings()
        policy = deepcopy(settings_version.policy)
        policy["payments"]["payout"]["protection_window_seconds"] = 60
        BusinessSettingsVersion.objects.filter(pk=settings_version.pk).update(
            policy=policy
        )

        release_delivery_code(scenario)
        confirm_delivery(scenario)
        deal = scenario.deal
        assert deal.protection_ends_at - deal.delivery_confirmed_at == timedelta(
            hours=48
        )
