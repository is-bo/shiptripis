"""Redis pub/sub publisher with the G6 / G6b guardrails baked in.

CLAUDE.md G6 — Redis publish ALWAYS after commit:
    Use `redis_bus.publish_after_commit(...)` from views/services.
    Direct calls inside a transaction body are forbidden — they leak
    ghost events on rollback.

CLAUDE.md G6b — Detection-only outbox (V1):
    Every successful publish also INSERTs a `PublishedEvent` row. A daily
    cron compares undelivered rows against Redis `delivered:<event_id>`
    keys and alerts on mismatches.

The Go side (chat / notif services) consumes these channels via Redis
pub/sub and writes `SET delivered:<event_id> 1 EX 60` on receipt; the
notif worker then marks `PublishedEvent.delivered_at`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any

import redis
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import PublishedEvent

logger = logging.getLogger(__name__)

_client: redis.Redis | None = None


def get_client() -> redis.Redis:
    """Lazy-initialized Redis client. Single connection pool process-wide."""
    global _client
    if _client is None:
        _client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=2,
            health_check_interval=30,
        )
    return _client


def _payload_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def publish_after_commit(
    channel: str,
    payload: dict[str, Any],
    *,
    targets: list[int] | None = None,
) -> str:
    """Schedule a Redis publish + audit-row write to fire on commit.

    `targets` lists user ids the Go notification dispatcher should fan
    out to over WS. If omitted the dispatcher falls back to legacy
    sender_id/traveler_id/recipient_id keys in the payload.

    Returns the `event_id` (UUID4 hex).
    """
    if not channel or not isinstance(channel, str):
        raise ValueError("channel must be a non-empty string")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")

    event_id = uuid.uuid4().hex
    enriched: dict[str, Any] = {
        "event_id": event_id,
        "ts": timezone.now().isoformat(),
        "targets": list(targets) if targets else [],
        **payload,
    }
    serialized = json.dumps(enriched, separators=(",", ":"))
    digest = _payload_hash(enriched)

    def _fire() -> None:
        try:
            PublishedEvent.objects.create(
                channel=channel,
                event_id=event_id,
                payload_hash=digest,
            )
        except Exception:
            logger.exception(
                "redis_bus: failed to record PublishedEvent for %s/%s — skipping publish",
                channel,
                event_id,
            )
            return
        # Persist a per-recipient inbox row for every target user. This is the
        # source of truth the mobile inbox reads on cold start; the live WS
        # fan-out via Go is a same-event mirror, not a replacement. We
        # deliberately swallow errors here so a notification-write failure
        # does NOT stop the live Redis publish below.
        if targets:
            try:
                from apps.notifications.models import (  # noqa: WPS433 (late import)
                    Notification,
                )

                Notification.objects.bulk_create(
                    [
                        Notification(
                            recipient_id=int(uid),
                            channel=channel,
                            event_id=event_id,
                            payload=enriched,
                        )
                        for uid in targets
                    ],
                    ignore_conflicts=True,  # (recipient, event_id) is unique
                )
            except Exception:
                logger.exception(
                    "redis_bus: failed to persist inbox rows for %s/%s",
                    channel,
                    event_id,
                )
        try:
            get_client().publish(channel, serialized)
        except redis.RedisError:
            # The audit row already exists; the daily sweep will surface
            # this as undelivered. Don't re-raise — caller's commit already
            # happened, and a request shouldn't fail because Redis is sick.
            logger.exception(
                "redis_bus: PUBLISH %s failed; PublishedEvent %s will surface in sweep",
                channel,
                event_id,
            )

    transaction.on_commit(_fire)
    return event_id


def mark_delivered(event_id: str) -> bool:
    """Mark a `PublishedEvent` as delivered. Idempotent.

    Called by the Go notif worker (or a Django observer) when it sees the
    downstream `delivered:<event_id>` Redis key. Returns True if a row
    was updated, False if no matching row exists.
    """
    updated = (
        PublishedEvent.objects.filter(event_id=event_id, delivered_at__isnull=True)
        .update(delivered_at=timezone.now())
    )
    return updated > 0
