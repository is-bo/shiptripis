from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from django.db.models import (
    Case,
    DecimalField,
    Exists,
    IntegerField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.conf import settings

from apps.core.business_settings import get_active_business_settings
from apps.deals.models import Deal, DealLegAllocation
from apps.kyc.models import KycSubmission
from apps.locations.models import AirportLocalityMapping, Place
from apps.locations.serializers import PublicLocationSerializer
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.providers import RouteProvider, get_route_provider
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof

from .compatibility import (
    ACTIVE_DEAL_STATUSES,
    CompatibilityResult,
    evaluate_compatibility,
    _matching_locality_id,
)
from .policy import Phase2Policy
from .pricing import PricingQuote, calculate_pricing_quote
from .public_contract import public_compatibility_payload, public_pricing_payload
from .ranking import rank_compatible_candidate


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    delivery_request: DeliveryRequest
    journey: Journey
    compatibility: CompatibilityResult
    pricing: PricingQuote | None
    ranking: dict | None

    def _request_block(self) -> dict:
        def place_summary(place):
            if place is None:
                return None
            locality_id = _matching_locality_id(place)
            return {
                "id": place.pk,
                "name": place.name,
                "display_label": place.display_label,
                "place_type": place.place_type,
                "country_code": place.country_id,
                "iata_code": place.iata_code or None,
                "matching_locality_id": locality_id,
            }

        return {
            "id": self.delivery_request.pk,
            "sender_id": self.delivery_request.sender_id,
            "pickup": (
                PublicLocationSerializer(self.delivery_request.pickup_location).data
                if self.delivery_request.pickup_location
                else place_summary(self.delivery_request.pickup_place)
            ),
            "delivery": (
                PublicLocationSerializer(self.delivery_request.delivery_location).data
                if self.delivery_request.delivery_location
                else place_summary(self.delivery_request.delivery_place)
            ),
            "pickup_place": place_summary(self.delivery_request.pickup_place),
            "delivery_place": place_summary(self.delivery_request.delivery_place),
            "actual_weight_kg": str(self.delivery_request.actual_weight_kg),
            "ready_window_start": self.delivery_request.ready_window_start,
            "ready_window_end": self.delivery_request.ready_window_end,
            "deadline_at": self.delivery_request.deadline_at,
            "sender_proposed_reward_eur_cents": (
                self.delivery_request.traveler_reward_eur_cents
            ),
            # J2. A Boost is extra reward the sender has attached to this
            # request, so it is part of the offer a traveler is looking at --
            # not private commercial history. The total is computed here
            # because no client should be adding up money.
            "boost_eur_cents": int(self.delivery_request.boost_eur_cents or 0),
            "total_offered_reward_eur_cents": (
                int(self.delivery_request.traveler_reward_eur_cents or 0)
                + int(self.delivery_request.boost_eur_cents or 0)
            ),
        }

    def _journey_block(self, compatibility: dict) -> dict:
        legs = list(getattr(self.journey, "_matching_legs", ()))
        covered_leg_ids = compatibility.get("covered_leg_ids") or []
        start_leg_id = compatibility.get("start_leg_id")
        end_leg_id = compatibility.get("end_leg_id")
        if start_leg_id is None and covered_leg_ids:
            start_leg_id = covered_leg_ids[0]
        if end_leg_id is None and covered_leg_ids:
            end_leg_id = covered_leg_ids[-1]

        def place_summary(place):
            if place is None:
                return None
            locality_id = _matching_locality_id(place)
            return {
                "id": place.pk,
                "name": place.name,
                "display_label": place.display_label,
                "place_type": place.place_type,
                "country_code": place.country_id,
                "iata_code": place.iata_code or None,
                "matching_locality_id": locality_id,
            }

        return {
            "id": self.journey.pk,
            "traveler_id": self.journey.traveler_id,
            "start_location": (
                PublicLocationSerializer(self.journey.start_location).data
                if self.journey.start_location
                else place_summary(self.journey.start_place)
            ),
            "destination_location": (
                PublicLocationSerializer(self.journey.destination_location).data
                if self.journey.destination_location
                else place_summary(self.journey.destination_place)
            ),
            "start_place": place_summary(self.journey.start_place),
            "destination_place": place_summary(self.journey.destination_place),
            "first_departure": legs[0].depart_at if legs else None,
            # Proposing needs both endpoint leg IDs and rendering needs the leg
            # modes/labels. Both are served here so a candidate row never costs
            # the client an extra GET /journeys/{id}.
            "start_leg_id": start_leg_id,
            "end_leg_id": end_leg_id,
            "covered_legs": compatibility.get("covered_legs", []),
        }

    def as_dict(self) -> dict:
        """Internal/admin representation. Never serialize this to a party."""

        return {
            "delivery_request": self._request_block(),
            "journey": self._journey_block(self.compatibility.as_dict()),
            "compatibility": self.compatibility.as_dict(),
            "pricing": self.pricing.as_dict() if self.pricing else None,
            "ranking": self.ranking,
        }

    def as_public_dict(self, *, include_recommendation: bool) -> dict:
        """Pre-funding representation for a party.

        `include_recommendation` is set only when the caller owns the delivery
        request. Ranking is omitted in both directions: its factors are linear
        in detour, added distance and delivery time, and they carry the ranking
        weights a sender could otherwise game.
        """

        compatibility = public_compatibility_payload(self.compatibility.as_dict())
        assert compatibility is not None
        return {
            "delivery_request": self._request_block(),
            "journey": self._journey_block(compatibility),
            "compatibility": compatibility,
            "pricing": public_pricing_payload(
                self.pricing.as_dict() if self.pricing else None,
                include_recommendation=include_recommendation,
            ),
        }


def phase2_policy() -> Phase2Policy:
    return Phase2Policy.from_settings(get_active_business_settings())


def _matching_leg_queryset(*, at):
    approved_proof = JourneyLegProof.objects.filter(
        leg_id=OuterRef("pk"),
        status=JourneyLegProof.Status.APPROVED,
    )
    allocated = (
        DealLegAllocation.objects.active(at=at)
        .filter(journey_leg_id=OuterRef("pk"))
        .values("journey_leg_id")
        .annotate(total=Sum("allocated_weight_kg"))
        .values("total")[:1]
    )
    decimal_field = DecimalField(max_digits=10, decimal_places=3)
    active_mapping = AirportLocalityMapping.objects.filter(
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).select_related("locality")
    return (
        JourneyLeg.objects.select_related(
            "origin", "destination", "origin_place", "destination_place"
        )
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
        .annotate(
            has_approved_proof_value=Exists(approved_proof),
            reserved_capacity_value=Coalesce(
                Subquery(allocated, output_field=decimal_field),
                Value(Decimal("0.000")),
                output_field=decimal_field,
            ),
        )
        .order_by("position", "pk")
    )


def _matching_journey_queryset(*, at):
    approved_kyc = KycSubmission.objects.filter(
        user_id=OuterRef("traveler_id"),
        status=KycSubmission.Status.APPROVED,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=at))
    return (
        Journey.objects.select_related(
            "traveler",
            "start_location",
            "destination_location",
            "start_place",
            "destination_place",
        )
        .annotate(has_current_kyc_value=Exists(approved_kyc))
        .prefetch_related(
            Prefetch(
                "legs",
                queryset=_matching_leg_queryset(at=at),
                to_attr="_matching_legs",
            )
        )
    )


