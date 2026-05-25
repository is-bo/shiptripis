"""Payments API.

V1 endpoints:
  GET  /api/payments/intents                       — list mine (?status=)
  POST /api/payments/intents                       — create + auto-confirm (mock provider)
  GET  /api/payments/intents/<id>                  — detail (payer-only)
  POST /api/payments/intents/<id>/cancel           — cancel while not yet succeeded
  POST /api/payments/intents/<id>/refund           — refund (full or partial) by amount
  POST /api/payments/webhook/mock                  — synthetic webhook (dev/QA tool)

The mock provider returns success instantly, so the typical flow is:

  POST /intents  →  PaymentIntent.status = succeeded
                  PaymentEvent (intent_created + intent_succeeded)
                  publishes `payment.captured`

Real Stripe/Edahabia plug in by:
  - swapping `providers.get_provider` / `providers.choose_provider`
  - replacing `_synthesize_succeeded` with webhook-driven status updates
"""

from __future__ import annotations

import secrets

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import channels, redis_bus
from apps.matching.models import Match, Offer
from apps.verification.models import HandoverCode
from apps.verification.services import issue_code

from .models import PaymentEvent, PaymentIntent, Refund
from .providers import choose_provider, get_provider
from .serializers import (
    CreateIntentSerializer,
    PaymentIntentSerializer,
    RefundSerializer,
)


# ---------- helpers ----------


def _refetch(pk: int) -> PaymentIntent:
    return PaymentIntent.objects.select_related("offer", "offer__match", "payer").get(
        pk=pk
    )


def _synthesize_succeeded(intent: PaymentIntent, provider_intent_id: str) -> None:
    """Apply the 'mock succeeded' state transition in one atomic block.

    Real providers will instead transition via webhook. This helper exists
    so the mock-create flow and the dev webhook endpoint share one path.
    """
    now = timezone.now()
    intent.provider_intent_id = provider_intent_id
    intent.status = PaymentIntent.Status.SUCCEEDED
    intent.succeeded_at = now
    intent.save(
        update_fields=[
            "provider_intent_id",
            "status",
            "succeeded_at",
            "updated_at",
        ]
    )
    PaymentEvent.objects.create(
        intent=intent,
        provider=intent.provider,
        provider_event_id=f"evt_succeeded_{provider_intent_id}_{secrets.token_hex(4)}",
        kind=PaymentEvent.Kind.INTENT_SUCCEEDED,
        payload={"amount_minor": intent.amount_minor, "currency": intent.currency},
    )
    match = intent.offer.match
    redis_bus.publish_after_commit(
        channels.PAYMENT_CAPTURED,
        {
            "intent_id": intent.id,
            "offer_id": intent.offer_id,
            "match_id": match.id,
            "payer_id": intent.payer_id,
            "amount_minor": intent.amount_minor,
            "currency": intent.currency,
        },
        targets=[match.sender_id, match.traveler_id],
    )

    # Auto-issue PICKUP code so the sender lands on a "your code is X" screen
    # without a second round-trip. The mobile traveler home shows a "paid match
    # awaiting pickup" entry once it sees the corresponding `handover.code_issued`
    # WS event. Skipped if there's already an ACTIVE pickup code (idempotent
    # against double-capture). Same atomic block as the payment transition so
    # a failure here rolls the capture back too.
    has_active = HandoverCode.objects.filter(
        match=match,
        kind=HandoverCode.Kind.PICKUP,
        status=HandoverCode.Status.ACTIVE,
    ).exists()
    if not has_active:
        issue_code(match=match, kind=HandoverCode.Kind.PICKUP, issued_to=match.sender)


# ---------- views ----------


class PaymentIntentListView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = PaymentIntent.objects.filter(payer=request.user).select_related(
            "offer", "offer__match"
        )
        if (s := request.query_params.get("status")):
            qs = qs.filter(status=s)
        return Response(PaymentIntentSerializer(qs, many=True).data)


