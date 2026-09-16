"""ShipTrip V1 offer APIs.

These endpoints deliberately do not reuse the legacy airport/DZD write paths.
All money is calculated by the server in EUR cents from one versioned business
settings row, and acceptance atomically creates the Deal and leg allocations.
"""

from __future__ import annotations

import logging

from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import IsAdminUser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.core.business_settings import NoActiveBusinessSettings
from apps.deals.serializers import DealSerializer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.models import Journey

from .discovery import (
    compatible_journeys_for_request,
    compatible_requests_for_journey,
    explain_candidate,
    phase2_policy,
)
from .find_travelers import find_travelers, request_ineligibility
from .models import Offer
from .policy import InvalidPhase2Policy
from .pricing import PricingError
from .serializers import (
    CandidateExplanationQuerySerializer,
    CompatibleJourneysQuerySerializer,
    CompatibleRequestsQuerySerializer,
    CounterOfferV1Serializer,
    FindTravelersQuerySerializer,
    OfferSerializer,
    PricingQuoteV1Serializer,
    SenderProposeV1Serializer,
)
from .public_contract import public_compatibility_payload
from .v1_services import (
    CapacityExceeded,
    InvalidLegRange,
    OfferAuthorizationError,
    OfferStateError,
    V1OfferError,
    accept_offer,
    counter_offer,
    create_sender_offer,
)

logger = logging.getLogger(__name__)


def _product_retired_response() -> Response:
    return Response(
        {
            "code": "product_request_retired",
            "detail": "ProductRequest/Kaba offer mutations are retired in ShipTrip V1.",
        },
        status=status.HTTP_410_GONE,
    )


def _domain_error_response(exc: Exception) -> Response:
    """Map a domain failure to its machine code, status and structured detail.

    Every branch is explicit. An unrecognised exception is reported as a
    generic `internal_error` rather than being mislabelled as a business
    settings outage, and its message is not echoed back to the caller.
    """

    if isinstance(exc, IntegrityError):
        logger.warning("V1 matching constraint conflict", exc_info=True)
        return Response(
            {
                "code": "constraint_conflict",
                "detail": "The requested state conflicts with a concurrent update.",
            },
            status=status.HTTP_409_CONFLICT,
        )
    if isinstance(exc, OfferAuthorizationError):
        response_status = status.HTTP_403_FORBIDDEN
    elif isinstance(exc, InvalidLegRange):
        response_status = status.HTTP_400_BAD_REQUEST
    elif isinstance(exc, (CapacityExceeded, OfferStateError, V1OfferError)):
        response_status = status.HTTP_409_CONFLICT
    elif isinstance(exc, NoActiveBusinessSettings):
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, InvalidPhase2Policy):
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, PricingError):
        response_status = status.HTTP_409_CONFLICT
    else:
        logger.error("Unmapped V1 matching failure", exc_info=True)
        return Response(
            {
                "code": "internal_error",
                "detail": "The request could not be completed.",
            },
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    payload = {
        "code": getattr(exc, "code", "internal_error"),
        "detail": str(exc),
    }
    details = getattr(exc, "details", None)
    if callable(details):
        payload.update(details())
    return Response(payload, status=response_status)


def _request_for_owner(*, pk: int, user):
    delivery_request = get_object_or_404(
        DeliveryRequest.objects.select_related(
            "sender",
            "pickup_location",
            "delivery_location",
            "pickup_place",
            "delivery_place",
        ),
        pk=pk,
    )
    if delivery_request.sender_id != user.id:
        raise OfferAuthorizationError(
            "Only the request sender may discover or quote matches."
        )
    return delivery_request


class RetiredLegacyMatchingWriteView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, *args, **kwargs) -> Response:
        del request, args, kwargs
        return Response(
            {
                "code": "legacy_matching_flow_retired",
                "detail": (
                    "Legacy traveler-first and DZD matching writes are retired. "
                    "Use the ShipTrip V1 sender proposal endpoint."
                ),
            },
            status=status.HTTP_410_GONE,
        )


