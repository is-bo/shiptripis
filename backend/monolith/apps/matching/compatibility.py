from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil, floor, isclose

from django.db.models import Sum
from django.utils import timezone

from apps.deals.models import Deal, DealLegAllocation
from apps.locations.models import AirportLocalityMapping, Location, Place
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.geometry import (
    GeoPoint,
    haversine_meters,
    parse_corridor_points_with_fallback,
    project_to_corridor,
)
from apps.routing.providers import (
    RouteProvider,
    RouteProviderError,
    RouteProviderUnavailable,
    get_route_provider,
)
from apps.trips.models import Journey, JourneyLeg, JourneyLegProof
from apps.trips.services import has_current_kyc_approval

from .policy import Phase2Policy
from .public_contract import (
    PUBLIC_LEG_SUMMARY_FIELDS,
    PUBLIC_LOCATION_SUMMARY_FIELDS,
)


MATCHING_VERSION = "v1-matching-1"
ACTIVE_DEAL_STATUSES = (
    Deal.Status.OFFER_ACCEPTED,
    Deal.Status.PAYMENT_REQUIRED,
    Deal.Status.FUNDED,
    Deal.Status.PICKUP_READY,
    Deal.Status.PICKED_UP,
    Deal.Status.IN_TRANSIT,
    Deal.Status.DELIVERY_READY,
    Deal.Status.DELIVERY_CONFIRMED,
    Deal.Status.PROTECTION_WINDOW,
    Deal.Status.DISPUTED,
)


@dataclass(frozen=True, slots=True)
class RouteAnchor:
    position: float
    detour_meters: int
    leg: JourneyLeg | None
    method: str
    projected_point: GeoPoint | None


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    compatible: bool
    rejection_codes: tuple[str, ...]
    checks: tuple[dict, ...]
    covered_legs: tuple[JourneyLeg, ...]
    pickup_position: float | None
    delivery_position: float | None
    pickup_at: datetime | None
    delivery_at: datetime | None
    pickup_added_duration_seconds: int | None
    pickup_detour_meters: int
    delivery_detour_meters: int
    added_distance_meters: int
    added_duration_seconds: int | None
    matched_distance_meters: int | None
    matched_distance_method: str
    distance_components: tuple[dict, ...]
    capacity_remaining_by_leg: tuple[dict, ...]
    limitations: tuple[str, ...]
    route_provider: str | None

    def as_dict(self) -> dict:
        """Internal/admin/audit representation.

        This is the form persisted on Match/Offer/Deal. It contains derived
        geometry that reconstructs an exact private address, so it is never
        serialized to a party — see `matching.public_contract`.
        """

        return {
            "matching_version": MATCHING_VERSION,
            "compatible": self.compatible,
            "rejection_codes": list(self.rejection_codes),
            "checks": list(self.checks),
            "covered_leg_ids": [leg.pk for leg in self.covered_legs],
            "covered_leg_positions": [leg.position for leg in self.covered_legs],
            "covered_legs": [_public_leg_summary(leg) for leg in self.covered_legs],
            "pickup_route_position": self.pickup_position,
            "delivery_route_position": self.delivery_position,
            "pickup_at": self.pickup_at.isoformat() if self.pickup_at else None,
            "delivery_at": self.delivery_at.isoformat() if self.delivery_at else None,
            "pickup_added_duration_seconds": self.pickup_added_duration_seconds,
            "pickup_detour_meters": self.pickup_detour_meters,
            "delivery_detour_meters": self.delivery_detour_meters,
            "estimated_added_distance_meters": self.added_distance_meters,
            "estimated_added_duration_seconds": self.added_duration_seconds,
            "matched_distance_meters": self.matched_distance_meters,
            "matched_distance_method": self.matched_distance_method,
            "distance_components": list(self.distance_components),
            "capacity_remaining_by_leg": list(self.capacity_remaining_by_leg),
            "limitations": list(self.limitations),
            "route_provider": self.route_provider,
        }


