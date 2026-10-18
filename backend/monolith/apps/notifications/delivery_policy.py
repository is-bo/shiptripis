"""Shared PostgreSQL send gate; its lock number and rate query match Go."""

from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from .models import OutboundMessage

# Held only through a bounded final send/publication transaction. A crashed
# connection releases it automatically; no expiring Redis lock can overlap SMTP.
SEND_LOCK = 877431106


def acquire_send_lock():
    if connection.vendor != "postgresql":
        return True  # SQLite is a single-writer test fallback only.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(%s)", [SEND_LOCK])
        return cursor.fetchone()[0]


def activation_held(message):
    cutoff = getattr(settings, "EMAIL_ACTIVATION_NOT_BEFORE", None)
    return bool(
        not (
            message.activation_reviewed_at
            and message.activation_reviewed_at >= timezone.now() - timedelta(hours=24)
        )
        and (
            (cutoff and message.created_at < cutoff)
            or message.created_at < timezone.now() - timedelta(hours=48)
        )
    )


def rate_limited():
    since = timezone.now() - timedelta(minutes=1)
    return (
        OutboundMessage.objects.filter(
            Q(dispatched_at__gte=since)
            | Q(
                last_error__in=("smtp_transient", "smtp_permanent"),
                updated_at__gte=since,
            )
        ).count()
        >= settings.EMAIL_RATE_LIMIT_PER_MINUTE
    )
