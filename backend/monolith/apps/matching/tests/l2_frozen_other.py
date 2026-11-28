"""Frozen copies of the other functions L2 changes, at main `8205544`.

From `apps/matching/discovery.py` (`evaluate_candidate` wired to the frozen
compatibility, and the two scans), `apps/matching/posting_pricing.py`
(`estimate_request_route`), `apps/trips/services.py` (`_validate_leg_sequence`)
and `apps/trips/lifecycle.py` (`with_lifecycle`, `discoverable`). Compared with
the live code by `test_l2_matching_unchanged.py`; L2 deletes both in its last
commit.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import (
    Case,
    CharField,
    Exists,
    IntegerField,
    OuterRef,
    Q,
    Value,
    When,
)
from django.utils import timezone

from apps.accounts.blocks import not_blocked_with
from apps.deals.models import Deal
from apps.locations.models import AirportLocalityMapping, Place
from apps.matching.discovery import (
    CandidateEvaluation,
    _adopt_leg_place_mappings,
    _attach_sea_switch,
    _canonical_node_mapping_q,
    _canonical_place_in_localities_q,
    _load_endpoint_mappings,
    _matching_journey_queryset,
    _place_matching_prefetches,
)
from apps.matching.listed_price import listed_reward
from apps.matching.policy import Phase2Policy
from apps.matching.pricing import PricingError, calculate_pricing_quote
from apps.matching.posting_pricing import RouteEstimate
from apps.matching.ranking import rank_compatible_candidate
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.providers import RouteProvider, get_route_provider
from apps.trips.constraints import (
    DEPARTURE_NOT_FUTURE_CODE,
    DEPARTURE_NOT_FUTURE_MESSAGE,
    first_departure_is_future,
)
from apps.trips.models import Journey, JourneyLeg
from apps.trips.pricing import traveler_pricing_policy
from apps.trips.services import JourneyDomainError, validate_leg_times
from apps.trips.transport_rules import (
    MODE_UNAVAILABLE_CODE,
    check_leg_mode,
    mode_violation_message,
)

from .l2_frozen_compatibility import (
    ACTIVE_DEAL_STATUSES,
    _matching_locality_id,
    evaluate_compatibility,
)


# -- apps/matching/discovery.py ----------------------------------------------


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
    listed = None
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
        if journey.has_price:
            # The switch comes from the revision that priced this match, so a
            # listed price never mixes two revisions. Parsed, not queried.
            listed = listed_reward(
                journey,
                pricing,
                enabled=traveler_pricing_policy(policy.settings_version) is not None,
            )
    return CandidateEvaluation(
        delivery_request=delivery_request,
        journey=journey,
        compatibility=compatibility,
        pricing=pricing,
        ranking=ranking,
        listed=listed,
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
        .filter(not_blocked_with(delivery_request.sender_id, "traveler_id"))
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
    journeys = list(queryset)
    for journey in journeys:
        _adopt_leg_place_mappings(journey)
    _load_endpoint_mappings(journeys)
    _attach_sea_switch(journeys)
    evaluations = [
        evaluate_candidate(
            delivery_request=delivery_request,
            journey=journey,
            policy=policy,
            at=at,
            route_provider=route_provider,
        )
        for journey in journeys
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
    _attach_sea_switch([journey])
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
        # K7-E: the places (with parents and served mappings) are read for
        # every candidate by compatibility and by the request block.
        DeliveryRequest.objects.select_related(
            "sender",
            "pickup_location",
            "delivery_location",
            "pickup_place__parent",
            "delivery_place__parent",
        )
        .prefetch_related(*_place_matching_prefetches("pickup_place", "delivery_place"))
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
        .filter(not_blocked_with(journey.traveler_id, "sender_id"))
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


# -- apps/matching/posting_pricing.py ----------------------------------------


def estimate_request_route(delivery_request) -> RouteEstimate:
    """Great-circle distance between the request's own endpoints.

    Schema version 3 requests carry canonical places; version 2 carries
    `Location` rows. Every launch-country catalogue city carries coordinates
    (the release-data test enforces it); a preferred pin is optional
    operational data, never a pricing identity. An endpoint without
    coordinates is a crash guard only: the distance is zero, which lands the
    estimate on the global pricing floor rather than leaving a sender unable
    to post at all.
    """

    if getattr(delivery_request, "schema_version", 2) >= 3:
        pickup = delivery_request.pickup_place
        dropoff = delivery_request.delivery_place
        method = "posting_estimate:canonical_place_great_circle"
    else:
        pickup = delivery_request.pickup_location
        dropoff = delivery_request.delivery_location
        method = "posting_estimate:great_circle"
    if pickup is None or dropoff is None:
        raise PricingError("A V1 delivery request needs both route endpoints.")

    if (
        pickup.latitude is not None
        and pickup.longitude is not None
        and dropoff.latitude is not None
        and dropoff.longitude is not None
    ):
        from apps.routing.geometry import GeoPoint, haversine_meters

        meters = int(
            haversine_meters(
                GeoPoint(float(pickup.latitude), float(pickup.longitude)),
                GeoPoint(float(dropoff.latitude), float(dropoff.longitude)),
            )
        )
        return RouteEstimate(distance_meters=max(0, meters), method=method)
    return RouteEstimate(
        distance_meters=0, method="posting_estimate:canonical_place_floor"
    )


# -- apps/trips/services.py --------------------------------------------------


def _validate_leg_sequence(
    journey: Journey, legs: list[JourneyLeg], *, at=None
) -> None:
    if not legs:
        raise JourneyDomainError(
            "journey_has_no_legs",
            "A journey must contain at least one leg before publication.",
        )

    positions = [leg.position for leg in legs]
    if positions != list(range(len(legs))):
        raise JourneyDomainError(
            "journey_leg_positions_invalid",
            "Journey leg positions must be contiguous and start at zero.",
        )

    if not first_departure_is_future(legs[0].depart_at, at=at):
        raise JourneyDomainError(
            DEPARTURE_NOT_FUTURE_CODE,
            DEPARTURE_NOT_FUTURE_MESSAGE,
        )

    canonical = journey.schema_version >= 2

    def matching_place_id(place: Place | None) -> int | None:
        if place is None:
            return None
        if place.place_type == Place.PlaceType.LOCALITY:
            return place.pk
        mapping = place.airport_mappings.filter(
            active=True,
            is_primary=True,
            relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
            locality__active=True,
        ).first()
        return mapping.locality_id if mapping else None

    if canonical:
        if matching_place_id(legs[0].origin_place) != matching_place_id(
            journey.start_place
        ) or matching_place_id(legs[-1].destination_place) != matching_place_id(
            journey.destination_place
        ):
            raise JourneyDomainError(
                "journey_endpoints_mismatch",
                "Journey endpoints must match the first and last leg.",
            )
    elif (
        legs[0].origin_id != journey.start_location_id
        or legs[-1].destination_id != journey.destination_location_id
    ):
        raise JourneyDomainError(
            "journey_endpoints_mismatch",
            "Journey endpoints must match the first and last leg.",
        )

    for index, leg in enumerate(legs):
        if canonical:
            origin_node = matching_place_id(leg.origin_place)
            destination_node = matching_place_id(leg.destination_place)
        else:
            origin_node = leg.origin_id
            destination_node = leg.destination_id
        if (
            origin_node is None
            or destination_node is None
            or origin_node == destination_node
        ):
            raise JourneyDomainError(
                "journey_leg_endpoints_invalid",
                f"Leg {leg.position} origin and destination must differ.",
            )
        # A leg can become impossible after it was written: the catalogue can
        # move a place between countries, and a legacy row predates the rule
        # entirely.  Publication is the last gate before senders see it, so
        # the check runs again here rather than being trusted from write time.
        violation = check_leg_mode(
            position=leg.position,
            mode=leg.mode,
            origin=leg.origin_place,
            destination=leg.destination_place,
        )
        if violation is not None:
            raise JourneyDomainError(
                MODE_UNAVAILABLE_CODE,
                mode_violation_message(violation),
            )
        if index == 0:
            continue

        previous = legs[index - 1]
        if canonical:
            previous_node = matching_place_id(previous.destination_place)
            current_node = matching_place_id(leg.origin_place)
        else:
            previous_node = previous.destination_id
            current_node = leg.origin_id
        if (
            previous_node is None
            or current_node is None
            or previous_node != current_node
        ):
            raise JourneyDomainError(
                "journey_legs_disconnected",
                "Each leg must begin where the previous leg ends.",
            )
    validate_leg_times(legs)


# -- apps/trips/lifecycle.py -------------------------------------------------


def with_lifecycle(queryset, *, at=None):
    from apps.deals.activity import activity_q
    from apps.deals.models import Deal

    at = at or timezone.now()
    legs = JourneyLeg.objects.filter(journey_id=OuterRef("pk"))
    deals = Deal.objects.filter(journey_id=OuterRef("pk"), funded_at__isnull=False)
    return queryset.alias(
        remaining_inventory=Exists(legs.filter(
            Q(depart_at__gt=at)
            # Legacy DRIVE matching permits pickup along a leg. Canonical V2
            # matching uses departure nodes; do not reinterpret either model.
            | Q(journey__schema_version=1, mode="DRIVE", arrive_at__gt=at)
        )),
        travel_begun=Exists(deals.filter(pickup_confirmed_at__isnull=False)),
        funded_dependency=Exists(deals.filter(activity_q("active"))),
        unfinished_leg=Exists(legs.filter(Q(arrive_at__isnull=True) | Q(arrive_at__gt=at))),
        any_leg=Exists(legs),
    ).annotate(lifecycle_status=Case(
        When(~Q(status__in=[Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS]), then="status"),
        When(Q(status=Journey.Status.IN_PROGRESS) | Q(travel_begun=True), then=Case(
            When(any_leg=True, unfinished_leg=False, then=Value(Journey.Status.COMPLETED)),
            default=Value(Journey.Status.IN_PROGRESS),
        )),
        When(remaining_inventory=False, funded_dependency=False, then=Value(Journey.Status.EXPIRED)),
        default="status", output_field=CharField(),
    ))


def discoverable(queryset, *, at=None):
    """Journeys a member may find and offer on right now.

    A paused journey is not discoverable (spec 5.7), whoever paused it; this
    is the one filter every scan, listing and the Matches tier shares.
    """

    return with_lifecycle(queryset, at=at).filter(
        lifecycle_status__in=[Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS],
        remaining_inventory=True,
        paused_at__isnull=True,
    )
