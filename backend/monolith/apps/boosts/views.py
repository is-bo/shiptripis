"""HTTP API for paid sender boosts.

    GET  /api/boosts/packages         what may be bought, priced by the server
    POST /api/parcels/<id>/boosts     buy one, get back the payment obligation
    GET  /api/parcels/<id>/boosts     this request's boost history and effect

Nothing in this module activates a boost. A purchase returns a `PaymentOrder`
reference and an amount; the client takes them to the existing
`/api/payments/orders/<reference>/checkout` route, and the boost starts when the
provider's authoritative event reaches `reconcile_attempt`. Returning from a
checkout page is not a payment.

Boost history is owner-or-staff only. What a buyer paid, and how often they have
paid it, is not something other users may read off a public request.
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

from .serializers import (
    BoostPackageSerializer,
    BoostPurchaseCreateSerializer,
    BoostPurchaseSerializer,
)
from .services import (
    BoostError,
    NotAuthorized,
    boost_state,
    list_packages,
    purchase_boost,
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


class BoostPackageListView(APIView):
    """The packages on offer, with server-authoritative prices.

    Fails closed. A settings revision that cannot drive Phase 4 returns 503
    rather than an empty catalogue, because "no boosts exist" and "we cannot
    price boosts right now" are different answers and only one of them is true.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        try:
            policy = phase4_policy()
            packages = list_packages(policy=policy)
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(
            {
                "enabled": policy.boost.enabled,
                "max_active_per_request": policy.boost.max_active_per_request,
                "currency": "EUR",
                "settings_version": policy.settings_version.version,
                "packages": BoostPackageSerializer(packages, many=True).data,
            }
        )


class RequestBoostView(APIView):
    """Buy a boost for one delivery request, or read what it already has.

    Both verbs share a path, so they share a view: `boosts-purchase` and
    `boosts-list` are two names for `parcels/<id>/boosts`, and Django routes by
    path before it dispatches on the method.
    """

    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        """Create the purchase and its payment obligation.

        The response carries the order reference and amount so the client can
        open the existing checkout. The boost itself stays `pending_payment`
        until the provider says otherwise.
        """

        get_object_or_404(DeliveryRequest, pk=pk)
        serializer = BoostPurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            purchase = purchase_boost(
                delivery_request_id=pk,
                actor_id=request.user.id,
                package_code=serializer.validated_data["package_code"],
            )
        except MAPPED_FAILURES as exc:
            return _error_response(exc)
        return Response(
            BoostPurchaseSerializer(purchase).data, status=http.HTTP_201_CREATED
        )

    def get(self, request: Request, pk: int) -> Response:
        """This request's boost history and its current ranking effect."""

        delivery_request = get_object_or_404(DeliveryRequest, pk=pk)
        if (
            delivery_request.sender_id != request.user.id
            and not request.user.is_staff
        ):
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
