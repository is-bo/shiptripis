"""Daily detection-only outbox sweep (CLAUDE.md G6b).

For every `PublishedEvent` row where `delivered_at IS NULL` AND
`published_at < now - 5 minutes`, check whether the Go side wrote
`delivered:<event_id>` to Redis. If yes, mark delivered. If not,
log + emit Sentry warning — that's an event we lost.

V1 is detection-only: we do NOT re-publish. Full transactional outbox
is V2.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
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

    def handle(self, *args, **opts) -> None:  # noqa: ANN002, ANN003
        cutoff = timezone.now() - timedelta(seconds=opts["age_seconds"])
        client = redis_bus.get_client()

        qs = PublishedEvent.objects.filter(
            delivered_at__isnull=True,
            published_at__lt=cutoff,
        ).order_by("published_at")

        total = 0
        recovered = 0
        missing = 0
        for ev in qs.iterator():
            total += 1
            if client.exists(f"delivered:{ev.event_id}"):
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
