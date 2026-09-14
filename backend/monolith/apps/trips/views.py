"""Trip API.

Endpoints:
  GET  /api/airports                 — list (filter by ?country=DZ)
  GET  /api/trips                    — list (mine, with ?status=active)
  GET  /api/trips/search             — public search (active trips, not mine)
  POST /api/trips                    — create
  GET  /api/trips/<id>               — retrieve (any auth user)
  POST /api/trips/<id>/cancel        — cancel (owner only, while active)

Per CLAUDE.md G6, every Trip lifecycle change publishes via
`redis_bus.publish_after_commit` so the Go services can fan out.
"""

from __future__ import annotations

import logging
from decimal import Decimal

from django.db import IntegrityError
from django.db.models import (
    DecimalField,
    Exists,
    F,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.core.storage import (
    ext_for_content_type,
    image_bytes_match_extension,
    make_key,
    put_object,
    storage_for,
)
from apps.deals.models import DealLegAllocation
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping

from .models import (
    Airport,
    Journey,
    JourneyLeg,
    JourneyLegProof,
    Trip,
)
from .serializers import (
    AirportSerializer,
    JourneyCreateSerializer,
    JourneyLegProofSerializer,
    JourneySearchFilterSerializer,
    JourneySerializer,
    JourneyUpdateSerializer,
    TripSerializer,
)
from .services import (
    JourneyDomainError,
    cancel_journey,
    journey_editability,
    publish_journey,
    validate_journey_verification_gates,
)

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

logger = logging.getLogger("apps.trips")


class AirportListView(APIView):
    permission_classes = (AllowAny,)

    def get(self, request: Request) -> Response:
        qs = Airport.objects.all()
        country = request.query_params.get("country")
        if country:
            qs = qs.filter(country=country.upper())
        return Response(AirportSerializer(qs, many=True).data)


class TripListCreateView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        qs = (
            Trip.objects.filter(traveler=request.user)
            .select_related("origin", "destination", "traveler")
            .prefetch_related("stopovers__airport")
        )
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response(TripSerializer(qs[:100], many=True).data)

    def post(self, request: Request) -> Response:
        del request
        return Response(
            {
                "code": "legacy_trip_flow_retired",
                "detail": "Use POST /api/journeys with ordered FLIGHT/DRIVE legs.",
            },
            status=status.HTTP_410_GONE,
        )


class TripSearchView(APIView):
    """Public trip search for senders looking for travelers.

    Only returns trips in ACTIVE status that are NOT the caller's own. Filters:
      ?origin=ALG&destination=CDG     IATA codes (uppercased)
      ?departure_after=2026-05-20T00:00:00Z   ISO 8601, accepts naive
      ?min_capacity_kg=2              integer
    Results are ordered by earliest departure first; capped at 100 rows.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        del request
        return Response(
            {
                "code": "legacy_trip_search_retired",
                "detail": "Search active V1 Journeys instead.",
            },
            status=status.HTTP_410_GONE,
        )


class TripDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        trip = get_object_or_404(
            Trip.objects.select_related(
                "origin", "destination", "traveler"
            ).prefetch_related("stopovers__airport"),
            pk=pk,
        )
        if trip.traveler_id != request.user.id and not request.user.is_staff:
            return Response(
                {"detail": "Legacy Trip history is owner-only."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(TripSerializer(trip).data)


class TripCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        del request, pk
        return Response(
            {
                "code": "legacy_trip_flow_retired",
                "detail": "Legacy Trip mutations are retired; use Journey APIs.",
            },
            status=status.HTTP_410_GONE,
        )


class TripMediaUploadView(APIView):
    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)

    def post(self, request: Request, pk: int) -> Response:
        del request, pk
        return Response(
            {
                "code": "legacy_trip_flow_retired",
                "detail": "Legacy Trip media writes are retired; use Journey proof APIs.",
            },
            status=status.HTTP_410_GONE,
        )


def _journey_queryset():
    active_mapping = AirportLocalityMapping.objects.filter(
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).select_related("locality", "locality__parent")
    proof_queryset = JourneyLegProof.objects.select_related("leg__journey").order_by(
        "-created_at"
    )
    leg_queryset = (
        JourneyLeg.objects.select_related(
            "journey", "origin", "destination", "origin_place", "destination_place"
        )
        .prefetch_related(
            Prefetch("proofs", queryset=proof_queryset),
            Prefetch(
                "origin_place__airport_mappings",
                queryset=active_mapping,
                to_attr="_active_matching_mappings",
            ),
            Prefetch(
                "destination_place__airport_mappings",
                queryset=active_mapping,
                to_attr="_active_matching_mappings",
            ),
        )
        .order_by("position")
    )
    return Journey.objects.select_related(
        "traveler",
        "start_location",
        "destination_location",
        "start_place",
        "destination_place",
        "legacy_trip",
    ).prefetch_related(
        Prefetch("legs", queryset=leg_queryset),
        Prefetch(
            "start_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
        Prefetch(
            "destination_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
    )


def _public_journey_queryset():
    active_mapping = AirportLocalityMapping.objects.filter(
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).select_related("locality", "locality__parent")
    approved_proof = JourneyLegProof.objects.filter(
        leg_id=OuterRef("pk"),
        status=JourneyLegProof.Status.APPROVED,
    )
    leg_queryset = (
        JourneyLeg.objects.select_related(
            "journey", "origin", "destination", "origin_place", "destination_place"
        )
        .annotate(has_approved_proof_value=Exists(approved_proof))
        .prefetch_related(
            Prefetch(
                "origin_place__airport_mappings",
                queryset=active_mapping,
                to_attr="_active_matching_mappings",
            ),
            Prefetch(
                "destination_place__airport_mappings",
                queryset=active_mapping,
                to_attr="_active_matching_mappings",
            ),
        )
        .order_by("position")
    )
    return Journey.objects.select_related(
        "traveler",
        "start_location",
        "destination_location",
        "start_place",
        "destination_place",
        "legacy_trip",
    ).prefetch_related(
        Prefetch("legs", queryset=leg_queryset),
        Prefetch(
            "start_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
        Prefetch(
            "destination_place__airport_mappings",
            queryset=active_mapping,
            to_attr="_active_matching_mappings",
        ),
    )


class JourneyListCreateView(APIView):
    """List the caller's journeys or create a new nested-leg draft."""

    permission_classes = (IsAuthenticated,)
    throttle_scope = "journey_routes"

    def get_throttles(self):
        if self.request.method == "POST":
            return [UserRateThrottle(), ScopedRateThrottle()]
        return super().get_throttles()

    def get(self, request: Request) -> Response:
        from .lifecycle import with_lifecycle
        queryset = with_lifecycle(_journey_queryset().filter(traveler=request.user))
        status_filter = request.query_params.get("status")
        if status_filter:
            allowed_statuses = {choice for choice, _ in Journey.Status.choices}
            if status_filter not in allowed_statuses:
                return Response(
                    {"detail": "Unknown journey status."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(lifecycle_status=status_filter)
        return Response(
            JourneySerializer(
                queryset[:100],
                many=True,
                context={"request": request},
            ).data
        )

    def post(self, request: Request) -> Response:
        serializer = JourneyCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        journey = serializer.save()
        journey = _journey_queryset().get(pk=journey.pk)
        return Response(
            JourneySerializer(journey, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class JourneySearchView(APIView):
    """Search public, active V1 Journeys using coarse domain filters.

    ``min_capacity_kg`` applies to every leg because capacity is segment
    scoped. Results are ordered by the first departure and capped until the
    shared API pagination contract is introduced.
    """

    permission_classes = (IsAuthenticated,)

    def get(self, request: Request) -> Response:
        filters = JourneySearchFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        values = filters.validated_data

        leg_scope = JourneyLeg.objects.filter(journey_id=OuterRef("pk"))
        approved_kyc = KycSubmission.objects.filter(
            user_id=OuterRef("traveler_id"),
            status=KycSubmission.Status.APPROVED,
        ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
        approved_proof = JourneyLegProof.objects.filter(
            leg_id=OuterRef("pk"),
            status=JourneyLegProof.Status.APPROVED,
        )
        ineligible_flight_leg = (
            JourneyLeg.objects.filter(
                journey_id=OuterRef("pk"),
                mode=JourneyLeg.Mode.FLIGHT,
            )
            .alias(has_approved_proof=Exists(approved_proof))
            .filter(has_approved_proof=False)
        )
        from .lifecycle import discoverable
        queryset = (
            discoverable(_public_journey_queryset())
            .exclude(traveler=request.user)
            .alias(
                has_legs=Exists(leg_scope),
                has_current_kyc=Exists(approved_kyc),
                has_ineligible_flight_leg=Exists(ineligible_flight_leg),
                first_departure=Subquery(
                    leg_scope.order_by("position").values("depart_at")[:1]
                ),
            )
            .filter(
                has_legs=True,
                has_current_kyc=True,
                has_ineligible_flight_leg=False,
            )
        )
        if start_id := values.get("start_location_id"):
            queryset = queryset.filter(start_location_id=start_id)
        if destination_id := values.get("destination_location_id"):
            queryset = queryset.filter(destination_location_id=destination_id)
        if start_place_id := values.get("start_place_id"):
            queryset = queryset.filter(start_place_id=start_place_id)
        if destination_place_id := values.get("destination_place_id"):
            queryset = queryset.filter(destination_place_id=destination_place_id)
        if mode := values.get("mode"):
            queryset = queryset.alias(
                has_requested_mode=Exists(leg_scope.filter(mode=mode))
            ).filter(has_requested_mode=True)
        if departure_after := values.get("departure_after"):
            queryset = queryset.filter(first_departure__gte=departure_after)
        if min_capacity := values.get("min_capacity_kg"):
            allocated = (
                DealLegAllocation.objects.active()
                .filter(
                    journey_leg_id=OuterRef("pk"),
                )
                .values("journey_leg_id")
                .annotate(total=Sum("allocated_weight_kg"))
                .values("total")[:1]
            )
            decimal_field = DecimalField(max_digits=10, decimal_places=3)
            queryset = queryset.alias(
                has_under_capacity=Exists(
                    leg_scope.annotate(
                        reserved_capacity=Coalesce(
                            Subquery(allocated, output_field=decimal_field),
                            Value(Decimal("0.000")),
                            output_field=decimal_field,
                        )
                    ).filter(
                        capacity_kg__lt=F("reserved_capacity")
                        + Value(min_capacity, output_field=decimal_field)
                    )
                )
            ).filter(has_under_capacity=False)

        queryset = queryset.order_by("first_departure", "pk")[:100]
        return Response(
            JourneySerializer(
                queryset,
                many=True,
                context={"request": request},
            ).data
        )


class JourneyDetailView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request: Request, pk: int) -> Response:
        # Draft and verification details belong to their traveler. Active
        # journeys are discoverable to authenticated marketplace users, with
        # coarse Location serialization and private proof fields redacted.
        journey = get_object_or_404(
            _journey_queryset().filter(
                Q(traveler=request.user) | Q(status__in=[Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS])
            ),
            pk=pk,
        )
        if journey.traveler_id != request.user.id:
            from .lifecycle import discoverable
            if not discoverable(Journey.objects.filter(pk=journey.pk)).exists():
                raise Http404("Journey is not currently matchable.")
            try:
                validate_journey_verification_gates(journey)
            except JourneyDomainError as exc:
                raise Http404("Journey is not currently matchable.") from exc
        return Response(
            JourneySerializer(
                journey,
                context={
                    "request": request,
                    # The owner is told whether they may edit, and when they
                    # may not, why. A hidden button explains nothing.
                    "editability": (
                        journey_editability(journey, actor=request.user)
                        if journey.traveler_id == request.user.id
                        else None
                    ),
                },
            ).data
        )

    def patch(self, request: Request, pk: int) -> Response:
        """Rewrite an editable journey's route, times, capacity and notes.

        The client sends the whole chain, exactly as on create. A route is
        only meaningful whole: inserting one stop changes two segments, and a
        partial patch of one of them describes a route that never existed.
        """

        journey = get_object_or_404(Journey, pk=pk)
        blocked = journey_editability(journey, actor=request.user)
        if not blocked.editable:
            return Response(
                {"code": blocked.code, "detail": blocked.message, "status": journey.status},
                status=(
                    status.HTTP_403_FORBIDDEN
                    if blocked.code == "journey_not_owned"
                    else status.HTTP_409_CONFLICT
                ),
            )

        serializer = JourneyUpdateSerializer(
            instance=journey,
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except JourneyDomainError as exc:
            return Response(
                {"code": exc.code, "detail": exc.message},
                status=(
                    status.HTTP_403_FORBIDDEN
                    if exc.code == "journey_not_owned"
                    else status.HTTP_409_CONFLICT
                ),
            )

        change = serializer.route_change
        fresh = _journey_queryset().get(pk=journey.pk)
        return Response(
            {
                **JourneySerializer(
                    fresh,
                    context={
                        "request": request,
                        "editability": journey_editability(fresh, actor=request.user),
                    },
                ).data,
                # Not decoration: an edit that sent a reviewed boarding pass
                # back to the queue has changed when this journey can go live,
                # and the traveller has to hear it from the response that did
                # it rather than from a publish refusal days later.
                "route_change": {
                    "legs_created": change.legs_created,
                    "legs_updated": change.legs_updated,
                    "legs_removed": change.legs_removed,
                    "proofs_reset_for_review": change.proofs_reset_for_review,
                    "proofs_discarded": change.proofs_discarded,
                },
            }
        )


class JourneyPublishView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        journey = get_object_or_404(Journey, pk=pk)
        try:
            journey = publish_journey(journey=journey, actor=request.user)
        except JourneyDomainError as exc:
            response_status = (
                status.HTTP_403_FORBIDDEN
                if exc.code == "journey_not_owned"
                else status.HTTP_409_CONFLICT
            )
            return Response(
                {"code": exc.code, "detail": exc.message},
                status=response_status,
            )
        journey = _journey_queryset().get(pk=journey.pk)
        return Response(JourneySerializer(journey, context={"request": request}).data)


class JourneyCancelView(APIView):
    permission_classes = (IsAuthenticated,)

    def post(self, request: Request, pk: int) -> Response:
        journey = get_object_or_404(Journey, pk=pk)
        try:
            result = cancel_journey(journey=journey, actor=request.user)
        except JourneyDomainError as exc:
            response_status = (
                status.HTTP_403_FORBIDDEN
                if exc.code == "journey_not_owned"
                else status.HTTP_409_CONFLICT
            )
            return Response(
                {"code": exc.code, "detail": exc.message},
                status=response_status,
            )
        journey = _journey_queryset().get(pk=result.journey.pk)
        return Response(
            {
                "journey": JourneySerializer(
                    journey,
                    context={"request": request},
                ).data,
                "released_allocations": result.released_allocations,
                "changed": result.changed,
            }
        )


class JourneyLegProofCreateView(APIView):
    """Private flight proof for one leg of the caller's own draft journey.

    Every refusal here carries a machine code. The screen on the other end is
    a phone with one image on it, and "something went wrong" is the difference
    between a traveller who crops their boarding pass and one who gives up —
    which is exactly what the Phase 8F-A device QA found.
    """

    permission_classes = (IsAuthenticated,)
    parser_classes = (MultiPartParser,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "media_upload"

    _ALLOWED_KINDS = {
        "ticket",
        "boarding_pass",
        "booking_confirmation",
    }

    @staticmethod
    def _error(code: str, detail: str, http_status: int) -> Response:
        return Response({"code": code, "detail": detail}, status=http_status)

    def post(self, request: Request, journey_pk: int, leg_pk: int) -> Response:
        leg = get_object_or_404(
            JourneyLeg.objects.select_related("journey"),
            pk=leg_pk,
            journey_id=journey_pk,
        )
        if leg.journey.traveler_id != request.user.pk:
            return self._error(
                "journey_not_owned",
                "Only the journey owner can add flight proof.",
                status.HTTP_403_FORBIDDEN,
            )
        if leg.mode != JourneyLeg.Mode.FLIGHT:
            return self._error(
                "proof_only_for_flight",
                "Transport proof can only be added to flight legs.",
                status.HTTP_400_BAD_REQUEST,
            )
        if leg.journey.status not in {
            Journey.Status.DRAFT,
            Journey.Status.PENDING_VERIFICATION,
        }:
            return self._error(
                "journey_proof_upload_closed",
                "Proof can only be added before journey publication.",
                status.HTTP_409_CONFLICT,
            )

        upload = request.FILES.get("photo")
        if upload is None:
            return self._error(
                "proof_file_missing",
                "Send the file under the 'photo' field.",
                status.HTTP_400_BAD_REQUEST,
            )
        if upload.size > MAX_UPLOAD_BYTES:
            return self._error(
                "proof_file_too_large",
                "File exceeds 10 MiB.",
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
        ext = ext_for_content_type(upload.content_type or "")
        if ext is None:
            return self._error(
                "proof_media_type_unsupported",
                "Only JPEG / PNG / WebP images are allowed.",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )
        body = upload.read()
        if not image_bytes_match_extension(body, ext):
            return self._error(
                "proof_media_type_unsupported",
                "File content is not a valid image of the declared type.",
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        kind = request.data.get("kind") or "ticket"
        if kind not in self._ALLOWED_KINDS:
            return self._error(
                "proof_kind_unknown",
                "Unknown flight proof kind.",
                status.HTTP_400_BAD_REQUEST,
            )

        idempotency_key = str(request.data.get("idempotency_key") or "").strip()[:64]
        if idempotency_key:
            # A retry after a timeout must re-attach to the row the first
            # attempt may already have written, not add a second copy of the
            # same boarding pass to a reviewer's queue.
            existing = JourneyLegProof.objects.filter(
                leg=leg, idempotency_key=idempotency_key
            ).first()
            if existing is not None:
                return Response(
                    JourneyLegProofSerializer(
                        existing,
                        context={"request": request},
                    ).data,
                    status=status.HTTP_200_OK,
                )

        # The private media bucket Django's own credential owns. Not the
        # KYC bucket: that belongs to the Go KYC service's key, which is how
        # every deployed proof upload came to 500 before Phase 8F-A.
        bucket = storage_for("proof").require_bucket()
        key = make_key(f"journeys/{journey_pk}/legs/{leg_pk}/proofs", ext)
        try:
            put_object(
                bucket=bucket,
                key=key,
                body=body,
                content_type=upload.content_type,
            )
        except Exception:
            # The provider's own message names buckets, keys and credentials.
            # It goes to the log with the request id and never to the phone.
            logger.exception(
                "flight proof upload failed",
                extra={"journey_id": journey_pk, "journey_leg_id": leg_pk},
            )
            return self._error(
                "proof_storage_unavailable",
                "Proof storage is temporarily unavailable.",
                status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            proof = JourneyLegProof.objects.create(
                leg=leg,
                bucket=bucket,
                object_key=key,
                content_type=upload.content_type,
                bytes=len(body),
                kind=kind,
                idempotency_key=idempotency_key,
            )
        except IntegrityError:
            # Two retries raced. The first one's row is the answer; the object
            # this attempt wrote is an orphan the lifecycle policy reclaims.
            proof = JourneyLegProof.objects.filter(
                leg=leg, idempotency_key=idempotency_key
            ).first()
            if proof is None:
                raise
            return Response(
                JourneyLegProofSerializer(
                    proof,
                    context={"request": request},
                ).data,
                status=status.HTTP_200_OK,
            )
        return Response(
            JourneyLegProofSerializer(
                proof,
                context={"request": request},
            ).data,
            status=status.HTTP_201_CREATED,
        )
