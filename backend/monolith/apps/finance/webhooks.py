"""Provider webhook endpoints.

These are the only unauthenticated write surfaces in the financial system, so
the rules are tight:

* **The raw body is what gets verified.** `request.body` is read before DRF
  parses anything, because both Stripe and Chargily sign the exact bytes they
  sent. Re-serialising a parsed dict would change whitespace and key order and
  break every signature.
* **A bad signature is a 400 and nothing else.** No row is written, no state
  moves, and the response says nothing about whether the referenced payment
  exists.
* **A verified event is idempotent and recoverable.** `apply_provider_event`
  inserts the provider event id first; a duplicate cannot create a second
  economic identity, but it re-drives any event that has not reached applied
  or intentionally ignored.
* **Availability does not gate events.** A provider disabled for new checkouts
  still has customers mid-flight and refunds in progress. Turning off new
  Chargily checkouts must not strand money that already exists, so these views
  never consult business availability.
* **Return 2xx once the event is durably recorded.** A 500 makes the provider
  retry, which is safe but noisy; a silent 200 on an unrecorded event would
  lose it. Recording happens before any answer.
"""

from __future__ import annotations

import logging

from rest_framework import status as http
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import PaymentProvider
from .providers import ProviderNotConfigured, ProviderSignatureError, get_gateway
from .services import apply_provider_event

logger = logging.getLogger(__name__)


class WebhookThrottle(AnonRateThrottle):
    scope = "payment_webhook"


class _ProviderWebhookView(APIView):
    """Shared verification and dispatch for one provider's webhook."""

    provider: str = ""
    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (WebhookThrottle,)

    def post(self, request: Request) -> Response:
        # Read the raw bytes before touching request.data: the signature covers
        # exactly these bytes, and DRF's parsers would otherwise consume the
        # stream and hand back a re-encodable dict.
        raw_body = request.body
        headers = {
            key.lower(): value for key, value in request.headers.items()
        }
        try:
            gateway = get_gateway(self.provider)
            event = gateway.parse_webhook(raw_body=raw_body, headers=headers)
        except ProviderNotConfigured:
            # The rail is not set up here. Do not confirm receipt, so the
            # provider retries once configuration lands.
            logger.error("finance.webhook_provider_unconfigured provider=%s", self.provider)
            return Response(
                {"code": "provider_not_configured"},
                status=http.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ProviderSignatureError as exc:
            # Never echo why. An attacker learns nothing from a rejected probe.
            logger.warning(
                "finance.webhook_signature_rejected provider=%s reason=%s",
                self.provider,
                exc.code,
            )
            return Response(
                {"code": "invalid_webhook_signature"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        try:
            outcome = apply_provider_event(event)
        except Exception:  # noqa: BLE001 - a 500 asks the provider to retry
            logger.exception(
                "finance.webhook_processing_failed provider=%s type=%s",
                self.provider,
                event.event_type,
            )
            return Response(
                {"code": "webhook_processing_failed"},
                status=http.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        logger.info(
            "finance.webhook_processed provider=%s type=%s duplicate=%s note=%s",
            self.provider,
            event.event_type,
            outcome.duplicate,
            outcome.note,
        )
        return Response(
            {"received": True, "duplicate": outcome.duplicate},
            status=http.HTTP_200_OK,
        )


class StripeWebhookView(_ProviderWebhookView):
    provider = PaymentProvider.STRIPE


class ChargilyWebhookView(_ProviderWebhookView):
    provider = PaymentProvider.CHARGILY


class MockWebhookView(_ProviderWebhookView):
    """Test/local rail only.

    The URL is registered unconditionally, but `get_gateway("mock")` raises
    `ProviderNotConfigured` unless the deployment explicitly opted in, so in
    production this route answers 503 and can never move money.
    """

    provider = PaymentProvider.MOCK