class PaymentIntentCreateView(APIView):
    """POST /api/payments/intents.

    Creates a PaymentIntent for the given accepted Offer. In V1 the mock
    provider returns success instantly, so the response already contains
    `status == "succeeded"`. The mobile UI will still play the
    Stripe/Edahabia-style "processing" animation before showing success.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        s = CreateIntentSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data

        offer = get_object_or_404(
            Offer.objects.select_related("match"), pk=d["offer_id"]
        )
        match: Match = offer.match

        if match.sender_id != request.user.id:
            return Response(
                {"detail": "Only the sender pays."},
                status=http.HTTP_403_FORBIDDEN,
            )
        if offer.status != Offer.Status.ACCEPTED:
            return Response(
                {"detail": f"Offer is not accepted (status={offer.status})."},
                status=http.HTTP_409_CONFLICT,
            )

        # If an existing SUCCEEDED intent is on this offer, return it.
        existing = PaymentIntent.objects.filter(offer=offer).first()
        if existing is not None and existing.status == PaymentIntent.Status.SUCCEEDED:
            return Response(
                PaymentIntentSerializer(existing).data, status=http.HTTP_200_OK
            )

        idem = d.get("idempotency_key", "")
        if idem:
            prior = PaymentIntent.objects.filter(
                payer=request.user, client_idempotency_key=idem
            ).first()
            if prior is not None:
                return Response(
                    PaymentIntentSerializer(prior).data, status=http.HTTP_200_OK
                )

        provider = choose_provider(d["currency"])

        try:
            with transaction.atomic():
                intent = PaymentIntent.objects.create(
                    offer=offer,
                    payer=request.user,
                    provider=provider.name,
                    amount_minor=offer.total_dzd,
                    currency=d["currency"],
                    status=PaymentIntent.Status.PROCESSING,
                    client_idempotency_key=idem,
                )
                PaymentEvent.objects.create(
                    intent=intent,
                    provider=provider.name,
                    provider_event_id=f"evt_created_local_{intent.id}",
                    kind=PaymentEvent.Kind.INTENT_CREATED,
                    payload={"amount_minor": intent.amount_minor, "currency": intent.currency},
                )

                result = provider.create_intent(
                    amount_minor=intent.amount_minor,
                    currency=intent.currency,
                    payer_user_id=request.user.id,
                    idempotency_key=idem or f"local-{intent.id}",
                )

                if result.status == "succeeded":
                    _synthesize_succeeded(intent, result.provider_intent_id)
                else:
                    intent.provider_intent_id = result.provider_intent_id
                    intent.save(update_fields=["provider_intent_id", "updated_at"])
        except IntegrityError:
            # Race: another request created the open intent or hit the
            # client-key uniqueness. Return the row that won.
            existing = PaymentIntent.objects.filter(offer=offer).first()
            if existing is not None:
                return Response(
                    PaymentIntentSerializer(existing).data, status=http.HTTP_200_OK
                )
            return Response(
                {"detail": "Conflict creating payment intent."},
                status=http.HTTP_409_CONFLICT,
            )

        return Response(
            PaymentIntentSerializer(_refetch(intent.pk)).data,
            status=http.HTTP_201_CREATED,
        )


class PaymentIntentDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        intent = get_object_or_404(
            PaymentIntent.objects.select_related("offer", "offer__match"), pk=pk
        )
        if intent.payer_id != request.user.id:
            return Response({"detail": "Forbidden."}, status=http.HTTP_403_FORBIDDEN)
        return Response(PaymentIntentSerializer(intent).data)


class PaymentIntentCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        intent = get_object_or_404(PaymentIntent, pk=pk)
        if intent.payer_id != request.user.id:
            return Response({"detail": "Forbidden."}, status=http.HTTP_403_FORBIDDEN)
        if intent.status not in {
            PaymentIntent.Status.REQUIRES_PAYMENT_METHOD,
            PaymentIntent.Status.PROCESSING,
        }:
            return Response(
                {"detail": f"Cannot cancel intent in status '{intent.status}'."},
                status=http.HTTP_409_CONFLICT,
            )

        with transaction.atomic():
            intent.status = PaymentIntent.Status.CANCELLED
            intent.save(update_fields=["status", "updated_at"])
            PaymentEvent.objects.create(
                intent=intent,
                provider=intent.provider,
                provider_event_id=f"evt_cancelled_local_{intent.id}",
                kind=PaymentEvent.Kind.INTENT_CANCELLED,
                payload={},
            )

        return Response(PaymentIntentSerializer(_refetch(intent.pk)).data)


class PaymentIntentRefundView(APIView):
    """Refund a succeeded intent (full or partial)."""

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        intent = get_object_or_404(PaymentIntent, pk=pk)
        if intent.payer_id != request.user.id:
            return Response({"detail": "Forbidden."}, status=http.HTTP_403_FORBIDDEN)
        if intent.status not in {
            PaymentIntent.Status.SUCCEEDED,
            PaymentIntent.Status.REFUND_PENDING,
        }:
            return Response(
                {"detail": f"Cannot refund intent in status '{intent.status}'."},
                status=http.HTTP_409_CONFLICT,
            )

        try:
            amount = int(request.data.get("amount_minor", intent.amount_minor))
        except (TypeError, ValueError):
            return Response(
                {"detail": "amount_minor must be int."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        if amount <= 0:
            return Response(
                {"detail": "amount_minor must be > 0."},
                status=http.HTTP_400_BAD_REQUEST,
            )

        refunded_so_far = sum(
            r.amount_minor for r in intent.refunds.filter(status=Refund.Status.SUCCEEDED)
        )
        if refunded_so_far + amount > intent.amount_minor:
            return Response(
                {
                    "detail": "Refund exceeds captured amount.",
                    "captured_minor": intent.amount_minor,
                    "already_refunded_minor": refunded_so_far,
                },
                status=http.HTTP_409_CONFLICT,
            )

        provider = get_provider(intent.provider)
        reason = request.data.get("reason", "")[:64] if request.data.get("reason") else ""

        with transaction.atomic():
            result = provider.refund(
                provider_intent_id=intent.provider_intent_id,
                amount_minor=amount,
                currency=intent.currency,
                reason=reason,
            )
            now = timezone.now()
            refund = Refund.objects.create(
                intent=intent,
                amount_minor=amount,
                currency=intent.currency,
                provider=intent.provider,
                provider_refund_id=result.provider_refund_id,
                reason=reason,
                status=(
                    Refund.Status.SUCCEEDED
                    if result.status == "succeeded"
                    else Refund.Status.PENDING
                ),
                succeeded_at=now if result.status == "succeeded" else None,
            )
            PaymentEvent.objects.create(
                intent=intent,
                provider=intent.provider,
                provider_event_id=f"evt_refund_{refund.provider_refund_id}",
                kind=(
                    PaymentEvent.Kind.REFUND_SUCCEEDED
                    if result.status == "succeeded"
                    else PaymentEvent.Kind.REFUND_CREATED
                ),
                payload={"amount_minor": amount, "currency": intent.currency},
            )

            total_refunded = refunded_so_far + (amount if result.status == "succeeded" else 0)
            if total_refunded >= intent.amount_minor:
                intent.status = PaymentIntent.Status.REFUNDED
                intent.refunded_at = now
            else:
                intent.status = PaymentIntent.Status.REFUND_PENDING
            intent.save(update_fields=["status", "refunded_at", "updated_at"])

            redis_bus.publish_after_commit(
                channels.PAYMENT_REFUNDED,
                {
                    "intent_id": intent.id,
                    "refund_id": refund.id,
                    "offer_id": intent.offer_id,
                    "amount_minor": amount,
                    "currency": intent.currency,
                    "full": intent.status == PaymentIntent.Status.REFUNDED,
                },
                targets=[intent.payer_id],
            )

        return Response(
            {
                "intent": PaymentIntentSerializer(_refetch(intent.pk)).data,
                "refund": RefundSerializer(refund).data,
            },
            status=http.HTTP_201_CREATED,
        )


class MockWebhookView(APIView):
    """Dev/QA endpoint to simulate provider webhooks.

    Body: {"provider_intent_id": "...", "event": "succeeded"|"failed"}

    No auth — this only exists in V1 to let QA force a transition without
    going through `create`. In V2 a real signed webhook from Stripe /
    Edahabia replaces this entirely.
    """

    permission_classes = (AllowAny,)

    def post(self, request: Request) -> Response:
        pid = request.data.get("provider_intent_id")
        event = request.data.get("event")
        if not pid or event not in {"succeeded", "failed"}:
            return Response(
                {"detail": "Need provider_intent_id and event in {succeeded,failed}."},
                status=http.HTTP_400_BAD_REQUEST,
            )
        intent = PaymentIntent.objects.filter(provider_intent_id=pid).first()
        if intent is None:
            return Response(
                {"detail": "No intent with that provider id."},
                status=http.HTTP_404_NOT_FOUND,
            )
        if intent.status == PaymentIntent.Status.SUCCEEDED and event == "succeeded":
            return Response(PaymentIntentSerializer(intent).data, status=http.HTTP_200_OK)

        with transaction.atomic():
            if event == "succeeded":
                _synthesize_succeeded(intent, intent.provider_intent_id)
            else:
                intent.status = PaymentIntent.Status.FAILED
                intent.failure_code = "mock_failed"
                intent.failure_message = "Mock failure"
                intent.save(
                    update_fields=[
                        "status",
                        "failure_code",
                        "failure_message",
                        "updated_at",
                    ]
                )
                PaymentEvent.objects.create(
                    intent=intent,
                    provider=intent.provider,
                    provider_event_id=f"evt_failed_local_{intent.id}",
                    kind=PaymentEvent.Kind.INTENT_FAILED,
                    payload={"code": "mock_failed"},
                )

        return Response(PaymentIntentSerializer(_refetch(intent.pk)).data)
