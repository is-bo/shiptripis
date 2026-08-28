from __future__ import annotations

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, close_old_connections

from apps.deals.services import release_expired_reservations


class Command(BaseCommand):
    help = "Continuously release expired pre-funding capacity reservations."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--interval", type=int, default=60)
        parser.add_argument("--batch-size", type=int, default=100)

    def handle(self, *args, **options):
        del args
        interval = options["interval"]
        batch_size = options["batch_size"]
        if not 5 <= interval <= 3_600:
            raise CommandError("Interval must be between 5 and 3,600 seconds.")
        if not 1 <= batch_size <= 10_000:
            raise CommandError("Batch size must be between 1 and 10,000.")

        self.stdout.write("Reservation releaser started.")
        while True:
            close_old_connections()
            try:
                results = release_expired_reservations(limit=batch_size)
            except DatabaseError as exc:
                self.stderr.write(
                    f"Reservation release sweep failed: {type(exc).__name__}"
                )
            else:
                changed = sum(int(result.changed) for result in results)
                if changed:
                    self.stdout.write(f"Released {changed} expired deal reservations.")
            finally:
                close_old_connections()
            time.sleep(interval)
