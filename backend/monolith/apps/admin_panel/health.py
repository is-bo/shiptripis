"""Permissioned operational health for on-call staff."""

from __future__ import annotations

import redis
from django.conf import settings
from django.db import connection
from django.db.models import F
from django.utils import timezone
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.finance.models import PaymentProviderEvent, ScheduledJob
from apps.notifications.models import OutboundMessage

from .permissions import CanViewOperationalIncidents


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
        try:
            settings.REDIS_URL  # noqa: B018 - settings access is the check
            client = redis.Redis.from_url(
                settings.REDIS_URL, socket_timeout=1, socket_connect_timeout=1
            )
            client.ping()
            checks["redis"] = "ok"
        except Exception:
            checks["redis"] = "degraded"
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
        checks["providers"] = {
            "stripe_credentials_present": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_WEBHOOK_SECRET),
            "chargily_credentials_present": bool(settings.CHARGILY_SECRET_KEY),
            "email_enabled": bool(settings.TRANSACTIONAL_EMAIL_ENABLED),
        }
        checks["storage"] = {
            "endpoint_configured": bool(settings.S3_ENDPOINT_URL),
            "kyc_bucket_configured": bool(settings.S3_BUCKET_KYC),
            "parcel_bucket_configured": bool(settings.S3_BUCKET_PARCEL),
            "dispute_bucket_configured": bool(settings.S3_BUCKET_DISPUTE),
        }
        response = Response(
            {"status": "ok", "release": settings.RELEASE_ID, "checks": checks}
        )
        response["Cache-Control"] = "no-store"
        return response
