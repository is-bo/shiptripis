"""Retryable delivery of committed inbox events using the existing DB worker."""
import json
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)


def dispatch_event(payload):
    from apps.core.redis_bus import get_client, _payload_hash
    from apps.core.models import PublishedEvent
    from .models import Notification
    from .push import enqueue_fcm_for_event

    event_id = payload["event_id"]
    row = Notification.objects.filter(event_id=event_id).order_by("pk").first()
    if row is None:
        return "event_missing"
    envelope = row.payload
    PublishedEvent.objects.get_or_create(event_id=event_id, defaults={
        "channel": row.channel, "payload_hash": _payload_hash(envelope),
    })
    targets = list(Notification.objects.filter(event_id=event_id).values_list("recipient_id", flat=True))
    failed = False
    try:
        enqueue_fcm_for_event(channel=row.channel, event_id=event_id, payload=envelope, targets=targets)
    except Exception:
        failed = True
    try:
        get_client().publish(row.channel, json.dumps(envelope, separators=(",", ":")))
    except Exception:
        failed = True
    if failed:
        raise RuntimeError("notification_transport_unavailable")
    return "notification_dispatched"


def dispatch_promptly(event_id):
    from apps.finance.models import ScheduledJob
    try:
        dispatch_event({"event_id": event_id})
    except Exception:
        # Do not log transport exception strings: token/provider material may
        # be embedded. The durable obligation will retry independently.
        logger.warning("Notification transport deferred: %s", event_id)
        return
    ScheduledJob.objects.filter(key=f"notification:{event_id}", status="pending").update(
        status="succeeded", completed_at=timezone.now(), last_result="notification_dispatched",
    )
