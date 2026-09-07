"""One-shot sweep of due financial jobs.

Safe to run from cron, a Railway one-off, or by hand. Everything it executes is
idempotent, so an overlapping run is a no-op rather than a double refund.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from apps.finance.jobs import requeue_stuck_jobs, run_due_jobs


class Command(BaseCommand):
    help = "Run every due finance job once and exit."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--stale-after-seconds", type=int, default=900)

    def handle(self, *args, **options):
        requeued = requeue_stuck_jobs(
            stale_after_seconds=options["stale_after_seconds"]
        )
        report = run_due_jobs(limit=options["limit"])
        self.stdout.write(
            f"requeued={requeued} claimed={report.claimed} "
            f"succeeded={report.succeeded} deferred={report.deferred} "
            f"failed={report.failed}"
        )
