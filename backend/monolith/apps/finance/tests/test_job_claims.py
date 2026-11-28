"""Rule R4: a job run owns its claim (G-E2).

Every claim stamps the job's `locked_at`. A run writes its end, whichever of
the five it is (no handler, deferred, permanent failure, failure, success),
only while the job is still running under that stamp. A run that lost its
claim, to `requeue_stuck_jobs` and a newer claim, writes nothing, and the newer
claim's outcome stands. A wake recorded during a run is kept whatever the run
answers.
"""

from __future__ import annotations

import ast
from datetime import timedelta
from pathlib import Path
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from apps.finance import jobs, services
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


class AWakeDuringTheClaimIsKept(ClaimTestCase):
    def test_by_each_completion(self):
        for number, name in enumerate(COMPLETIONS, start=1):
            with self.subTest(name):
                self.make_job(name, key=f"provider_reconcile:{number}")
                [claimed] = jobs.claim_due_jobs(limit=1)
                # A close asked for while it runs (`_record_close_intent`).
                services._arm_checkout_settle(number)
                woken = ScheduledJob.objects.get(pk=claimed.pk).run_at
                assert woken > claimed.locked_at

                run(claimed, name)

                job = ScheduledJob.objects.get(pk=claimed.pk)
                assert job.status == ScheduledJob.Status.PENDING
                assert job.run_at == woken
                assert job.completed_at is None
                assert (job.locked_at, job.locked_by) == (None, "")


class AJobThatIsNotACheckout(TestCase):
    """The runner treats every kind alike: a rating reveal ends as before."""

    def setUp(self):
        self.job = ScheduledJob.objects.create(
            key="rating_reveal:1",
            kind=ScheduledJob.Kind.RATING_REVEAL,
            payload={"deal_id": 1},
            run_at=timezone.now(),
        )

    def run_cycle(self, name):
        with mock.patch.dict(jobs.HANDLERS, {self.job.kind: ending(name)}):
            report = jobs.run_due_jobs()
        assert report.claimed == 1
        self.job.refresh_from_db()
        assert (self.job.locked_at, self.job.locked_by) == (None, "")
        assert self.job.last_attempt_at is not None
        return report

    def test_succeeds(self):
        assert self.run_cycle("success").results == ["success_result"]
        assert self.job.status == ScheduledJob.Status.SUCCEEDED
        assert (self.job.attempts, self.job.last_result) == (1, "success_result")
        assert self.job.completed_at is not None

    def test_defers_without_spending_a_try(self):
        before = timezone.now()
        assert self.run_cycle("deferred").deferred == 1
        assert self.job.status == ScheduledJob.Status.PENDING
        assert (self.job.attempts, self.job.last_result) == (0, "deferred:wait")
        assert self.job.run_at >= before + timedelta(hours=1)
        assert self.job.completed_at is None

    def test_retries_with_backoff_then_fails(self):
        before = timezone.now()
        assert self.run_cycle("retry").failed == 1
        assert self.job.status == ScheduledJob.Status.PENDING
        assert (self.job.attempts, self.job.last_error_code) == (1, "again")
        assert self.job.run_at >= before + timedelta(seconds=60)

        ScheduledJob.objects.filter(pk=self.job.pk).update(
            run_at=timezone.now(), attempts=self.job.max_attempts - 1
        )
        self.run_cycle("retry")
        assert self.job.status == ScheduledJob.Status.FAILED
        assert self.job.completed_at is not None

    def test_fails_for_good(self):
        self.run_cycle("permanent")
        assert self.job.status == ScheduledJob.Status.FAILED
        assert (self.job.attempts, self.job.last_error_code) == (1, "never")


class OnlyTheRunWritesItsEnd(TestCase):
    """Mechanical check: no `ScheduledJob` completion is written elsewhere."""

    SOURCE = Path(__file__).resolve().parents[2]

    def functions(self):
        for path in sorted(self.SOURCE.rglob("*.py")):
            parts = path.relative_to(self.SOURCE).parts
            if "tests" in parts or "migrations" in parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    yield path.relative_to(self.SOURCE).as_posix(), node

    @staticmethod
    def names_running(node) -> bool:
        return any(
            (isinstance(n, ast.Attribute) and n.attr == "RUNNING")
            or (isinstance(n, ast.Constant) and n.value == "running")
            for n in ast.walk(node)
        )

    def test_only_the_helper_records_a_run(self):
        # A run's end is the only write of when it was last tried.
        writers = {
            (path, function.name)
            for path, function in self.functions()
            for node in ast.walk(function)
            if (
                isinstance(node, ast.Call)
                and any(k.arg == "last_attempt_at" for k in node.keywords)
            )
            or (
                isinstance(node, ast.Attribute)
                and node.attr == "last_attempt_at"
                and isinstance(node.ctx, ast.Store)
            )
        }
        assert writers == {("finance/jobs.py", "_complete_run")}

    def test_no_other_write_targets_a_running_job(self):
        # `X.filter(status=running ...).update(...)`, anywhere.
        writers = {
            (path, function.name)
            for path, function in self.functions()
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "update"
            and isinstance(node.func.value, ast.Call)
            and any(
                k.arg in ("status", "status__in") and self.names_running(k.value)
                for k in node.func.value.keywords
            )
        }
        # The run's own end, and the requeue that takes a claim from a run
        # presumed dead.
        assert writers == {
            ("finance/jobs.py", "_complete_run"),
            ("finance/jobs.py", "requeue_stuck_jobs"),
        }
