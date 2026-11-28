"""Rule R4: a job run owns its claim (G-E2).

Every claim stamps the job's `locked_at`. A run writes its end, whichever of
the five it is (no handler, deferred, permanent failure, failure, success),
only while the job is still running under that stamp. A run that lost its
claim, to `requeue_stuck_jobs` and a newer claim, writes nothing, and the newer
claim's outcome stands. A wake recorded during a run is kept whatever the run
answers.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.finance import jobs
from apps.finance.models import ScheduledJob

#: The five ends of a run, the failure both before and after its tries ran out.
COMPLETIONS = ("no_handler", "deferred", "permanent", "retry", "exhausted", "success")


def ending(name):
    """A handler whose run ends as `name`."""

    def handler(_payload):
        if name == "deferred":
            raise jobs.JobDeferred("Not yet.", code="wait", delay=timedelta(hours=1))
        if name == "permanent":
            raise jobs.PermanentJobError("Never.", code="never")
        if name in ("retry", "exhausted"):
            raise jobs.RetryableJobError("Again.", code="again")
        return f"{name}_result"

    return handler


def run(job, name):
    handlers = {} if name == "no_handler" else {job.kind: ending(name)}
    with mock.patch.dict(jobs.HANDLERS, handlers, clear=name == "no_handler"):
        return jobs.run_job(job)


class ClaimTestCase(TestCase):
    def make_job(self, name, *, key):
        return ScheduledJob.objects.create(
            key=key,
            kind=ScheduledJob.Kind.PROVIDER_RECONCILE,
            payload={"attempt_id": 1},
            run_at=timezone.now() - timedelta(minutes=30),
            attempts=7 if name == "exhausted" else 0,
            max_attempts=8,
        )

    def stale_and_fresh(self, name, *, key):
        """A run presumed dead, its job requeued and claimed again."""

        self.make_job(name, key=key)
        [stale] = jobs.claim_due_jobs(
            limit=1, at=timezone.now() - timedelta(minutes=20)
        )
        assert jobs.requeue_stuck_jobs() == 1
        [fresh] = jobs.claim_due_jobs(limit=1)
        assert fresh.locked_at != stale.locked_at
        return stale, fresh


class AStaleRunWritesNothing(ClaimTestCase):
    def test_while_the_newer_claim_runs(self):
        for name in COMPLETIONS:
            with self.subTest(name):
                stale, fresh = self.stale_and_fresh(name, key=f"stale-first:{name}")

                run(stale, name)

                job = ScheduledJob.objects.get(pk=fresh.pk)
                assert job.status == ScheduledJob.Status.RUNNING
                assert job.locked_at == fresh.locked_at
                assert job.locked_by == fresh.locked_by
                assert job.attempts == fresh.attempts
                assert (job.last_result, job.last_error_code) == ("", "")
                assert job.last_attempt_at is None

                run(fresh, "success")
                job.refresh_from_db()
                assert job.status == ScheduledJob.Status.SUCCEEDED
                assert job.last_result == "success_result"
                assert job.attempts == fresh.attempts + 1

    def test_after_the_newer_claim_armed_it_again(self):
        for name in COMPLETIONS:
            with self.subTest(name):
                stale, fresh = self.stale_and_fresh(name, key=f"fresh-first:{name}")
                run(fresh, "deferred")
                armed = ScheduledJob.objects.get(pk=fresh.pk)
                assert armed.status == ScheduledJob.Status.PENDING

                run(stale, name)

                job = ScheduledJob.objects.get(pk=fresh.pk)
                assert job.status == ScheduledJob.Status.PENDING
                assert job.run_at == armed.run_at
                assert job.attempts == armed.attempts
                assert job.last_result == "deferred:wait"
                assert job.last_attempt_at == armed.last_attempt_at
                assert job.completed_at is None