def _public_location_summary(location: Location) -> dict:
    """Build the JSON-safe public location mirror, driven by the allowlist.

    The candidate values are assembled first and then projected through
    `PUBLIC_LOCATION_SUMMARY_FIELDS`, so this builder and
    `public_contract.public_location_summary` cannot disagree about which keys
    are public.
    """

    values = {
        "id": location.pk,
        "kind": location.kind,
        "public_label": location.public_label,
        "city": location.city,
        "region": location.region,
        "country_code": location.country_code,
        "coarse_latitude": str(location.coarse_latitude),
        "coarse_longitude": str(location.coarse_longitude),
        "precision": location.precision,
        "coordinates_trusted": location.coordinates_trusted,
        "coordinate_dataset_version": location.coordinate_dataset_version,
        "airport": location.airport_id,
    }
    return {field: values[field] for field in PUBLIC_LOCATION_SUMMARY_FIELDS}


def _matching_locality_id(place: Place | None) -> int | None:
    """Resolve a selectable place to the immutable locality used for matching."""

    if place is None:
        return None
    if place.place_type == Place.PlaceType.LOCALITY:
        return place.pk if place.active else None
    cached = getattr(place, "_matching_locality_id_cache", None)
    if cached is not None:
        return cached or None
    prefetched = getattr(place, "_active_matching_mappings", None)
    if prefetched is not None:
        locality_id = prefetched[0].locality_id if prefetched else None
        place._matching_locality_id_cache = locality_id or 0
        return locality_id
    mapping = place.airport_mappings.filter(
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).first()
    locality_id = mapping.locality_id if mapping else None
    place._matching_locality_id_cache = locality_id or 0
    return locality_id


def _public_place_summary(place: Place | None) -> dict | None:
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


def _public_leg_summary(leg: JourneyLeg) -> dict:
    """Render one covered leg with only counterparty-visible fields.

    The published leg schedule is safe because it describes the Journey, not
    where on that Journey the parcel joins it. The interpolated pickup/delivery
    instants are position-derived and stay internal.
    """

    values = {
        "journey_leg_id": leg.pk,
        "position": leg.position,
        "mode": leg.mode,
        "origin": _public_location_summary(leg.origin) if leg.origin else None,
        "destination": _public_location_summary(leg.destination)
        if leg.destination
        else None,
        "origin_place": _public_place_summary(leg.origin_place),
        "destination_place": _public_place_summary(leg.destination_place),
        "depart_at": leg.depart_at.isoformat() if leg.depart_at else None,
        "arrive_at": leg.arrive_at.isoformat() if leg.arrive_at else None,
    }
    return {field: values[field] for field in PUBLIC_LEG_SUMMARY_FIELDS}


def _point(location: Location) -> GeoPoint:
    return GeoPoint(float(location.latitude), float(location.longitude))


def _leg_point(leg: JourneyLeg, *, origin: bool) -> GeoPoint:
    """Get a route endpoint from canonical Place or legacy Location."""

    value = (leg.origin_place if origin else leg.destination_place) or (
        leg.origin if origin else leg.destination
    )
    if value is None or value.latitude is None or value.longitude is None:
        raise ValueError("Journey endpoint has no trusted coordinates")
    return GeoPoint(float(value.latitude), float(value.longitude))


def _same_route_node(first: Location, second: Location) -> bool:
    if first.pk == second.pk:
        return True
    return bool(
        first.kind == Location.Kind.AIRPORT
        and second.kind == Location.Kind.AIRPORT
        and first.airport_id is not None
        and first.airport_id == second.airport_id
    )


def _journey_legs(journey: Journey) -> list[JourneyLeg]:
    prefetched = getattr(journey, "_matching_legs", None)
    if prefetched is not None:
        return list(prefetched)
    return list(
        JourneyLeg.objects.filter(journey=journey)
        .select_related("origin", "destination", "origin_place", "destination_place")
        .order_by("position", "pk")
    )


def _approved_flight_proof(leg: JourneyLeg) -> bool:
    annotated = getattr(leg, "has_approved_proof_value", None)
    if annotated is not None:
        return bool(annotated)
    return JourneyLegProof.objects.filter(
        leg=leg,
        status=JourneyLegProof.Status.APPROVED,
    ).exists()


def _kyc_is_current(journey: Journey, *, at: datetime) -> bool:
    annotated = getattr(journey, "has_current_kyc_value", None)
    if annotated is not None:
        return bool(annotated)
    return has_current_kyc_approval(journey.traveler, at=at)


def _has_active_deal(delivery_request: DeliveryRequest) -> bool:
    annotated = getattr(delivery_request, "has_active_deal_value", None)
    if annotated is not None:
        return bool(annotated)
    return delivery_request.deals.filter(status__in=ACTIVE_DEAL_STATUSES).exists()


