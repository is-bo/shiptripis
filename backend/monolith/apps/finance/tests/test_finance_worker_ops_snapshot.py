import itertools
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase

from apps.finance.jobs import JobRunReport

COMMAND = "apps.finance.management.commands.run_finance_worker"


class _StopLoop(Exception):
    pass


class FinanceWorkerOpsSnapshotTests(SimpleTestCase):
    def _run_one_iteration(self, snapshot, **options):
        with (
            patch(f"{COMMAND}.requeue_stuck_jobs"),
            patch(f"{COMMAND}.run_due_jobs", return_value=JobRunReport(0, 0, 0, 0, [])),
            patch(f"{COMMAND}.dispatch_due_messages", return_value=0),
            patch(f"{COMMAND}.consume_fcm_results", return_value=0),
            patch(f"{COMMAND}.log_ops_snapshot", side_effect=snapshot) as logged,
            # Each clock read jumps ten minutes, so the snapshot is due on the
            # first pass; the first sleep ends the loop.
            patch(f"{COMMAND}.time.monotonic", side_effect=itertools.count(0, 600)),
            patch(f"{COMMAND}.time.sleep", side_effect=_StopLoop),
            # Keep the worker's SIGTERM handler out of the test process.
            patch(f"{COMMAND}.signal.signal"),
        ):
            with self.assertRaises(_StopLoop):
                call_command("run_finance_worker", "--interval", "5", **options)
        return logged

    def test_worker_logs_the_ops_snapshot_when_due(self):
        logged = self._run_one_iteration(None)
        logged.assert_called_once_with()

    def test_a_failing_snapshot_never_stops_the_job_loop(self):
        logged = self._run_one_iteration(RuntimeError("redis down"))
        logged.assert_called_once_with()

    def test_snapshot_can_be_disabled(self):
        logged = self._run_one_iteration(None, ops_snapshot_seconds=0)
        logged.assert_not_called()