class SenderProposeV1View(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request) -> Response:
        serializer = SenderProposeV1Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        delivery_request = get_object_or_404(DeliveryRequest, pk=data["parcel_id"])
        journey = get_object_or_404(Journey, pk=data["journey_id"])
        try:
            offer = create_sender_offer(
                sender=request.user,
                delivery_request=delivery_request,
                journey=journey,
                start_leg_id=data["start_leg_id"],
                end_leg_id=data["end_leg_id"],
                traveler_reward_eur_cents=data["traveler_reward_eur_cents"],
                note=data.get("note", ""),
            )
        except (
            V1OfferError,
            IntegrityError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)
        return Response(
            OfferSerializer(offer, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class CounterOfferV1View(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        serializer = CounterOfferV1Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        pending_offer = get_object_or_404(
            Offer.objects.select_related("match__parcel"), pk=pk
        )
        if pending_offer.match.parcel.kind == ParcelRequest.Kind.PRODUCT:
            return _product_retired_response()
        try:
            offer = counter_offer(
                pending_offer=pending_offer,
                actor=request.user,
                **serializer.validated_data,
            )
        except (
            V1OfferError,
            IntegrityError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)
        return Response(
            OfferSerializer(offer, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class OfferAcceptV1View(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        pending_offer = get_object_or_404(
            Offer.objects.select_related("match__parcel"), pk=pk
        )
        if pending_offer.match.parcel.kind == ParcelRequest.Kind.PRODUCT:
            return _product_retired_response()
        try:
            accepted = accept_offer(pending_offer=pending_offer, actor=request.user)
        except (
            V1OfferError,
            IntegrityError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)
        response_status = (
            status.HTTP_201_CREATED if accepted.created else status.HTTP_200_OK
        )
        return Response(DealSerializer(accepted.deal).data, status=response_status)


class CompatibleJourneysV1View(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def get(self, request: Request) -> Response:
        serializer = CompatibleJourneysQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            delivery_request = _request_for_owner(
                pk=serializer.validated_data["parcel_id"],
                user=request.user,
            )
            candidates = compatible_journeys_for_request(
                delivery_request=delivery_request,
                policy=phase2_policy(),
            )
        except (
            OfferAuthorizationError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)
        # The caller owns the request, so the detour-bearing recommendation is
        # about their own parcel and may be returned.
        return Response(
            {
                "count": len(candidates),
                "results": [
                    row.as_public_dict(include_recommendation=True)
                    for row in candidates
                ],
            }
        )


class FindTravelersV1View(APIView):
    """`GET /api/matches/find-travelers` — the frozen J4 browse contract.

    Supersedes `compatible-journeys` for the Sender's Find Travelers screen.
    The older endpoint keeps answering the shipped J3 app unchanged; this one is
    what Gemini J5 renders.

    Three things it does that the older endpoint cannot.

    It **names the Traveler**, with a first name, a rating state and a completed
    delivery count, so a browse row answers "would I trust this person" without
    a second request per candidate.

    It **pages**. The active policy allows a fifty-row answer, which is a large
    response for a phone and an unreadable one for a human. The authoritative
    result set is unchanged; only how much of it crosses the wire at once.

    It **separates "nobody matches" from "this request cannot be matched"**.
    Both used to arrive as an empty list, because a closed request simply failed
    the `request_active` gate on every candidate in turn.
    """

    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def get(self, request: Request) -> Response:
        serializer = FindTravelersQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data
        try:
            delivery_request = _request_for_owner(
                pk=query["parcel_id"],
                user=request.user,
            )
            policy = phase2_policy()
            # An ineligible request never runs a scan. Discovery would evaluate
            # every candidate only to reject all of them on the same gate.
            if request_ineligibility(delivery_request) is None:
                candidates = compatible_journeys_for_request(
                    delivery_request=delivery_request,
                    policy=policy,
                )
            else:
                candidates = []
        except (
            OfferAuthorizationError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)

        page, block = find_travelers(
            delivery_request=delivery_request,
            candidates=candidates,
            sort=query["sort"],
            # `result_limit` bounds the authoritative result set, so it is also
            # the largest page that could ever be whole.
            limit=min(query["limit"], policy.result_limit),
            offset=query["offset"],
        )
        return Response(page.as_dict(request_block=block))


class CompatibleRequestsV1View(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def get(self, request: Request) -> Response:
        serializer = CompatibleRequestsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        journey = get_object_or_404(
            Journey.objects.select_related("traveler"),
            pk=serializer.validated_data["journey_id"],
        )
        if journey.traveler_id != request.user.id:
            return Response(
                {
                    "code": "not_authorized",
                    "detail": "Only the journey owner may discover compatible requests.",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            candidates = compatible_requests_for_journey(
                journey=journey,
                policy=phase2_policy(),
            )
        except (NoActiveBusinessSettings, InvalidPhase2Policy, PricingError) as exc:
            return _domain_error_response(exc)
        # Bulk-harvest surface: one call returns up to `result_limit` unrelated
        # senders. The traveler cannot propose a price, so the detour-bearing
        # recommendation is withheld and only the geometry-free enforced floor
        # is disclosed.
        return Response(
            {
                "count": len(candidates),
                "results": [
                    row.as_public_dict(include_recommendation=False)
                    for row in candidates
                ],
            }
        )


class PricingQuoteV1View(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def post(self, request: Request) -> Response:
        serializer = PricingQuoteV1Serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            delivery_request = _request_for_owner(
                pk=serializer.validated_data["parcel_id"],
                user=request.user,
            )
            journey = get_object_or_404(
                Journey.objects.select_related("traveler"),
                pk=serializer.validated_data["journey_id"],
            )
            evaluation = explain_candidate(
                delivery_request_id=delivery_request.pk,
                journey_id=journey.pk,
            )
        except (
            OfferAuthorizationError,
            NoActiveBusinessSettings,
            InvalidPhase2Policy,
            PricingError,
        ) as exc:
            return _domain_error_response(exc)
        if not evaluation.compatibility.compatible:
            compatibility = public_compatibility_payload(
                evaluation.compatibility.as_dict()
            )
            return Response(
                {
                    "code": "incompatible_candidate",
                    "detail": "The request and journey do not pass hard compatibility.",
                    "rejection_codes": compatibility["rejection_codes"],
                    "compatibility": compatibility,
                },
                status=status.HTTP_409_CONFLICT,
            )
        # Sender-facing quote. Deliberately not `evaluation.as_dict()`: that is
        # the IsAdminUser explain payload (gate details, ranking weights,
        # per-leg capacity, exact route geometry).
        return Response(evaluation.as_public_dict(include_recommendation=True))


class CandidateExplanationV1View(APIView):
    permission_classes = (IsAdminUser,)
    throttle_classes = (UserRateThrottle, ScopedRateThrottle)
    throttle_scope = "matching_discovery"

    def get(self, request: Request) -> Response:
        serializer = CandidateExplanationQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        try:
            evaluation = explain_candidate(
                delivery_request_id=serializer.validated_data["parcel_id"],
                journey_id=serializer.validated_data["journey_id"],
            )
        except ObjectDoesNotExist:
            return Response(
                {"code": "candidate_not_found", "detail": "Candidate not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except (NoActiveBusinessSettings, InvalidPhase2Policy, PricingError) as exc:
            return _domain_error_response(exc)
        # Admin-only diagnostics: gate details, route positions, exact detours,
        # per-component distances, per-leg capacity and ranking factors. Still
        # no exact coordinates, addresses, provider place IDs or recipient data.
        return Response(evaluation.as_dict())