def _canonical_node_mapping_q(*, relation: str, locality_id: int) -> Q:
    """Match an airport node only through its active primary served mapping."""

    mapping = f"{relation}__airport_mappings"
    return Q(
        **{
            f"{mapping}__locality_id": locality_id,
            f"{mapping}__active": True,
            f"{mapping}__is_primary": True,
            f"{mapping}__relationship_type": AirportLocalityMapping.RelationshipType.SERVED,
            f"{mapping}__locality__active": True,
        }
    )


def _canonical_place_in_localities_q(
    *, field: str, locality_ids: set[int]
) -> Q:
    """Match a canonical place directly or through an active served airport map."""

    return Q(**{f"{field}_id__in": locality_ids}) | Q(
        **{
            f"{field}__airport_mappings__locality_id__in": locality_ids,
            f"{field}__airport_mappings__active": True,
            f"{field}__airport_mappings__is_primary": True,
            f"{field}__airport_mappings__relationship_type": AirportLocalityMapping.RelationshipType.SERVED,
            f"{field}__airport_mappings__locality__active": True,
        }
    )


def evaluate_candidate(
    *,
    delivery_request: DeliveryRequest,
    journey: Journey,
    policy: Phase2Policy,
    at=None,
    route_provider: RouteProvider | None = None,
) -> CandidateEvaluation:
    at = at or timezone.now()
    compatibility = evaluate_compatibility(
        delivery_request=delivery_request,
        journey=journey,
        policy=policy,
        at=at,
        route_provider=route_provider,
    )
    pricing = None
    ranking = None
    if compatibility.compatible:
        assert compatibility.matched_distance_meters is not None
        assert compatibility.delivery_at is not None
        pricing = calculate_pricing_quote(
            delivery_request=delivery_request,
            matched_distance_meters=compatibility.matched_distance_meters,
            matched_distance_method=compatibility.matched_distance_method,
            added_distance_meters=compatibility.added_distance_meters,
            estimated_arrival_at=compatibility.delivery_at,
            policy=policy,
        )
        ranking = rank_compatible_candidate(
            compatibility=compatibility,
            delivery_request=delivery_request,
            policy=policy,
            at=at,
        )
    return CandidateEvaluation(
        delivery_request=delivery_request,
        journey=journey,
        compatibility=compatibility,
        pricing=pricing,
        ranking=ranking,
    )


