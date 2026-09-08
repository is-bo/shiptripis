"""The connected-accounts webhook endpoint.

`POST /api/payments/webhooks/stripe-connect` is a second, separate ingress from
the existing platform endpoint, with its own signing secret. The separation is
the point:

* one secret per endpoint, so a compromise or rotation of either does not
  widen into the other;
* one scope per endpoint, so a connected-account event can never be applied by
  the payment reconciler and a Checkout event can never be applied by the
  account refresher;
* one event allowlist per endpoint, so an unrequested event type is recorded
  and classified rather than silently interpreted.

The event itself is only ever treated as *something changed*. Nothing here
believes a payload: readiness is always re-derived from a fresh authoritative
`GET /v1/accounts/{acct}`, and the write is guarded so a slow old fetch cannot
regress a newer one. Nothing here moves money, and no handler in this module
can: the Connect adapter has no transfer or payout call to reach.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .models import PaymentProvider, PaymentProviderEvent, StripePayoutAccount
from .payout_accounts import expected_mode, refresh_account
from .providers.base import ProviderNotConfigured, ProviderSignatureError
from .providers.stripe import (
    DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
    MAX_WEBHOOK_BYTES,
    verify_stripe_signature,
)
from .providers.stripe_connect import get_connect_gateway

logger = logging.getLogger(__name__)

ENDPOINT_SCOPE = "connect"

#: Exactly the H2 onboarding/readiness subset. Anything outside it is stored
#: and classified, never acted on. There is no wildcard subscription, and
#: adding an event here is a deliberate change with a handler behind it.
READINESS_EVENTS = frozenset(
    {
        "account.updated",
        "capability.updated",
        "account.external_account.created",
        "account.external_account.updated",
        "account.external_account.deleted",
    }
)

#: Event types H3 will own. Accepting them now means an operator can register
#: the full destination once; ingesting them here records provenance and moves
#: no money, because this module has no execution path at all.
DEFERRED_EVENTS = frozenset(
    {
        "payout.created",
        "payout.updated",
        "payout.paid",
        "payout.failed",
        "payout.canceled",
        "account.application.deauthorized",
    }
)


class ConnectWebhookThrottle(AnonRateThrottle):
    scope = "payment_webhook"


def _safe_payload(event: dict) -> dict:
    """Keep provenance, drop everything a bank or a person is in.

    `account.external_account.*` carries a full bank-account object: holder
    name, last four, routing details, fingerprint. None of it is stored. What
    survives is the event envelope plus a handful of ids and enum-shaped
    fields, which is everything reconciliation needs.
    """

    obj = event.get("data") or {}
    obj = obj.get("object") if isinstance(obj, dict) else {}
    obj = obj if isinstance(obj, dict) else {}
    safe_object = {
        "object": str(obj.get("object") or ""),
        "id": str(obj.get("id") or ""),
    }
    for key in ("status", "currency", "default_for_currency", "payouts_enabled"):
        if key in obj and isinstance(obj[key], (str, bool)):
            safe_object[key] = obj[key]
    return {
        "id": str(event.get("id") or ""),
        "type": str(event.get("type") or ""),
        "account": str(event.get("account") or ""),
        "livemode": event.get("livemode"),
        "created": event.get("created"),
        "api_version": str(event.get("api_version") or ""),
        "data": {"object": safe_object},
    }


def _parse(raw_body: bytes, headers: dict) -> dict:
    secret = str(getattr(settings, "STRIPE_CONNECT_WEBHOOK_SECRET", "") or "")
    if not secret:
        raise ProviderNotConfigured("STRIPE_CONNECT_WEBHOOK_SECRET is not configured.")
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise ProviderSignatureError("Webhook body exceeds the accepted size.")
    verify_stripe_signature(
        raw_body=raw_body,
        signature_header=headers.get("stripe-signature", ""),
        secret=secret,
        tolerance_seconds=int(
            getattr(
                settings,
                "STRIPE_WEBHOOK_TOLERANCE_SECONDS",
                DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
            )
        ),
    )
    try:
        event = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ProviderSignatureError("Connect webhook body is not valid JSON.") from exc
    if not isinstance(event, dict) or not str(event.get("id") or ""):
        raise ProviderSignatureError("Connect webhook carries no event id.")
    return event


def _classification(event: dict) -> tuple:
    """Decide what this endpoint is allowed to do with one verified event."""

    account_id = str(event.get("account") or "")
    event_type = str(event.get("type") or "")
    if not account_id:
        # A platform-scoped event on the connected-accounts endpoint. Somebody's
        # subscription is wrong; record it so that is visible, and do nothing.
        return "ignored", "platform_scope_event"
    livemode = event.get("livemode")
    mode = (
        ("live" if livemode else "test") if type(livemode) is bool else "legacy_unknown"
    )
    if mode != expected_mode():
        # Production Connect endpoints legitimately receive test events. They
        # are durably classified, never applied to another mode's obligation,
        # and never rejected into an infinite provider retry.
        return "ignored", "mode_isolated"
    if event_type in READINESS_EVENTS:
        return "refresh", ""
    if event_type in DEFERRED_EVENTS:
        return "ignored", "deferred_to_execution_phase"
    return "ignored", "event_not_subscribed"


def record_connect_event(event: dict, *, endpoint_scope: str = ENDPOINT_SCOPE):
    """Insert the event durably before answering the provider.

    Uniqueness on `(provider, provider_event_id)` is what makes a redelivery a
    no-op rather than a second economic identity. A replayed id carrying a
    different safe payload is a contradiction and is failed rather than applied.
    """

    payload = _safe_payload(event)
    fingerprint = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    obj = payload["data"]["object"]
    livemode = event.get("livemode")
    mode = (
        ("live" if livemode else "test") if type(livemode) is bool else "legacy_unknown"
    )
    duplicate = False
    try:
        with transaction.atomic():
            record = PaymentProviderEvent.objects.create(
                provider=PaymentProvider.STRIPE,
                provider_event_id=payload["id"],
                provider_mode=mode,
                provider_account_id=payload["account"][:255],
                endpoint_scope=endpoint_scope,
                api_version=payload["api_version"][:64],
                event_type=payload["type"][:128],
                object_type=obj["object"][:64],
                object_id=obj["id"][:255],
                signature_verified=True,
                payload=payload,
                payload_fingerprint=fingerprint,
                normalized_event={
                    "scope": endpoint_scope,
                    "account": payload["account"],
                    "object_id": obj["id"],
                    "object_type": obj["object"],
                },
            )
    except IntegrityError:
        duplicate = True
        record = PaymentProviderEvent.objects.get(
            provider=PaymentProvider.STRIPE, provider_event_id=payload["id"]
        )
    matches = (
        not record.payload_fingerprint or record.payload_fingerprint == fingerprint
    )
    return record, duplicate, matches


def record_out_of_scope_event(event) -> None:
    """Durably classify a connected-account event that hit the platform endpoint.

    Takes a parsed `ProviderEvent`; its `payload` is the already-scrubbed
    Stripe envelope. Stored under `endpoint_scope="platform"` and marked
    ignored, so the wrong subscription is visible in the event log without the
    payment reconciler ever being handed a connected account's object.
    """

    record, _, matches = record_connect_event(
        dict(event.payload or {}), endpoint_scope="platform"
    )
    if matches and record.processing_result not in (
        PaymentProviderEvent.ProcessingResult.APPLIED,
        PaymentProviderEvent.ProcessingResult.IGNORED,
    ):
        _finish(
            record,
            result=PaymentProviderEvent.ProcessingResult.IGNORED,
            note="connected_account_scope",
        )


def _finish(record, *, result, note):
    PaymentProviderEvent.objects.filter(pk=record.pk).update(
        processing_result=result,
        processing_note=note[:255],
        processing_attempts=record.processing_attempts + 1,
        processed_at=timezone.now(),
    )


def process_connect_event(event: dict, record) -> str:
    """Re-read the named account from Stripe and re-evaluate readiness.

    The event's own body is never the source of truth for readiness. An
    `account.external_account.deleted` payload says a bank went away; only the
    fresh account object says whether an eligible EUR destination still exists.
    """

    action, note = _classification(event)
    if action != "refresh":
        _finish(record, result=PaymentProviderEvent.ProcessingResult.IGNORED, note=note)
        return note

    account_id = str(event.get("account") or "")
    account = StripePayoutAccount.objects.filter(
        provider_account_id=account_id,
        provider_mode=expected_mode(),
        platform_id=str(
            getattr(settings, "STRIPE_CONNECT_PLATFORM_ACCOUNT_ID", "") or ""
        ),
    ).first()
    if not account:
        # An account this platform does not track. Safely classified, never
        # created from an event: nothing outside this server may introduce a
        # connected account into the payout domain.
        _finish(
            record,
            result=PaymentProviderEvent.ProcessingResult.IGNORED,
            note="unknown_connected_account",
        )
        return "unknown_connected_account"

    try:
        _, applied = refresh_account(account, gateway=get_connect_gateway())
    except ValidationError as exc:
        _finish(
            record,
            result=PaymentProviderEvent.ProcessingResult.IGNORED,
            note=f"refusal:{getattr(exc, 'code', '') or 'invalid'}",
        )
        return "refresh_refused"
    note = "readiness_refreshed" if applied else "superseded_by_newer_observation"
    _finish(record, result=PaymentProviderEvent.ProcessingResult.APPLIED, note=note)
    return note


class StripeConnectWebhookView(APIView):
    """Connected-accounts ingress. Separate secret, separate scope, no money."""

    permission_classes = (AllowAny,)
    authentication_classes = ()
    throttle_classes = (ConnectWebhookThrottle,)

    def post(self, request: Request) -> Response:
        # Raw bytes before DRF parses anything: the signature covers exactly
        # these bytes, and a re-encoded dict is a different message.
        raw_body = request.body
        headers = {key.lower(): value for key, value in request.headers.items()}
        try:
            event = _parse(raw_body, headers)
        except ProviderNotConfigured:
            logger.error("finance.connect_webhook_unconfigured")
            return Response(
                {"code": "provider_not_configured"},
                status=http.HTTP_503_SERVICE_UNAVAILABLE,
            )
        except ProviderSignatureError as exc:
            logger.warning("finance.connect_webhook_rejected reason=%s", exc.code)
            return Response(
                {"code": "invalid_webhook_signature"},
                status=http.HTTP_400_BAD_REQUEST,
            )

        record, duplicate, matches = record_connect_event(event)
        if not matches:
            PaymentProviderEvent.objects.filter(pk=record.pk).exclude(
                processing_result__in=(
                    PaymentProviderEvent.ProcessingResult.APPLIED,
                    PaymentProviderEvent.ProcessingResult.IGNORED,
                )
            ).update(
                processing_result=PaymentProviderEvent.ProcessingResult.FAILED,
                last_error_code="event_id_payload_mismatch",
                processed_at=timezone.now(),
            )
            return Response(
                {"received": True, "duplicate": True}, status=http.HTTP_200_OK
            )
        if record.processing_result in (
            PaymentProviderEvent.ProcessingResult.APPLIED,
            PaymentProviderEvent.ProcessingResult.IGNORED,
        ):
            return Response(
                {"received": True, "duplicate": True}, status=http.HTTP_200_OK
            )
        if record.endpoint_scope != ENDPOINT_SCOPE:
            # The same event id already arrived on the platform endpoint. Its
            # scope decision stands; do not re-classify it from here.
            return Response(
                {"received": True, "duplicate": True}, status=http.HTTP_200_OK
            )

        try:
            note = process_connect_event(event, record)
        except Exception:  # noqa: BLE001 - a 500 asks Stripe to redeliver
            logger.exception(
                "finance.connect_webhook_failed type=%s", record.event_type
            )
            PaymentProviderEvent.objects.filter(pk=record.pk).update(
                processing_result=PaymentProviderEvent.ProcessingResult.RETRYABLE,
                processing_attempts=record.processing_attempts + 1,
                last_error_code="connect_event_failed",
            )
            return Response(
                {"code": "webhook_processing_failed"},
                status=http.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        logger.info(
            "finance.connect_webhook_processed type=%s note=%s duplicate=%s",
            record.event_type,
            note,
            duplicate,
        )
        return Response(
            {"received": True, "duplicate": duplicate}, status=http.HTTP_200_OK
        )
