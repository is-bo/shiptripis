"""Shared PostgreSQL send gate; its lock number and rate query match Go.

Also the one rule for whether the selected email provider is configured,
which the staff console and the provider-health API both report.
"""

from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from .models import OutboundMessage

# Held only through a bounded final send/publication transaction. A crashed
# connection releases it automatically; no expiring Redis lock can overlap a send.
SEND_LOCK = 877431106

#: `last_error` values a provider refusal writes (Django and Go alike). Each one
#: spends the shared minute budget, exactly like an accepted send.
PROVIDER_TRANSIENT = "provider_transient"
PROVIDER_PERMANENT = "provider_permanent"
PROVIDER_FAILURES = (PROVIDER_TRANSIENT, PROVIDER_PERMANENT)


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
                last_error__in=PROVIDER_FAILURES,
                updated_at__gte=since,
            )
        ).count()
        >= settings.EMAIL_RATE_LIMIT_PER_MINUTE
    )


def email_transport_configured() -> bool:
    """Whether the selected provider has what it needs to send.

    Sender.net's API needs its token; SMTP needs a relay host (authentication
    is optional, as for a local MailHog). The From address always has a value:
    `EMAIL_FROM_ADDR` defaults to contact@wassla.eu.
    """

    if getattr(settings, "TRANSACTIONAL_EMAIL_PROVIDER", "smtp") == "sender_net":
        return bool(getattr(settings, "SENDER_NET_API_TOKEN", ""))
    return bool(getattr(settings, "EMAIL_HOST", ""))
