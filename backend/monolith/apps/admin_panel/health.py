"""Permissioned operational health for on-call staff."""

from __future__ import annotations

import time

import redis
from django.conf import settings
from django.db import connection
from django.db.models import F
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.storage import storage_for
from apps.finance.models import PaymentProviderEvent, ScheduledJob
from apps.finance.providers import ChargilyGateway, StripeGateway
from apps.notifications.models import OutboundMessage, PushDevice

from .permissions import CanViewOperationalIncidents

#: Logical storage classes reported to operators, in reading order.
STORAGE_CLASSES_REPORTED = ("parcel", "proof", "dispute", "kyc")

#: How long a storage reachability verdict is reused. Health is polled; the
#: object store is not. Long enough that polling costs nothing, short enough
#: that an operator watching a repair sees it inside a minute.
_STORAGE_PROBE_TTL_SECONDS = 60

_storage_cache: dict[str, object] = {"at": 0.0, "value": None}


def storage_health() -> dict:
    """Per-class object storage readiness, probed with each owning credential.

    Deliberately not a single verdict. The whole failure this replaces was one
    bucket working and being read as all of them working.
    """

    now = time.monotonic()
    cached = _storage_cache["value"]
    if cached is not None and now - float(_storage_cache["at"]) < _STORAGE_PROBE_TTL_SECONDS:
        return cached  # type: ignore[return-value]

    report: dict[str, object] = {
        "endpoint_configured": bool(settings.S3_ENDPOINT_URL),
    }
    classes: dict[str, dict] = {}
    degraded: list[str] = []
    for name in STORAGE_CLASSES_REPORTED:
        store = storage_for(name)
        entry: dict[str, object] = {
            "bucket_configured": bool(store.bucket),
            # The environment prefix supplying the key, never the key.
            "credential": store.credential_source,
            "dedicated_credential": store.uses_dedicated_credential,
        }
        if store.bucket:
            problem = store.probe(read_only=True)
            entry["reachable"] = problem is None
            if problem is not None:
                entry["problem"] = problem
                degraded.append(name)
        else:
            entry["reachable"] = False
            degraded.append(name)
        classes[name] = entry
    report["classes"] = classes
    report["status"] = "ok" if not degraded else "degraded"
    report["degraded"] = degraded
    _storage_cache["at"] = now
    _storage_cache["value"] = report
    return report


class AdminDeepHealthView(APIView):
    permission_classes = (CanViewOperationalIncidents,)

    def get(self, request):
        del request
        checks: dict[str, object] = {}
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "failed"

        client = None
        push_health: dict[str, object] = {
            "enabled": bool(settings.FCM_ENABLED),
            "configuration_complete": bool(
                settings.FCM_PROJECT_ID and settings.FCM_CREDENTIALS_PATH
            ),
            "active_devices": PushDevice.objects.filter(active=True).count(),
        }
        try:
            settings.REDIS_URL  # noqa: B018 - settings access is the check
            client = redis.Redis.from_url(
                settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1
            )
            client.ping()
            checks["redis"] = "ok"
            if not settings.FCM_ENABLED:
                push_health["status"] = "disabled"
                push_health["worker_healthy"] = None
            elif not push_health["configuration_complete"]:
                push_health["status"] = "configuration_incomplete"
                push_health["worker_healthy"] = False
            else:
                worker_healthy = bool(client.exists("fcm:worker:active"))
                push_health["worker_healthy"] = worker_healthy
                push_health["status"] = "ready" if worker_healthy else "degraded"
                push_health["stream_length"] = int(client.xlen(settings.FCM_STREAM))
                try:
                    group = next(
                        (
                            row
                            for row in client.xinfo_groups(settings.FCM_STREAM)
                            if row.get("name") == settings.FCM_CONSUMER_GROUP
                        ),
                        None,
                    )
                    push_health["stream_pending"] = (
                        int(group.get("pending", 0)) if group else None
                    )
                    push_health["stream_lag"] = (
                        int(group["lag"])
                        if group and group.get("lag") is not None
                        else None
                    )
                except redis.RedisError:
                    push_health["stream_pending"] = None
                    push_health["stream_lag"] = None
        except Exception:
            checks["redis"] = "degraded"
            push_health["status"] = (
                "disabled" if not settings.FCM_ENABLED else "degraded"
            )
            push_health["worker_healthy"] = None
        finally:
            if client is not None:
                client.close()

        now = timezone.now()
        jobs = ScheduledJob.objects.all()
        pending = jobs.filter(status=ScheduledJob.Status.PENDING)
        failed = jobs.filter(status=ScheduledJob.Status.FAILED)
        checks["scheduled_jobs"] = {
            "pending": pending.count(),
            "retrying": pending.filter(attempts__gt=0).count(),
            "running": jobs.filter(status=ScheduledJob.Status.RUNNING).count(),
            "failed": failed.count(),
            "manual_action": failed.filter(attempts__gte=F("max_attempts")).count(),
            "oldest_pending_age_seconds": (
                max(0, int((now - oldest).total_seconds()))
                if (oldest := pending.order_by("run_at").values_list("run_at", flat=True).first())
                else None
            ),
        }
        checks["provider_events"] = {
            "retryable": PaymentProviderEvent.objects.filter(
                processing_result=PaymentProviderEvent.ProcessingResult.RETRYABLE
            ).count(),
            "failed": PaymentProviderEvent.objects.filter(
                processing_result=PaymentProviderEvent.ProcessingResult.FAILED
            ).count(),
        }
        checks["outbound_messages"] = {
            "pending": OutboundMessage.objects.filter(
                status=OutboundMessage.Status.PENDING
            ).count(),
            "failed": OutboundMessage.objects.filter(
                status=OutboundMessage.Status.FAILED
            ).count(),
        }
        checks["push"] = push_health
        # Credential *shape*, never a credential. `credential_mode` says which
        # rail a key points at ("test" / "live" / "unknown"), so a pre-launch
        # operator can confirm that nothing is armed against real money without
        # anyone reading, echoing or logging a secret to find out.
        checks["providers"] = {
            "stripe_credentials_present": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET),
            "stripe_mode": StripeGateway().credential_mode(),
            "chargily_credentials_present": bool(settings.CHARGILY_SECRET_KEY),
            "chargily_mode": ChargilyGateway().credential_mode(),
            "email_enabled": bool(settings.TRANSACTIONAL_EMAIL_ENABLED),
        }
        # Storage is reported per *logical class with its own credential*, not
        # per bucket name. A configured name says nothing about access, and the
        # KYC bucket is owned by a different key from everything else Django
        # writes — so "the media bucket answered" must never be allowed to read
        # as "KYC evidence is servable". Reachability is a real HEAD, cached so
        # a health poll cannot turn into a request amplifier.
        checks["storage"] = storage_health()
        response = Response(
            {"status": "ok", "release": settings.RELEASE_ID, "checks": checks}
        )
        response["Cache-Control"] = "no-store"
        return response
