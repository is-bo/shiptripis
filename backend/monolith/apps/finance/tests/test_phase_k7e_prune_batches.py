"""Phase K7-E — `prune_scheduled_jobs --execute` deletes in bounded batches.

K7 package B found the command locked and deleted every eligible row in one
transaction, which is fine for a handful of rows and not for the backlog the
first scheduled run will meet. It now deletes at most ``--batch-size`` rows per
transaction. These tests pin that the batches are bounded and separate, and
that the rows deleted are exactly the rows the eligibility rule selects.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.finance.models import ScheduledJob

DELETE_SQL = 'DELETE FROM "finance_scheduled_job"'


class ScheduledJobPruneBatchTests(TestCase):
    def setUp(self):
        now = timezone.now()
        old = now - timedelta(days=120)
        recent = now - timedelta(days=10)
        self.eligible_ids = set()
        self.kept_ids = set()

        def job(name, *, status, completed_at, resolution="", eligible):
            row = ScheduledJob.objects.create(
                key=f"k7e-prune-{name}",
                kind=ScheduledJob.Kind.ATTEMPT_EXPIRY,
                run_at=completed_at or old,
                status=status,
                completed_at=completed_at,
                resolution=resolution,
                resolved_at=completed_at if resolution else None,
                resolution_reason="Reviewed" if resolution else "",
            )
            (self.eligible_ids if eligible else self.kept_ids).add(row.pk)

        # Interleave kept rows between eligible ones so a batch boundary can
        # never be mistaken for an eligibility boundary.
        for index in range(5):
            job(
                f"old-ok-{index}",
                status=ScheduledJob.Status.SUCCEEDED,
                completed_at=old,
                eligible=True,
            )
            job(
                f"recent-ok-{index}",
                status=ScheduledJob.Status.SUCCEEDED,
                completed_at=recent,
                eligible=False,
            )
        for resolution in ScheduledJob.Resolution.values:
            job(
                f"old-{resolution}",
                status=ScheduledJob.Status.FAILED,
                completed_at=old,
                resolution=resolution,
                eligible=True,
            )
        job(
            "old-unresolved",
            status=ScheduledJob.Status.FAILED,
            completed_at=old,
            eligible=False,
        )
        job(
            "old-cancelled",
            status=ScheduledJob.Status.CANCELLED,
            completed_at=old,
            eligible=False,
        )
        job(
            "pending",
            status=ScheduledJob.Status.PENDING,
            completed_at=None,
            eligible=False,
        )
        # 5 succeeded + 3 resolved failures.
        self.assertEqual(len(self.eligible_ids), 8)

    def run_prune(self, **options) -> tuple[str, list[str]]:
        output = StringIO()
        with CaptureQueriesContext(connection) as captured:
            call_command("prune_scheduled_jobs", execute=True, stdout=output, **options)
        return output.getvalue(), [query["sql"] for query in captured.captured_queries]

    def assert_exactly_the_eligible_rows_were_deleted(self):
        remaining = set(ScheduledJob.objects.values_list("pk", flat=True))
        self.assertEqual(remaining & self.eligible_ids, set())
        self.assertEqual(remaining, self.kept_ids)

    def test_small_batches_delete_exactly_the_eligible_rows(self):
        output, statements = self.run_prune(batch_size=3)

        self.assert_exactly_the_eligible_rows_were_deleted()
        self.assertIn("deleted 8 scheduled job row(s)", output)
        deletes = [sql for sql in statements if sql.startswith(DELETE_SQL)]
        # ceil(8 / 3) = 3 bounded deletes, each in its own transaction (a
        # savepoint under TestCase): 3 deleting batches plus the empty probe.
        self.assertEqual(len(deletes), 3)
        savepoints = [sql for sql in statements if sql.startswith("SAVEPOINT")]
        self.assertEqual(len(savepoints), 4)
        # SQLite (test_local) has no row locks, so Django drops the clause;
        # the per-batch lock is only observable on PostgreSQL.
        if connection.features.has_select_for_update:
            locks = [sql for sql in statements if "FOR NO KEY UPDATE" in sql]
            self.assertEqual(len(locks), 4)
            self.assertTrue(all("LIMIT 3" in sql for sql in locks), locks)

    def test_default_batch_holds_a_small_backlog_in_one_transaction(self):
        output, statements = self.run_prune()

        self.assert_exactly_the_eligible_rows_were_deleted()
        self.assertIn("deleted 8 scheduled job row(s)", output)
        self.assertEqual(
            len([sql for sql in statements if sql.startswith(DELETE_SQL)]), 1
        )

    def test_dry_run_is_unchanged_and_deletes_nothing(self):
        output = StringIO()
        call_command("prune_scheduled_jobs", batch_size=3, stdout=output)
        self.assertIn(
            "dry-run: 8 scheduled job row(s) older than 90 days", output.getvalue()
        )
        self.assertEqual(
            ScheduledJob.objects.count(), len(self.eligible_ids) + len(self.kept_ids)
        )

    def test_batch_size_must_be_positive(self):
        with self.assertRaises(CommandError):
            call_command("prune_scheduled_jobs", execute=True, batch_size=0)
        self.assertEqual(
            ScheduledJob.objects.count(), len(self.eligible_ids) + len(self.kept_ids)
        )