def compatible_journeys_for_request(
    *,
    delivery_request: DeliveryRequest,
    policy: Phase2Policy,
    at=None,
) -> list[CandidateEvaluation]:
    at = at or timezone.now()
    delivery_request.has_active_deal_value = delivery_request.deals.filter(
        status__in=ACTIVE_DEAL_STATUSES
    ).exists()
    route_provider = get_route_provider(
        external_call_budget=settings.ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST
    )
    overlapping_leg = JourneyLeg.objects.filter(
        journey_id=OuterRef("pk"),
        depart_at__lte=delivery_request.ready_window_end,
    ).filter(
        Q(arrive_at__isnull=True)
        | Q(arrive_at__gte=delivery_request.ready_window_start)
    )
    canonical = delivery_request.schema_version >= 3
    if canonical:
        pickup_locality = delivery_request.pickup_place
        delivery_locality = delivery_request.delivery_place
        if pickup_locality.place_type == Place.PlaceType.AIRPORT:
            mapping = pickup_locality.airport_mappings.filter(
                active=True,
                is_primary=True,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                locality__active=True,
            ).first()
            pickup_locality = mapping.locality if mapping else None
        if delivery_locality.place_type == Place.PlaceType.AIRPORT:
            mapping = delivery_locality.airport_mappings.filter(
                active=True,
                is_primary=True,
                relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
                locality__active=True,
            ).first()
            delivery_locality = mapping.locality if mapping else None
        if pickup_locality is None or delivery_locality is None:
            return []
        pickup_node = JourneyLeg.objects.filter(journey_id=OuterRef("pk")).filter(
            _canonical_node_mapping_q(
                relation="origin_place", locality_id=pickup_locality.pk
            )
            | _canonical_node_mapping_q(
                relation="destination_place", locality_id=pickup_locality.pk
            )
            | Q(origin_place_id=pickup_locality.pk)
            | Q(destination_place_id=pickup_locality.pk)
        )
        delivery_node = JourneyLeg.objects.filter(journey_id=OuterRef("pk")).filter(
            _canonical_node_mapping_q(
                relation="origin_place", locality_id=delivery_locality.pk
            )
            | _canonical_node_mapping_q(
                relation="destination_place", locality_id=delivery_locality.pk
            )
            | Q(origin_place_id=delivery_locality.pk)
            | Q(destination_place_id=delivery_locality.pk)
        )
    else:
        pickup_location = delivery_request.pickup_location
        delivery_location = delivery_request.delivery_location
        pickup_node = JourneyLeg.objects.filter(journey_id=OuterRef("pk")).filter(
            Q(origin_id=pickup_location.pk)
            | Q(destination_id=pickup_location.pk)
            | Q(
                origin__airport_id=pickup_location.airport_id,
                origin__airport_id__isnull=False,
            )
            | Q(
                destination__airport_id=pickup_location.airport_id,
                destination__airport_id__isnull=False,
            )
        )
        delivery_node = JourneyLeg.objects.filter(journey_id=OuterRef("pk")).filter(
            Q(origin_id=delivery_location.pk)
            | Q(destination_id=delivery_location.pk)
            | Q(
                origin__airport_id=delivery_location.airport_id,
                origin__airport_id__isnull=False,
            )
            | Q(
                destination__airport_id=delivery_location.airport_id,
                destination__airport_id__isnull=False,
            )
        )
    from apps.trips.lifecycle import discoverable
    queryset = (
        discoverable(_matching_journey_queryset(at=at), at=at)
        .filter(
            traveler__is_active=True,
            traveler__is_banned=False,
            has_current_kyc_value=True,
        )
        .exclude(traveler_id=delivery_request.sender_id)
        .alias(has_overlapping_leg=Exists(overlapping_leg))
        .filter(has_overlapping_leg=True)
        .annotate(
            has_exact_pickup_node=Exists(pickup_node),
            has_exact_delivery_node=Exists(delivery_node),
        )
    )
    if delivery_request.target_traveler_id is not None:
        queryset = queryset.filter(traveler_id=delivery_request.target_traveler_id)
    queryset = queryset.order_by(
        "-has_exact_pickup_node",
        "-has_exact_delivery_node",
        "-published_at",
        "pk",
    )[: policy.candidate_scan_limit]
    evaluations = [
        evaluate_candidate(
            delivery_request=delivery_request,
            journey=journey,
            policy=policy,
            at=at,
            route_provider=route_provider,
        )
        for journey in queryset
    ]
    compatible = [row for row in evaluations if row.compatibility.compatible]
    compatible.sort(
        key=lambda row: (
            -(row.ranking or {}).get("score", 0),
            row.compatibility.added_distance_meters,
            row.compatibility.pickup_at,
            row.journey.pk,
        )
    )
    return compatible[: policy.result_limit]


