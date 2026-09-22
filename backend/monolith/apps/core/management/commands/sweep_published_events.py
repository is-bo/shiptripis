"""Daily detection-only outbox sweep (CLAUDE.md G6b).

For every `PublishedEvent` row where `delivered_at IS NULL` AND
`published_at < now - 5 minutes`, check whether the Go side wrote
at least one `delivered:<event_id>:<user_id>` receipt to Redis. If yes, mark
delivered. If not, log + emit Sentry warning — that's an event we lost.

V1 is detection-only: we do NOT re-publish. Full transactional outbox
is V2.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.core import redis_bus
from apps.core.models import PublishedEvent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sweep undelivered PublishedEvent rows; reconcile against Redis delivered:* keys."

    def add_arguments(self, parser) -> None:  # noqa: ANN001
        parser.add_argument(
            "--age-seconds",
            type=int,
            default=5 * 60,
            help="Only sweep rows older than this many seconds (default: 300).",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=500,
            help="Maximum old events inspected in one run (default: 500).",
        )
        parser.add_argument(
            "--max-age-seconds",
            type=int,
            default=7 * 24 * 60 * 60,
            help=(
                "Ignore rows older than this many seconds (default: 7 days). "
                "Detection-only sweeps never clear a genuine miss, so without "
                "an upper bound the oldest permanently-missing rows would "
                "occupy the whole batch and newer events would never be "
                "inspected."
            ),
        )

    def handle(self, *args, **opts) -> None:  # noqa: ANN002, ANN003
        now = timezone.now()
        cutoff = now - timedelta(seconds=opts["age_seconds"])
        batch_size = opts["batch_size"]
        if not 1 <= batch_size <= 10_000:
            raise CommandError("batch-size must be between 1 and 10,000.")
        max_age_seconds = opts["max_age_seconds"]
        if max_age_seconds <= opts["age_seconds"]:
            raise CommandError("max-age-seconds must exceed age-seconds.")
        # A miss is reported for every run inside the window and then ages out.
        # That keeps the bounded batch moving forward instead of re-reading the
        # same unrecoverable head of the queue for ever.
        window_start = now - timedelta(seconds=max_age_seconds)
        client = redis_bus.get_client()

        qs = PublishedEvent.objects.filter(
            delivered_at__isnull=True,
            published_at__lt=cutoff,
            published_at__gte=window_start,
        ).order_by("published_at", "id")[:batch_size]

        total = 0
        recovered = 0
        missing = 0
        for ev in qs.iterator(chunk_size=min(batch_size, 500)):
            total += 1
            legacy_key = f"delivered:{ev.event_id}"
            has_receipt = bool(client.exists(legacy_key))
            if not has_receipt:
                has_receipt = next(
                    client.scan_iter(match=f"{legacy_key}:*", count=10),
                    None,
                ) is not None
            if has_receipt:
                redis_bus.mark_delivered(ev.event_id)
                recovered += 1
            else:
                missing += 1
                logger.warning(
                    "outbox_miss channel=%s event_id=%s published_at=%s",
                    ev.channel,
                    ev.event_id,
                    ev.published_at.isoformat(),
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"swept={total} recovered={recovered} missing={missing}"
            )
        )