def _candidate_anchors(
    location: Location,
    legs: list[JourneyLeg],
    *,
    provider: RouteProvider,
) -> list[RouteAnchor]:
    nodes = [legs[0].origin, *[leg.destination for leg in legs]]
    exact = [
        RouteAnchor(float(index), 0, None, "exact_node", None)
        for index, node in enumerate(nodes)
        if _same_route_node(node, location)
    ]
    if exact:
        return exact

    point = _point(location)
    anchors: list[RouteAnchor] = []
    for leg in legs:
        if leg.mode != JourneyLeg.Mode.DRIVE:
            continue
        raw_corridor = leg.route_metadata.get("corridor_points")
        method = "stored_route_corridor"
        if not raw_corridor:
            try:
                route = provider.directions(
                    [_point(leg.origin), _point(leg.destination)],
                    profile="drive",
                )
            except RouteProviderError:
                raw_corridor = None
                method = "spatial_fallback"
            else:
                raw_corridor = [point.as_pair() for point in route.corridor_points]
                method = "provider_route_corridor"
        corridor, used_fallback = parse_corridor_points_with_fallback(
            raw_corridor,
            fallback=(_point(leg.origin), _point(leg.destination)),
        )
        if used_fallback:
            method = "spatial_fallback"
        projection = project_to_corridor(point, corridor)
        anchors.append(
            RouteAnchor(
                position=leg.position + projection.progress,
                detour_meters=projection.distance_meters * 2,
                leg=leg,
                method=method,
                projected_point=projection.point,
            )
        )
    return anchors


def _canonical_candidate_anchors(
    place: Place, legs: list[JourneyLeg]
) -> list[RouteAnchor]:
    """Return node anchors for canonical locality identity only.

    Preferred pins are intentionally absent from this function: they are an
    operational handoff detail and never alter V1 compatibility.
    """

    locality_id = _matching_locality_id(place)
    if locality_id is None:
        return []
    nodes = [legs[0].origin_place, *[leg.destination_place for leg in legs]]
    return [
        RouteAnchor(float(index), 0, None, "canonical_locality", None)
        for index, node in enumerate(nodes)
        if _matching_locality_id(node) == locality_id
    ]


def _time_at_position(
    position: float,
    legs: list[JourneyLeg],
    *,
    pickup: bool,
) -> datetime | None:
    if isclose(position, round(position), abs_tol=1e-9):
        node = int(round(position))
        if pickup:
            return legs[node].depart_at if node < len(legs) else None
        return legs[node - 1].arrive_at if node > 0 else None
    leg = legs[floor(position)]
    if leg.arrive_at is None:
        return None
    fraction = Decimal(str(position - floor(position)))
    seconds = Decimal(str((leg.arrive_at - leg.depart_at).total_seconds()))
    return leg.depart_at + timedelta(seconds=float(seconds * fraction))


def _time_at_anchor(
    anchor: RouteAnchor,
    legs: list[JourneyLeg],
    *,
    pickup: bool,
) -> datetime | None:
    if anchor.leg is None:
        return _time_at_position(anchor.position, legs, pickup=pickup)
    leg = anchor.leg
    if leg.arrive_at is None:
        return None
    fraction = Decimal(str(max(0.0, min(1.0, anchor.position - leg.position))))
    seconds = Decimal(str((leg.arrive_at - leg.depart_at).total_seconds()))
    return leg.depart_at + timedelta(seconds=float(seconds * fraction))


def _pickup_precedes_delivery(
    pickup: RouteAnchor,
    delivery: RouteAnchor,
) -> bool:
    if pickup.position + 1e-9 < delivery.position:
        return True
    if not isclose(pickup.position, delivery.position, abs_tol=1e-9):
        return False
    if pickup.leg is not None and delivery.leg is not None:
        return pickup.leg.pk == delivery.leg.pk
    if pickup.leg is None and delivery.leg is not None:
        return isclose(delivery.position, delivery.leg.position, abs_tol=1e-9)
    if pickup.leg is not None and delivery.leg is None:
        return isclose(
            pickup.position,
            pickup.leg.position + 1,
            abs_tol=1e-9,
        )
    return False


