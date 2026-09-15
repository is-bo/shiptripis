"""HTTP API for sender Boost.

    GET  /api/boosts/policy            the bounds and the rate, before choosing
    GET  /api/parcels/<id>/boost       this request's Boost, economics, history
    PUT  /api/parcels/<id>/boost       set, raise, lower or remove it
    GET  /api/parcels/<id>/boosts      retired paid-package history (audit)
    POST /api/parcels/<id>/boosts      410 Gone -- packages are not sold
    GET  /api/boosts/packages          410 Gone
    POST /api/boosts/preview           410 Gone

A J2 Boost is not a purchase, so nothing in this module creates a payment
order, opens a checkout or waits for a provider. The amount is a property of
the request until the commitment boundary copies it onto the Deal, and it is
collected inside the Deal balance like every other cent the sender owes.

Boost is owner-or-staff only. What a sender is willing to pay, and how often
they have changed their mind about it, is not something other users may read
off a public request.
"""

from __future__ import annotations

import logging

from django.shortcuts import get_object_or_404
from rest_framework import status as http
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.core.phase4_policy import InvalidPhase4Policy, phase4_policy
from apps.parcels.models import DeliveryRequest

from .serializers import BoostIntentSerializer
from .services import (
    BoostError,
    NotAuthorized,
    boost_policy_payload,
    boost_state,
    set_boost_intent,
)

logger = logging.getLogger(__name__)

#: The failures this API knows how to speak about. Anything else is a bug and
#: must reach DRF's own handler rather than being reshaped into a boost error --
#: a blanket `except Exception` here would quietly turn a database failure into
#: a 500 that looks like a domain refusal.
MAPPED_FAILURES = (
    BoostError,
    NoActiveBusinessSettings,
    InvalidPhase4Policy,
)

RETIRED_DETAIL = (
    "Paid boost packages are retired. A boost is now extra reward on the "
    "request: use PUT /api/parcels/<id>/boost."
)


def _error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code and structured detail.

    Every branch is explicit, and an unrecognised exception becomes a generic
    `internal_error` with its message suppressed rather than echoed.
    """

    if isinstance(exc, NotAuthorized):
        status_code = http.HTTP_403_FORBIDDEN
    elif isinstance(exc, BoostError):
        status_code = http.HTTP_409_CONFLICT
    elif isinstance(exc, (NoActiveBusinessSettings, InvalidPhase4Policy)):
        status_code = http.HTTP_503_SERVICE_UNAVAILABLE
    else:
        logger.error("Unmapped boost failure", exc_info=True)
        return Response(
            {
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            status=http.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    payload = {"code": getattr(exc, "code", "boost_error"), "detail": str(exc)}
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=status_code)


class BoostPolicyView(APIView):
    """What a sender may choose, before they choose it.

    Fails closed. A settings revision that cannot drive Phase 4 returns 503
    rather than a permissive default, because "boosts are off" and "we cannot
    price a boost right now" are different answers and only one of them is true.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        try:
            policy = phase4_policy()
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(boost_policy_payload(policy))


class RequestBoostIntentView(APIView):
    """Read or change one request's Boost."""

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        delivery_request = get_object_or_404(DeliveryRequest, pk=pk)
        if delivery_request.sender_id != request.user.id and not request.user.is_staff:
            return _error_response(
                NotAuthorized("Only the sender may see this request's boost.")
            )
        try:
            state = boost_state(
                delivery_request=delivery_request, viewer_id=request.user.id
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(state)

    def put(self, request: Request, pk: int) -> Response:
        get_object_or_404(DeliveryRequest, pk=pk)
        serializer = BoostIntentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            state = set_boost_intent(
                delivery_request_id=pk,
                actor_id=request.user.id,
                amount_eur_cents=serializer.validated_data["boost_eur_cents"],
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(state)


class RequestBoostHistoryView(APIView):
    """The retired paid-package history for one request.

    `GET` still answers, because a historical purchase is a settled payment and
    the person who made it may always read it back. `POST` is gone.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        delivery_request = get_object_or_404(DeliveryRequest, pk=pk)
        if delivery_request.sender_id != request.user.id and not request.user.is_staff:
            return _error_response(
                NotAuthorized("Only the sender may see this request's boosts.")
            )
        try:
            state = boost_state(
                delivery_request=delivery_request, viewer_id=request.user.id
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(state)

    def post(self, request: Request, pk: int) -> Response:
        del request, pk
        return Response(
            {"code": "boost_package_retired", "detail": RETIRED_DETAIL},
            status=http.HTTP_410_GONE,
        )


class RetiredBoostPackageView(APIView):
    """The package catalogue and its preview. Both retired by J2.

    Answering 410 rather than deleting the route is deliberate: a client built
    against the old contract gets a named, machine-readable retirement instead
    of a 404 it would report to the user as a network fault.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        del request
        return Response(
            {"code": "boost_package_retired", "detail": RETIRED_DETAIL},
            status=http.HTTP_410_GONE,
        )

    def post(self, request: Request) -> Response:
        return self.get(request)
