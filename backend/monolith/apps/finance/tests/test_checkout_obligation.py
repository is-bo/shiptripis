"""Rule G-E: the obligation to follow a checkout cannot be lost.

Every outstanding attempt (`OUTSTANDING`: a checkout that can still collect,
or a held payment) has a settle job that is pending or running. The job loop's
sweep restores one wherever it is missing, and the job reports done only once
the attempt is no longer outstanding. A close intent is committed together
with the wake of its settle job (R2, R3).
"""

from __future__ import annotations

from unittest import mock

from django.utils import timezone

from apps.finance import services
from apps.finance.models import ScheduledJob

from .test_held_payments import HeldPaymentTestCase


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