def _route_distance(
    *,
    legs: list[JourneyLeg],
    pickup_anchor: RouteAnchor,
    delivery_anchor: RouteAnchor,
    pickup_location: Location | None,
    delivery_location: Location | None,
    provider: RouteProvider,
) -> tuple[int, str, tuple[dict, ...], list[str]]:
    """Measure only the route on which the parcel is actually carried.

    Whole-itinerary pickup/drop-off detours are feasibility and recommendation
    inputs. They are deliberately not added to the matched subroute distance:
    the approach before pickup and the return after drop-off do not carry the
    parcel. Partial DRIVE legs are therefore routed between the actual request
    endpoint and the covered leg endpoint (or directly endpoint-to-endpoint
    when both fall on the same leg).
    """

    components: list[dict] = []
    limitations: list[str] = []
    total = 0
    start_index = (
        pickup_anchor.leg.position
        if pickup_anchor.leg is not None
        else floor(pickup_anchor.position)
    )
    end_index = (
        delivery_anchor.leg.position
        if delivery_anchor.leg is not None
        else ceil(delivery_anchor.position) - 1
    )
    for index in range(start_index, end_index + 1):
        leg = legs[index]
        start_fraction = pickup_anchor.position - index if index == start_index else 0.0
        end_fraction = delivery_anchor.position - index if index == end_index else 1.0
        end_fraction = min(1.0, end_fraction)
        covered_fraction = max(0.0, end_fraction - start_fraction)

        partial_start = index == start_index and pickup_anchor.leg is leg
        partial_end = index == end_index and delivery_anchor.leg is leg
        carried_start = (
            _point(pickup_location)
            if partial_start and pickup_location
            else _leg_point(leg, origin=True)
        )
        carried_end = (
            _point(delivery_location)
            if partial_end and delivery_location
            else _leg_point(leg, origin=False)
        )

        if leg.mode == JourneyLeg.Mode.FLIGHT:
            distance = haversine_meters(
                _leg_point(leg, origin=True), _leg_point(leg, origin=False)
            )
            method = "great_circle_trusted_coordinates"
            covered_distance = round(distance * covered_fraction)
        elif not partial_start and not partial_end and leg.distance_meters is not None:
            distance = int(leg.distance_meters)
            method = "stored_routed_road_distance"
            covered_distance = distance
        else:
            try:
                route = provider.directions(
                    [carried_start, carried_end],
                    profile="drive",
                )
            except RouteProviderError:
                distance = haversine_meters(carried_start, carried_end)
                method = "straight_line_spatial_fallback"
                limitations.append(
                    f"leg_{leg.pk}_road_distance_unavailable_spatial_fallback_used"
                )
            else:
                distance = route.distance_meters
                method = (
                    "provider_routed_partial_road_distance"
                    if partial_start or partial_end
                    else "provider_routed_road_distance"
                )
            covered_distance = distance
        total += covered_distance
        components.append(
            {
                "journey_leg_id": leg.pk,
                "position": leg.position,
                "mode": leg.mode,
                "covered_fraction": f"{covered_fraction:.6f}",
                "distance_meters": covered_distance,
                "method": method,
                "partial_start": partial_start,
                "partial_end": partial_end,
            }
        )
    methods = sorted({component["method"] for component in components})
    method = methods[0] if len(methods) == 1 else f"mixed:{'+'.join(methods)}"
    return total, method, tuple(components), limitations


