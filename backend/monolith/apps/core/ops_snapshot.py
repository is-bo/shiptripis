"""Aggregate operational numbers for alerting without an APM vendor.

Two readers share these helpers: the permissioned deep-health endpoint, and
the finance worker, which logs one `ops_snapshot` line every few minutes. The
log line matters because Railway collects the log stream by default and can
search/filter structured fields, while nothing scrapes an internal endpoint.

Everything here is a count, an age in seconds, or a byte size. No identifiers,
addresses, payloads or SQL leave this module.
"""

from __future__ import annotations

import logging
from datetime import timedelta
import time
from pathlib import Path

import redis
from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger("shiptrip.ops")

#: cgroup v2 files Railway containers expose; absent elsewhere (and on
#: developer machines), in which case memory is simply omitted.
_CGROUP_MEMORY_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_MEMORY_MAX = Path("/sys/fs/cgroup/memory.max")


def _text(value):
    """Callers' clients may or may not decode replies; accept both."""

    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _age_seconds_from_stream_id(entry_id) -> int | None:
    """Redis stream IDs start with their creation time in milliseconds."""

    entry_id = _text(entry_id)
    if not isinstance(entry_id, str) or "-" not in entry_id:
        return None
    try:
        created_ms = int(entry_id.split("-", 1)[0])
    except ValueError:
        return None
    return max(0, int(time.time() - created_ms / 1000))


def stream_backlog(client, stream: str, group: str) -> dict:
    """Length, pending, lag and oldest-pending age for one consumer group.

    `oldest_pending_age_seconds` is the alertable number: an entry a worker
    read but never acknowledged. It grows when a worker is wedged or a send
    keeps failing, which `pending` alone cannot distinguish from a burst.
    """

    report: dict[str, int | None] = {
        "length": None,
        "pending": None,
        "lag": None,
        "oldest_pending_age_seconds": None,
    }
    try:
        report["length"] = int(client.xlen(stream))
        summary = client.xpending(stream, group) or {}
        report["pending"] = int(summary.get("pending") or 0)
        report["oldest_pending_age_seconds"] = (
            _age_seconds_from_stream_id(summary.get("min"))
            if report["pending"]
            else None
        )
        for row in client.xinfo_groups(stream):
            if _text(row.get("name")) == group:
                lag = row.get("lag")
                report["lag"] = int(lag) if lag is not None else None
    except (redis.RedisError, TypeError, ValueError, AttributeError):
        # A missing stream/group (nothing ever enqueued) or a Redis outage is
        # reported as unknown rather than as zero; `/readyz` owns the outage.
        pass
    return report


def _database_connections() -> dict:
    if connection.vendor != "postgresql":
        return {}
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT count(*), current_setting('max_connections')::int "
            "FROM pg_stat_activity WHERE backend_type = 'client backend'"
        )
        used, limit = cursor.fetchone()
    return {"connections": int(used), "max_connections": int(limit)}


def _memory() -> dict:
    try:
        current = int(_CGROUP_MEMORY_CURRENT.read_text().strip())
        raw_max = _CGROUP_MEMORY_MAX.read_text().strip()
    except (OSError, ValueError):
        return {}
    report = {"container_memory_bytes": current}
    if raw_max.isdigit():
        report["container_memory_limit_bytes"] = int(raw_max)
    return report


def build_ops_snapshot() -> dict:
    """One flat-ish dict of backlog, saturation and headroom numbers."""

    from apps.finance.models import ScheduledJob
    from apps.notifications.models import OutboundMessage

    now = timezone.now()
    overdue_jobs = ScheduledJob.objects.filter(
        status=ScheduledJob.Status.PENDING, run_at__lte=now
    )
    oldest_job = overdue_jobs.order_by("run_at").values_list("run_at", flat=True).first()
    overdue_messages = OutboundMessage.objects.filter(
        status=OutboundMessage.Status.PENDING, next_attempt_at__lte=now
    )
    earliest = max(settings.EMAIL_ACTIVATION_NOT_BEFORE or now-timedelta(hours=48), now-timedelta(hours=48))
    eligible = Q(created_at__gte=earliest) | Q(activation_reviewed_at__gte=now-timedelta(hours=24))
    overdue_messages = overdue_messages.filter(eligible)
    oldest_message = (
        overdue_messages.order_by("next_attempt_at")
        .values_list("next_attempt_at", flat=True)
        .first()
    )
    snapshot: dict[str, object] = {
        "jobs_overdue": overdue_jobs.count(),
        "jobs_oldest_overdue_seconds": (
            int((now - oldest_job).total_seconds()) if oldest_job else None
        ),
        "jobs_running": ScheduledJob.objects.filter(
            status=ScheduledJob.Status.RUNNING
        ).count(),
        "jobs_failed_unresolved": ScheduledJob.objects.filter(
            status=ScheduledJob.Status.FAILED, resolution=""
        ).count(),
        "outbound_overdue": overdue_messages.count(),
        "outbound_oldest_overdue_seconds": (
            int((now - oldest_message).total_seconds()) if oldest_message else None
        ),
        "outbound_failed": OutboundMessage.objects.filter(
            status=OutboundMessage.Status.FAILED
        ).count(),
        "email_enabled": settings.TRANSACTIONAL_EMAIL_ENABLED,
        "outbound_retrying": OutboundMessage.objects.filter(status="pending", attempts__gt=0).count(),
        "outbound_activation_held": OutboundMessage.objects.filter(status="pending").exclude(eligible).count(),
    }
    snapshot.update(_database_connections())
    snapshot.update(_memory())

    client = None
    try:
        client = redis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=1,
            socket_connect_timeout=1,
        )
        for prefix, stream, group in (
            ("fcm", settings.FCM_STREAM, settings.FCM_CONSUMER_GROUP),
            ("email", settings.EMAIL_STREAM, settings.EMAIL_CONSUMER_GROUP),
        ):
            for key, value in stream_backlog(client, stream, group).items():
                snapshot[f"{prefix}_stream_{key}"] = value
    except (redis.RedisError, ValueError):
        snapshot["redis"] = "unavailable"
    finally:
        if client is not None:
            client.close()
    return snapshot


def log_ops_snapshot() -> dict:
    snapshot = build_ops_snapshot()
    logger.info("ops snapshot", extra={"event": "ops_snapshot", "ops": snapshot})
    return snapshot
