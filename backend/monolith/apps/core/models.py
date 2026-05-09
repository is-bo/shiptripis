"""Cross-cutting models for the monolith.

`PublishedEvent` is the V1 detection-only outbox audit (CLAUDE.md G6b):
every Redis publish writes a row here. A daily Django cron compares
`delivered_at IS NULL AND published_at < now - 5min` against Redis
`delivered:<event_id>` keys and alerts on mismatches.

Full transactional outbox is V2. We don't auto-recover — but we detect.
"""

from __future__ import annotations

import uuid

from django.db import models


class PublishedEvent(models.Model):
    """Audit row written for each Redis pub/sub publish from Django.

    Schema is intentionally narrow — read by both Django (cron sweep) and
    sqlc-generated Go code (so chat/notif services can mark `delivered_at`
    when they observe the event downstream).
    """

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )
    channel = models.CharField(max_length=128, db_index=True)
    event_id = models.CharField(max_length=64, unique=True)
    payload_hash = models.CharField(max_length=64)  # sha256 hex
    published_at = models.DateTimeField(auto_now_add=True, db_index=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_published_event"
        indexes = [
            models.Index(
                fields=["delivered_at", "published_at"],
                name="core_pe_undelivered_idx",
            ),
        ]
        ordering = ["-published_at"]

    def __str__(self) -> str:
        return f"{self.channel}/{self.event_id}"
