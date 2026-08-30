"""HTTP API endpoints for Deal handover codes.

    GET  /api/deals/<id>/handover                       state for both parties
    GET  /api/deals/<id>/handover/pickup-code           sender reveal pickup code
    POST /api/deals/<id>/handover/pickup-code/rotate    sender rotate pickup code
    GET  /api/deals/<id>/handover/delivery-code         sender reveal delivery code
    POST /api/deals/<id>/handover/delivery-code/rotate  sender rotate delivery code
    POST /api/deals/<id>/handover/pickup                traveler submit pickup code
    POST /api/deals/<id>/handover/delivery              traveler submit delivery code

Object-level authorization is enforced against Deal membership: non-parties are
returned 404 to avoid leaking Deal existence. Domain authorization (sender-only
reveals and traveler-only submissions) is enforced inside `apps.handover.services`.
"""

from __future__ import annotations

import logging

from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.phase4_policy import InvalidPhase4Policy
from apps.deals.lifecycle import DealLifecycleError
from apps.deals.models import Deal

from .models import DealHandoverCode
from .serializers import (
    HandoverSubmitSerializer,
    RevealedCodeSerializer,
    SubmissionResultSerializer,
)
from .services import (
    HandoverError,
    NotAuthorized,
    handover_state,
    reveal_code,
    rotate_code,
    submit_code,
)

logger = logging.getLogger(__name__)

#: The failures this API knows how to speak about. Anything else is a bug and
#: must reach DRF's own handler rather than being reshaped into a handover
#: error -- a blanket `except Exception` here would quietly turn a serializer
#: failure or a database error into a 500 that looks like a domain refusal.
MAPPED_FAILURES = (
    HandoverError,
    DealLifecycleError,
    NoActiveBusinessSettings,
    InvalidPhase4Policy,
)


def _handover_error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code and structured detail.

    Every branch is explicit, and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed rather than echoed.
    """
    if isinstance(exc, NotAuthorized):
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, HandoverError):
        if exc.code == "handover_code_invalid":
            status_code = http.HTTP_400_BAD_REQUEST
        elif exc.code == "handover_rate_limited":
            status_code = http.HTTP_429_TOO_MANY_REQUESTS
        else:
            status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, DealLifecycleError):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (NoActiveBusinessSettings, InvalidPhase4Policy)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped handover failure", exc_info=True)
        return Response(
            {
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {"code": getattr(exc, "code", "handover_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


def _party_deal(user_id: int, pk: int) -> Deal:
    """Ensure the deal exists and the caller is a party to it.

    Strangers receive a 404 rather than a 403, preventing unauthorized
    actors from probing whether arbitrary Deal IDs exist.
    """
    return get_object_or_404(
        Deal.objects.filter(Q(sender_id=user_id) | Q(traveler_id=user_id)),
        pk=pk,
    )


class HandoverStateView(APIView):
    """Inspect what either party is permitted to know about the handover codes.

    Neither party's projection contains code material of any kind. Both are
    told when the delivery-code safety window closes, because the sender needs
    the countdown and the traveler already learns the same thing from the Deal
    status; what the traveler is never told is anything that would help them
    produce a code rather than wait for one.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        deal = _party_deal(request.user.id, pk)
        try:
            state = handover_state(deal=deal, viewer_id=request.user.id)
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(state)


class HandoverPickupCodeRevealView(APIView):
    """Reveal the pickup handover code to the Deal sender.

    Unseals the stored ciphertext and writes an immutable HandoverCodeAccess
    audit row. The service layer strictly refuses non-sender callers.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "handover_reveal"

    def get(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        try:
            revealed = reveal_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=request.user.id,
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(RevealedCodeSerializer(revealed).data)


class HandoverPickupCodeRotateView(APIView):
    """Rotate an unconfirmed pickup code, superseding the previous issue.

    Generates and seals a new code for the sender while invalidating the old
    one under the Deal aggregate lock.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        try:
            revealed = rotate_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=request.user.id,
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(RevealedCodeSerializer(revealed).data)


class HandoverDeliveryCodeRevealView(APIView):
    """Reveal the delivery handover code to the Deal sender.

    Refused during the 30-minute safety buffer following pickup confirmation.
    If the safety window has elapsed, this endpoint automatically promotes
    the buffered code and arms the recipient notification in one transaction.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "handover_reveal"

    def get(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        try:
            revealed = reveal_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=request.user.id,
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(RevealedCodeSerializer(revealed).data)


class HandoverDeliveryCodeRotateView(APIView):
    """Rotate the delivery code, superseding the active row and re-arming notifications.

    Refused while inside the safety window. When valid, supersedes the previous
    code and re-queues the outbox notification for the parcel recipient under
    a new idempotency key.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        try:
            revealed = rotate_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=request.user.id,
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(RevealedCodeSerializer(revealed).data)


class HandoverPickupSubmitView(APIView):
    """Verify a pickup handover code submitted by the traveler.

    Rate limited by ScopedRateThrottle to prevent brute-force probing. Every
    submission attempts verification in constant time and records an append-only
    HandoverAttempt row.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "handover_submit"

    def post(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        serializer = HandoverSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = submit_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.PICKUP,
                actor_id=request.user.id,
                submitted_code=serializer.validated_data["code"],
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(SubmissionResultSerializer(result).data)


class HandoverDeliverySubmitView(APIView):
    """Verify a delivery handover code submitted by the traveler.

    On success the service confirms delivery, moves the Deal into its
    protection window and arms the 48-hour payout gate. The traveler reaches
    this endpoint with a code the recipient read to them; there is no route
    anywhere in this module by which they could have fetched it.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "handover_submit"

    def post(self, request: Request, pk: int) -> Response:
        _party_deal(request.user.id, pk)
        serializer = HandoverSubmitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = submit_code(
                deal_id=pk,
                kind=DealHandoverCode.Kind.DELIVERY,
                actor_id=request.user.id,
                submitted_code=serializer.validated_data["code"],
            )
        except MAPPED_FAILURES as exc:
            return _handover_error_response(exc)
        return Response(SubmissionResultSerializer(result).data)
