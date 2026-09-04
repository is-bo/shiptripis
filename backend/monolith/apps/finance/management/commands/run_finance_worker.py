"""Long-running worker for durable financial jobs.

Deployed alongside the reservation releaser. The database is the queue, so this
process holds no state: killing it loses nothing, and starting a second one is
safe because claiming is row-locked.
"""

from __future__ import annotations

import signal
import time

from django.core.management.base import BaseCommand

from apps.finance.jobs import requeue_stuck_jobs, run_due_jobs
from apps.notifications.outbox import dispatch_due_messages
from apps.notifications.push import consume_fcm_results


class Command(BaseCommand):
    help = "Continuously run due finance jobs."

    def add_arguments(self, parser):
        parser.add_argument("--interval", type=int, default=30)
        parser.add_argument("--limit", type=int, default=50)
        parser.add_argument("--stale-after-seconds", type=int, default=900)

    def handle(self, *args, **options):
        interval = max(5, int(options["interval"]))
        running = {"value": True}

        def _stop(signum, frame):  # noqa: ARG001
            running["value"] = False

        for name in ("SIGINT", "SIGTERM"):
            handler = getattr(signal, name, None)
            if handler is not None:
                signal.signal(handler, _stop)

        self.stdout.write(f"finance worker started (interval={interval}s)")
        while running["value"]:
            try:
                requeue_stuck_jobs(
                    stale_after_seconds=options["stale_after_seconds"]
                )
                report = run_due_jobs(limit=options["limit"])
                # The outbox sweep is the same kind of backstop as
                # `release_expired_reservations`: a message whose ScheduledJob
                # was lost or exhausted still has to go out, and the row's own
                # `next_attempt_at` is the only thing that can notice. Without
                # a caller it was a safety net that had been documented but
                # never hung -- and the one message it protects goes to a
                # recipient with no account and no way to ask again.
                dispatched = dispatch_due_messages(limit=options["limit"])
                push_results = consume_fcm_results(limit=options["limit"])
                if report.claimed or dispatched or push_results:
                    self.stdout.write(
                        f"claimed={report.claimed} succeeded={report.succeeded} "
                        f"failed={report.failed} messages={dispatched} "
                        f"push_results={push_results}"
                    )
            except Exception as exc:  # noqa: BLE001 - the loop must survive
                self.stderr.write(f"finance worker iteration failed: {exc!r}")
            for _ in range(interval):
                if not running["value"]:
                    break
                time.sleep(1)
        self.stdout.write("finance worker stopped")