def evaluate_compatibility(
    *,
    delivery_request: DeliveryRequest,
    journey: Journey,
    policy: Phase2Policy,
    at: datetime | None = None,
    route_provider: RouteProvider | None = None,
    _anchor_pair: tuple[RouteAnchor, RouteAnchor] | None = None,
) -> CompatibilityResult:
    at = at or timezone.now()
    provider = route_provider or get_route_provider()
    checks: list[dict] = []
    rejection_codes: list[str] = []
    limitations: list[str] = []

    def check(code: str, passed: bool, **details) -> None:
        checks.append({"code": code, "passed": passed, "details": details})
        if not passed:
            rejection_codes.append(code)

    canonical_request = delivery_request.schema_version >= 3
    canonical_journey = journey.schema_version >= 2
    canonical_flow = canonical_request and canonical_journey
    request_active = (
        delivery_request.schema_version in (2, 3)
        and delivery_request.status == ParcelRequest.Status.OPEN
    )
    check("request_active", request_active)
    check("journey_active", journey.status == Journey.Status.ACTIVE)
    accounts_eligible = all(
        (
            delivery_request.sender.is_active,
            not delivery_request.sender.is_banned,
            journey.traveler.is_active,
            not journey.traveler.is_banned,
            delivery_request.sender_id != journey.traveler_id,
        )
    )
    check("accounts_eligible", accounts_eligible)
    check("traveler_kyc_current", _kyc_is_current(journey, at=at))

    legs = _journey_legs(journey)
    sequence_valid = bool(legs) and [leg.position for leg in legs] == list(
        range(len(legs))
    )
    if sequence_valid:
        if canonical_journey:
            sequence_valid = all(
                _matching_locality_id(first.destination_place) is not None
                and _matching_locality_id(first.destination_place)
                == _matching_locality_id(second.origin_place)
                for first, second in zip(legs, legs[1:], strict=False)
            )
            sequence_valid = sequence_valid and all(
                _matching_locality_id(leg.origin_place) is not None
                and _matching_locality_id(leg.destination_place) is not None
                for leg in legs
            )
        else:
            sequence_valid = all(
                first.destination_id == second.origin_id
                for first, second in zip(legs, legs[1:], strict=False)
            )
    check("journey_leg_sequence", sequence_valid)

    safety_fields = (
        delivery_request.description_is_accurate,
        delivery_request.item_is_legal,
        delivery_request.no_prohibited_goods,
        delivery_request.declared_value_is_accurate,
        delivery_request.customs_responsibilities_understood,
    )
    check("item_safety_eligible", all(safety_fields))
    # Dimensions are optional from Phase 8F-B and are therefore no longer a
    # pricing input a request can be missing: `calculate_pricing_quote` reads
    # an absent set as zero volumetric weight. Weight and deadline remain
    # required — without either there is no quote at all.
    pricing_inputs = (
        delivery_request.actual_weight_kg,
        delivery_request.deadline_at,
    )
    check("pricing_inputs_complete", all(value is not None for value in pricing_inputs))
    check(
        "target_traveler_eligible",
        delivery_request.target_traveler_id in (None, journey.traveler_id),
    )
    check("request_has_no_active_deal", not _has_active_deal(delivery_request))
    if canonical_request:
        check(
            "canonical_geography_complete",
            canonical_journey
            and _matching_locality_id(delivery_request.pickup_place) is not None
            and _matching_locality_id(delivery_request.delivery_place) is not None,
        )
    elif canonical_journey:
        check("canonical_geography_complete", False)

    empty = CompatibilityResult(
        compatible=False,
        rejection_codes=tuple(dict.fromkeys(rejection_codes)),
        checks=tuple(checks),
        covered_legs=(),
        pickup_position=None,
        delivery_position=None,
        pickup_at=None,
        delivery_at=None,
        pickup_added_duration_seconds=None,
        pickup_detour_meters=0,
        delivery_detour_meters=0,
        added_distance_meters=0,
        added_duration_seconds=None,
        matched_distance_meters=None,
        matched_distance_method="unavailable",
        distance_components=(),
        capacity_remaining_by_leg=(),
        limitations=(),
        route_provider=None,
    )
    if not sequence_valid:
        return empty

    # Reuse the same leg objects while evaluating alternate anchors so that
    # annotations and covered-leg identity remain stable without extra queries.
    journey._matching_legs = legs

    def pair_sort_key(
        pair: tuple[RouteAnchor, RouteAnchor],
    ) -> tuple[int, float, float]:
        return (
            pair[0].detour_meters + pair[1].detour_meters,
            pair[1].position - pair[0].position,
            pair[0].position,
        )

    if _anchor_pair is None:
        if canonical_flow:
            pickup_anchors = _canonical_candidate_anchors(
                delivery_request.pickup_place, legs
            )
            delivery_anchors = _canonical_candidate_anchors(
                delivery_request.delivery_place, legs
            )
        else:
            if (
                delivery_request.pickup_location is None
                or delivery_request.delivery_location is None
            ):
                check("canonical_geography_complete", False)
                return replace(
                    empty,
                    checks=tuple(checks),
                    rejection_codes=tuple(dict.fromkeys(rejection_codes)),
                )
            pickup_anchors = _candidate_anchors(
                delivery_request.pickup_location,
                legs,
                provider=provider,
            )
            delivery_anchors = _candidate_anchors(
                delivery_request.delivery_location,
                legs,
                provider=provider,
            )
        ordered_pairs = [
            (pickup, delivery)
            for pickup in pickup_anchors
            for delivery in delivery_anchors
            if _pickup_precedes_delivery(pickup, delivery)
        ]
        if not ordered_pairs:
            check("pickup_before_delivery", False)
            return replace(
                empty,
                checks=tuple(checks),
                rejection_codes=tuple(dict.fromkeys(rejection_codes)),
            )
        if len(ordered_pairs) > 1:
            rejected: list[CompatibilityResult] = []
            for pair in sorted(ordered_pairs, key=pair_sort_key):
                result = evaluate_compatibility(
                    delivery_request=delivery_request,
                    journey=journey,
                    policy=policy,
                    at=at,
                    route_provider=provider,
                    _anchor_pair=pair,
                )
                if result.compatible:
                    return result
                rejected.append(result)
            return min(
                rejected,
                key=lambda result: (
                    len(result.rejection_codes),
                    result.added_distance_meters,
                    (
                        result.delivery_position
                        if result.delivery_position is not None
                        else float("inf")
                    ),
                    (
                        result.pickup_position
                        if result.pickup_position is not None
                        else float("inf")
                    ),
                ),
            )
        pickup_anchor, delivery_anchor = ordered_pairs[0]
    else:
        pickup_anchor, delivery_anchor = _anchor_pair
    for kind, anchor in (
        ("pickup", pickup_anchor),
        ("delivery", delivery_anchor),
    ):
        if anchor.method == "spatial_fallback":
            limitations.append(f"{kind}_anchor_uses_straight_line_spatial_fallback")
    check(
        "pickup_before_delivery",
        True,
        pickup_position=pickup_anchor.position,
        delivery_position=delivery_anchor.position,
    )

    pickup_detour = 0 if canonical_flow else pickup_anchor.detour_meters
    delivery_detour = 0 if canonical_flow else delivery_anchor.detour_meters
    added_distance = pickup_detour + delivery_detour
    added_duration: int | None = None
    pickup_added_duration: int | None = None
    delivery_added_duration: int | None = None
    provider_name: str | None = None
    detour_anchors = [
        anchor for anchor in (pickup_anchor, delivery_anchor) if anchor.leg
    ]
    if canonical_flow:
        check("pickup_detour_within_limit", True, actual_meters=0)
        check("delivery_detour_within_limit", True, actual_meters=0)
        check("total_added_distance_within_limit", True, actual_meters=0)
        check(
            "total_added_duration_within_limit", True, actual_seconds=0, available=True
        )
        added_duration = 0
        pickup_added_duration = 0
        delivery_added_duration = 0
    elif detour_anchors:
        by_leg: dict[int, list[tuple[str, GeoPoint, RouteAnchor]]] = {}
        for kind, location, anchor in (
            ("pickup", delivery_request.pickup_location, pickup_anchor),
            ("delivery", delivery_request.delivery_location, delivery_anchor),
        ):
            if anchor.leg is not None:
                by_leg.setdefault(anchor.leg.pk, []).append(
                    (kind, _point(location), anchor)
                )
        try:
            provider_added_distance = 0
            provider_added_duration = 0
            has_duration = True
            individual: dict[str, int] = {}
            leg_added_duration: dict[int, int] = {}
            anchor_prefix_delay: dict[str, int] = {}
            for entries in sorted(
                by_leg.values(), key=lambda rows: rows[0][2].leg.position
            ):
                leg = entries[0][2].leg
                assert leg is not None
                ordered = sorted(entries, key=lambda item: item[2].position)
                baseline = provider.directions(
                    [_leg_point(leg, origin=True), _leg_point(leg, origin=False)],
                    profile="drive",
                )
                with_detour = provider.directions(
                    [
                        _point(leg.origin),
                        *[item[1] for item in ordered],
                        _point(leg.destination),
                    ],
                    profile="drive",
                )
                leg_distance = max(
                    0, with_detour.distance_meters - baseline.distance_meters
                )
                leg_duration = None
                if (
                    baseline.duration_seconds is not None
                    and with_detour.duration_seconds is not None
                ):
                    leg_duration = max(
                        0,
                        with_detour.duration_seconds - baseline.duration_seconds,
                    )
                provider_added_distance += leg_distance
                if leg_duration is None:
                    has_duration = False
                else:
                    provider_added_duration += leg_duration
                    leg_added_duration[leg.position] = leg_duration
                for anchor_index, (kind, point, anchor) in enumerate(ordered):
                    if len(ordered) == 1:
                        individual_distance = leg_distance
                    else:
                        individual_route = provider.directions(
                            [_point(leg.origin), point, _point(leg.destination)],
                            profile="drive",
                        )
                        individual_distance = max(
                            0,
                            individual_route.distance_meters - baseline.distance_meters,
                        )
                    individual[kind] = individual_distance
                    prefix = provider.directions(
                        [
                            _point(leg.origin),
                            *[item[1] for item in ordered[: anchor_index + 1]],
                        ],
                        profile="drive",
                    )
                    if (
                        prefix.duration_seconds is not None
                        and anchor.projected_point is not None
                    ):
                        route_fraction = anchor.position - leg.position
                        if isclose(route_fraction, 0.0, abs_tol=1e-9):
                            baseline_prefix_duration = 0
                        elif isclose(route_fraction, 1.0, abs_tol=1e-9):
                            baseline_prefix_duration = baseline.duration_seconds
                        else:
                            baseline_prefix = provider.directions(
                                [_point(leg.origin), anchor.projected_point],
                                profile="drive",
                            )
                            baseline_prefix_duration = baseline_prefix.duration_seconds
                        if baseline_prefix_duration is not None:
                            anchor_prefix_delay[kind] = max(
                                0,
                                prefix.duration_seconds - baseline_prefix_duration,
                            )
            pickup_detour = individual.get("pickup", 0)
            delivery_detour = individual.get("delivery", 0)
            added_distance = provider_added_distance
            added_duration = provider_added_duration if has_duration else None
            pickup_added_duration = sum(
                duration
                for position, duration in leg_added_duration.items()
                if position < floor(pickup_anchor.position)
            ) + anchor_prefix_delay.get("pickup", 0)
            delivery_added_duration = sum(
                duration
                for position, duration in leg_added_duration.items()
                if position < floor(delivery_anchor.position)
            ) + anchor_prefix_delay.get("delivery", 0)
            provider_name = provider.name
        except (RouteProviderUnavailable, RouteProviderError):
            if not policy.spatial_fallback_enabled:
                check("route_provider_available", False)
            limitations.append("drive_detour_uses_spatial_fallback_not_routed_delta")
    check(
        "pickup_detour_within_limit",
        pickup_detour <= policy.max_pickup_detour_meters,
        actual_meters=pickup_detour,
        limit_meters=policy.max_pickup_detour_meters,
    )
    check(
        "delivery_detour_within_limit",
        delivery_detour <= policy.max_dropoff_detour_meters,
        actual_meters=delivery_detour,
        limit_meters=policy.max_dropoff_detour_meters,
    )
    check(
        "total_added_distance_within_limit",
        added_distance <= policy.max_total_added_distance_meters,
        actual_meters=added_distance,
        limit_meters=policy.max_total_added_distance_meters,
    )
    duration_ok = (
        added_duration is None
        or added_duration <= policy.max_total_added_duration_seconds
    )
    check(
        "total_added_duration_within_limit",
        duration_ok,
        actual_seconds=added_duration,
        limit_seconds=policy.max_total_added_duration_seconds,
        available=added_duration is not None,
    )

    start_index = (
        pickup_anchor.leg.position
        if pickup_anchor.leg is not None
        else floor(pickup_anchor.position)
    )
    end_index = (
        delivery_anchor.leg.position
        if delivery_anchor.leg is not None
        else ceil(delivery_anchor.position) - 1
    )
    covered_legs = tuple(legs[start_index : end_index + 1])
    journey_flight_legs = [leg for leg in legs if leg.mode == JourneyLeg.Mode.FLIGHT]
    covered_flight_legs = [
        leg for leg in covered_legs if leg.mode == JourneyLeg.Mode.FLIGHT
    ]
    flight_proofs_ok = all(_approved_flight_proof(leg) for leg in journey_flight_legs)
    check(
        "flight_proofs_approved",
        flight_proofs_ok,
        flight_leg_ids=[leg.pk for leg in journey_flight_legs],
    )
    if canonical_flow:
        trusted_flight_coordinates = all(
            leg.origin_place is not None
            and leg.origin_place.place_type == Place.PlaceType.AIRPORT
            and leg.origin_place.latitude is not None
            and leg.origin_place.longitude is not None
            and leg.destination_place is not None
            and leg.destination_place.place_type == Place.PlaceType.AIRPORT
            and leg.destination_place.latitude is not None
            and leg.destination_place.longitude is not None
            for leg in covered_flight_legs
        )
    else:
        trusted_flight_coordinates = all(
            leg.origin is not None
            and leg.origin.kind == Location.Kind.AIRPORT
            and leg.origin.coordinates_trusted
            and leg.destination is not None
            and leg.destination.kind == Location.Kind.AIRPORT
            and leg.destination.coordinates_trusted
            for leg in covered_flight_legs
        )
    check(
        "flight_coordinates_trusted",
        trusted_flight_coordinates,
        flight_leg_ids=[leg.pk for leg in covered_flight_legs],
    )
    pickup_at = _time_at_anchor(pickup_anchor, legs, pickup=True)
    delivery_at = _time_at_anchor(delivery_anchor, legs, pickup=False)
    if pickup_at is not None and pickup_added_duration is not None:
        pickup_at += timedelta(seconds=pickup_added_duration)
    if delivery_at is not None and delivery_added_duration is not None:
        delivery_at += timedelta(seconds=delivery_added_duration)
    temporal_order = (
        pickup_at is not None
        and delivery_at is not None
        and pickup_at < delivery_at
        and pickup_at > at
    )
    check("route_time_order_feasible", temporal_order)
    pickup_window_ok = bool(
        pickup_at
        and delivery_request.ready_window_start
        and delivery_request.ready_window_end
        and delivery_request.ready_window_start
        <= pickup_at
        <= delivery_request.ready_window_end
    )
    check("pickup_within_ready_window", pickup_window_ok)
    deadline_ok = bool(
        delivery_at
        and delivery_request.deadline_at
        and delivery_at <= delivery_request.deadline_at
    )
    check("delivery_before_deadline", deadline_ok)

    leg_ids = [leg.pk for leg in covered_legs]
    unannotated_ids = [
        leg.pk for leg in covered_legs if not hasattr(leg, "reserved_capacity_value")
    ]
    reserved_by_leg = {}
    if unannotated_ids:
        reserved_by_leg = dict(
            DealLegAllocation.objects.active(at=at)
            .filter(journey_leg_id__in=unannotated_ids)
            .values("journey_leg_id")
            .annotate(total=Sum("allocated_weight_kg"))
            .values_list("journey_leg_id", "total")
        )
    capacity_rows: list[dict] = []
    capacity_ok = delivery_request.actual_weight_kg is not None
    request_weight = Decimal(delivery_request.actual_weight_kg or 0)
    for leg in covered_legs:
        reserved = getattr(leg, "reserved_capacity_value", None)
        if reserved is None:
            reserved = reserved_by_leg.get(leg.pk) or Decimal("0")
        remaining = Decimal(leg.capacity_kg) - Decimal(reserved)
        capacity_rows.append(
            {
                "journey_leg_id": leg.pk,
                "capacity_kg": str(leg.capacity_kg),
                "reserved_kg": str(reserved),
                "remaining_kg": str(remaining),
            }
        )
        capacity_ok = capacity_ok and remaining >= request_weight
    check(
        "capacity_available_on_every_leg",
        capacity_ok,
        covered_leg_ids=leg_ids,
        request_weight_kg=str(request_weight),
    )

    matched_distance, distance_method, components, distance_limitations = (
        _route_distance(
            legs=legs,
            pickup_anchor=pickup_anchor,
            delivery_anchor=delivery_anchor,
            pickup_location=delivery_request.pickup_location,
            delivery_location=delivery_request.delivery_location,
            provider=provider,
        )
    )
    limitations.extend(distance_limitations)
    if distance_limitations and not policy.spatial_fallback_enabled:
        check(
            "route_provider_available",
            False,
            reason="road_distance_requires_provider",
        )
    compatible = not rejection_codes
    return CompatibilityResult(
        compatible=compatible,
        rejection_codes=tuple(dict.fromkeys(rejection_codes)),
        checks=tuple(checks),
        covered_legs=covered_legs,
        pickup_position=pickup_anchor.position,
        delivery_position=delivery_anchor.position,
        pickup_at=pickup_at,
        delivery_at=delivery_at,
        pickup_added_duration_seconds=pickup_added_duration,
        pickup_detour_meters=pickup_detour,
        delivery_detour_meters=delivery_detour,
        added_distance_meters=added_distance,
        added_duration_seconds=added_duration,
        matched_distance_meters=matched_distance,
        matched_distance_method=distance_method,
        distance_components=components,
        capacity_remaining_by_leg=tuple(capacity_rows),
        limitations=tuple(dict.fromkeys(limitations)),
        route_provider=provider_name,
    )