def compatible_requests_for_journey(
    *,
    journey: Journey,
    policy: Phase2Policy,
    at=None,
) -> list[CandidateEvaluation]:
    at = at or timezone.now()
    journey = _matching_journey_queryset(at=at).get(pk=journey.pk)
    route_provider = get_route_provider(
        external_call_budget=settings.ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST
    )
    legs = list(journey._matching_legs)
    if not legs:
        return []
    first_departure = legs[0].depart_at
    # A pickup can occur inside the final DRIVE leg after that leg departs.
    # Use its arrival as the route coverage end; an open-ended leg conservatively
    # falls back to departure and is then decided by hard compatibility.
    coverage_end = legs[-1].arrive_at or legs[-1].depart_at
    canonical_journey = journey.schema_version >= 2
    if canonical_journey:
        route_nodes = [legs[0].origin_place, *[leg.destination_place for leg in legs]]
        route_localities = {
            locality_id
            for locality_id in (_matching_locality_id(place) for place in route_nodes)
            if locality_id is not None
        }
        node_ids = set()
        airport_ids = set()
    else:
        route_nodes = [legs[0].origin, *[leg.destination for leg in legs]]
        node_ids = {location.pk for location in route_nodes}
        airport_ids = {
            location.airport_id
            for location in route_nodes
            if location.airport_id is not None
        }
    active_deal = Deal.objects.filter(
        delivery_request_id=OuterRef("pk"),
        status__in=ACTIVE_DEAL_STATUSES,
    )
    queryset = (
        DeliveryRequest.objects.select_related(
            "sender",
            "pickup_location",
            "delivery_location",
        )
        .filter(
            schema_version=3 if canonical_journey else 2,
            status=ParcelRequest.Status.OPEN,
            sender__is_active=True,
            sender__is_banned=False,
            ready_window_start__lte=coverage_end,
            ready_window_end__gte=first_departure,
            deadline_at__gte=first_departure,
            # Dimensions are optional (Phase 8F-B). Filtering on them here
            # would have made every unmeasured request invisible to every
            # traveller — a posted request nobody can find is worse than the
            # bounce the rule was meant to prevent.
            actual_weight_kg__isnull=False,
        )
        .filter(
            Q(target_traveler__isnull=True) | Q(target_traveler_id=journey.traveler_id)
        )
        .exclude(sender_id=journey.traveler_id)
        .annotate(has_active_deal_value=Exists(active_deal))
        .filter(has_active_deal_value=False)
        .annotate(
            has_exact_pickup_node=Case(
                When(
                    _canonical_place_in_localities_q(
                        field="pickup_place", locality_ids=route_localities
                    )
                    if canonical_journey
                    else (
                        Q(pickup_location_id__in=node_ids)
                        | Q(pickup_location__airport_id__in=airport_ids)
                    ),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
            has_exact_delivery_node=Case(
                When(
                    _canonical_place_in_localities_q(
                        field="delivery_place", locality_ids=route_localities
                    )
                    if canonical_journey
                    else (
                        Q(delivery_location_id__in=node_ids)
                        | Q(delivery_location__airport_id__in=airport_ids)
                    ),
                    then=Value(1),
                ),
                default=Value(0),
                output_field=IntegerField(),
            ),
        )
        .order_by(
            "-has_exact_pickup_node",
            "-has_exact_delivery_node",
            "-created_at",
            "pk",
        )[: policy.candidate_scan_limit]
    )
    evaluations = [
        evaluate_candidate(
            delivery_request=delivery_request,
            journey=journey,
            policy=policy,
            at=at,
            route_provider=route_provider,
        )
        for delivery_request in queryset
    ]
    compatible = [row for row in evaluations if row.compatibility.compatible]
    compatible.sort(
        key=lambda row: (
            -(row.ranking or {}).get("score", 0),
            row.compatibility.added_distance_meters,
            row.delivery_request.created_at,
            row.delivery_request.pk,
        )
    )
    return compatible[: policy.result_limit]


def explain_candidate(*, delivery_request_id: int, journey_id: int, at=None):
    at = at or timezone.now()
    policy = phase2_policy()
    request = (
        DeliveryRequest.objects.select_related(
            "sender",
            "pickup_location",
            "delivery_location",
            "pickup_place",
            "delivery_place",
        )
        .annotate(
            has_active_deal_value=Exists(
                Deal.objects.filter(
                    delivery_request_id=OuterRef("pk"),
                    status__in=ACTIVE_DEAL_STATUSES,
                )
            )
        )
        .get(pk=delivery_request_id)
    )
    journey = _matching_journey_queryset(at=at).get(pk=journey_id)
    route_provider = get_route_provider(
        external_call_budget=settings.ROUTE_PROVIDER_MAX_EXTERNAL_CALLS_PER_MATCHING_REQUEST
    )
    return evaluate_candidate(
        delivery_request=request,
        journey=journey,
        policy=policy,
        at=at,
        route_provider=route_provider,
    )
