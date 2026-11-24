from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from math import ceil, floor, isclose

from django.db.models import Count, Sum
from django.utils import timezone

from apps.deals.models import Deal, DealLegAllocation
from apps.locations.city_names import city_name
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
from apps.trips.models import Journey, JourneyLeg, JourneyStopDetail
from apps.trips.proofs import journey_proof_gaps, leg_requires_proof
from apps.trips.services import has_current_kyc_approval
from apps.trips.transport_rules import sea_legs_enabled, unavailable_sea_legs

from .policy import Phase2Policy
from .public_contract import (
    PUBLIC_LEG_SUMMARY_FIELDS,
    PUBLIC_LOCATION_SUMMARY_FIELDS,
)


MATCHING_VERSION = "v1-matching-2"
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
    """A covered leg's place as a pre-funding counterparty reads it.

    `display_label` is the public city name (`apps.locations.city_names`),
    not the catalogue label.
    """

    if place is None:
        return None
    locality_id = _matching_locality_id(place)
    return {
        "id": place.pk,
        "name": place.name,
        "display_label": city_name(place),
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


def _optional_leg_point(leg: JourneyLeg, *, origin: bool) -> GeoPoint | None:
    """A route endpoint from canonical Place or legacy Location, if it has one.

    Every launch-country catalogue city carries coordinates (the release-data
    test enforces it), so ``None`` here is a crash guard for a place outside
    that catalogue, never a normal route.
    """

    value = (leg.origin_place if origin else leg.destination_place) or (
        leg.origin if origin else leg.destination
    )
    if value is None or value.latitude is None or value.longitude is None:
        return None
    return GeoPoint(float(value.latitude), float(value.longitude))


def _leg_point(leg: JourneyLeg, *, origin: bool) -> GeoPoint:
    """A route endpoint the caller cannot do without (legacy detour routing)."""

    point = _optional_leg_point(leg, origin=origin)
    if point is None:
        raise ValueError("Journey endpoint has no trusted coordinates")
    return point


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


def request_volume_litres(delivery_request: DeliveryRequest) -> Decimal | None:
    """The parcel's volume from its dimensions, rounded up to the millilitre.

    None when the sender gave no dimensions, which is allowed (Phase 8F-B):
    such a parcel is then never refused for volume, and a leg that declares a
    volume reports the `volume_unverified` caveat instead (spec 5.5).
    """

    dimensions = (
        delivery_request.length_cm,
        delivery_request.width_cm,
        delivery_request.height_cm,
    )
    if any(value is None for value in dimensions):
        return None
    length, width, height = (Decimal(value) for value in dimensions)
    return (length * width * height / Decimal(1000)).quantize(
        Decimal("0.001"), rounding=ROUND_CEILING
    )


def _stop_details(journey: Journey) -> dict[int, JourneyStopDetail]:
    cached = getattr(journey, "_matching_stop_details", None)
    if cached is None:
        cached = {
            row.position: row
            for row in JourneyStopDetail.objects.filter(journey_id=journey.pk)
        }
        journey._matching_stop_details = cached
    return cached


def _stop_accepts_pickup(journey: Journey, legs: list[JourneyLeg], node: int) -> bool:
    """Whether the stop at route node ``node`` accepts a parcel being handed over."""

    if node >= len(legs):
        return False
    annotated = getattr(legs[node], "origin_accepts_pickup_value", None)
    if annotated is not None:
        return bool(annotated)
    detail = _stop_details(journey).get(node)
    return detail is None or detail.accepts_pickup


def _stop_accepts_dropoff(journey: Journey, legs: list[JourneyLeg], node: int) -> bool:
    """Whether the stop at route node ``node`` accepts a parcel being dropped off."""

    if node < 1:
        return False
    annotated = getattr(legs[node - 1], "destination_accepts_dropoff_value", None)
    if annotated is not None:
        return bool(annotated)
    detail = _stop_details(journey).get(node)
    return detail is None or detail.accepts_dropoff


@dataclass(frozen=True, slots=True)
class LegReservation:
    """What active allocations already hold on one leg."""

    weight_kg: Decimal
    volume_l: Decimal
    parcels: int


_NOTHING_RESERVED = LegReservation(Decimal("0"), Decimal("0"), 0)


def _annotated_reservation(leg: JourneyLeg) -> LegReservation:
    """The reservation a matching queryset annotated onto ``leg``."""

    def value(name: str, default):
        annotated = getattr(leg, name, None)
        return default if annotated is None else annotated

    return LegReservation(
        weight_kg=Decimal(value("reserved_capacity_value", Decimal("0"))),
        volume_l=Decimal(value("reserved_volume_value", Decimal("0"))),
        parcels=int(value("reserved_parcels_value", 0)),
    )


def leg_reservations(
    legs, *, at: datetime | None = None
) -> dict[int, LegReservation]:
    """What active allocations hold on each of ``legs``, in one query.

    The acceptance lock calls this after taking the leg locks, so it reads
    every allocation a competing acceptance committed before it.
    """

    leg_ids = [leg.pk for leg in legs]
    rows = (
        DealLegAllocation.objects.active(at=at)
        .filter(journey_leg_id__in=leg_ids)
        .values("journey_leg_id")
        .annotate(
            weight=Sum("allocated_weight_kg"),
            volume=Sum("allocated_volume_l"),
            parcels=Count("pk"),
        )
    )
    reserved = {leg_id: _NOTHING_RESERVED for leg_id in leg_ids}
    for row in rows:
        reserved[row["journey_leg_id"]] = LegReservation(
            weight_kg=row["weight"] or Decimal("0"),
            volume_l=Decimal(row["volume"] or 0),
            parcels=int(row["parcels"] or 0),
        )
    return reserved


def _reserved_on_unannotated_legs(
    legs: tuple[JourneyLeg, ...], *, at: datetime
) -> dict[int, LegReservation]:
    """Reservations for the legs no matching queryset annotated.

    The acceptance lock evaluates freshly locked legs, which carry no
    annotation, so the read happens inside its transaction after the locks.
    """

    unannotated = [leg for leg in legs if not hasattr(leg, "reserved_capacity_value")]
    if not unannotated:
        return {}
    return leg_reservations(unannotated, at=at)


def _node_index(anchor: RouteAnchor) -> int | None:
    """The stop an anchor sits on, or None for a legacy point along a leg."""

    if anchor.leg is not None:
        return None
    return int(round(anchor.position))


def _journey_sea_switch(journey: Journey) -> bool:
    """The "Sea legs" switch for this evaluation.

    A scan reads it once and attaches it to every candidate as
    ``sea_legs_enabled_value``; a single evaluation (offer creation,
    acceptance) reads it here, inside its own transaction.
    """

    annotated = getattr(journey, "sea_legs_enabled_value", None)
    if annotated is not None:
        return bool(annotated)
    return sea_legs_enabled()


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

        if leg.mode == JourneyLeg.Mode.SEA and leg.distance_meters is not None:
            # The crossing's great-circle distance, snapshotted when the leg
            # was written (spec 5.4): the same method as a flight leg.
            distance = int(leg.distance_meters)
            method = "great_circle_sea_crossing"
            covered_distance = round(distance * covered_fraction)
        elif leg.mode in (JourneyLeg.Mode.FLIGHT, JourneyLeg.Mode.SEA):
            origin_point = _optional_leg_point(leg, origin=True)
            destination_point = _optional_leg_point(leg, origin=False)
            if origin_point is None or destination_point is None:
                # Only reachable for a leg another gate already refuses
                # (`flight_coordinates_trusted`), so it never prices a match.
                distance = 0
                method = "canonical_place_floor"
            else:
                distance = haversine_meters(origin_point, destination_point)
                method = (
                    "great_circle_trusted_coordinates"
                    if leg.mode == JourneyLeg.Mode.FLIGHT
                    else "great_circle_sea_crossing"
                )
            covered_distance = round(distance * covered_fraction)
        elif not partial_start and not partial_end and leg.distance_meters is not None:
            distance = int(leg.distance_meters)
            method = "stored_routed_road_distance"
            covered_distance = distance
        else:
            carried_start = (
                _point(pickup_location)
                if partial_start and pickup_location
                else _optional_leg_point(leg, origin=True)
            )
            carried_end = (
                _point(delivery_location)
                if partial_end and delivery_location
                else _optional_leg_point(leg, origin=False)
            )
            if carried_start is None or carried_end is None:
                # Crash guard only: every launch-country city has
                # coordinates. A leg that still lacks a point prices at the
                # distance floor, as posting pricing does, rather than
                # failing the whole scan.
                distance = 0
                method = "canonical_place_floor"
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
    _sea_legs_enabled: bool | None = None,
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
    check("journey_active", journey.status in (Journey.Status.ACTIVE, Journey.Status.IN_PROGRESS))
    # Spec 5.7: a paused journey accepts no new offers, whoever paused it.
    check("journey_not_paused", journey.paused_at is None)
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
    # Spec 5.6. A request with no category (none can be posted since V1) is
    # never refused by category; fragility is an explicit sender declaration.
    refused_categories = set(journey.refused_categories or ())
    category_accepted = (
        not delivery_request.category
        or delivery_request.category not in refused_categories
    )
    fragile_accepted = journey.accepts_fragile or not delivery_request.fragile
    check(
        "item_accepted_by_traveler",
        category_accepted and fragile_accepted,
        category_accepted=category_accepted,
        fragile_accepted=fragile_accepted,
    )
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
            if _sea_legs_enabled is None and any(
                leg.mode == JourneyLeg.Mode.SEA for leg in legs
            ):
                _sea_legs_enabled = _journey_sea_switch(journey)
            for pair in sorted(ordered_pairs, key=pair_sort_key):
                result = evaluate_compatibility(
                    delivery_request=delivery_request,
                    journey=journey,
                    policy=policy,
                    at=at,
                    route_provider=provider,
                    _anchor_pair=pair,
                    _sea_legs_enabled=_sea_legs_enabled,
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
    # Spec 5.1: the parcel boards at a stop that accepts pickup and leaves at
    # one that accepts drop-off. A legacy anchor along a road leg is not a
    # stop and has no stop options.
    pickup_node = _node_index(pickup_anchor)
    delivery_node = _node_index(delivery_anchor)
    check(
        "stop_services_allow_handover",
        (pickup_node is None or _stop_accepts_pickup(journey, legs, pickup_node))
        and (
            delivery_node is None
            or _stop_accepts_dropoff(journey, legs, delivery_node)
        ),
        pickup_stop=pickup_node,
        dropoff_stop=delivery_node,
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
    # Spec 5.3: a deactivated crossing or the switch turned off blocks new
    # offers on every journey that uses it, not only on parcels that sail.
    journey_sea_legs = [leg for leg in legs if leg.mode == JourneyLeg.Mode.SEA]
    if journey_sea_legs and _sea_legs_enabled is None:
        _sea_legs_enabled = _journey_sea_switch(journey)
    unavailable_sea_leg_ids = [
        leg.pk for leg in unavailable_sea_legs(journey_sea_legs, enabled=_sea_legs_enabled)
    ]
    check(
        "sea_legs_available",
        not unavailable_sea_leg_ids,
        sea_leg_ids=[leg.pk for leg in journey_sea_legs],
        unavailable_sea_leg_ids=unavailable_sea_leg_ids,
    )
    # Ticket proof: whether a leg needs one, and whether that need is met, is
    # decided only by `apps.trips.proofs`. The gaps are reported under the
    # mode's own gate so a client can say which ticket is missing.
    proof_legs = [leg for leg in legs if leg_requires_proof(leg)]
    gap_ids = {leg.pk for leg in journey_proof_gaps(proof_legs)}
    journey_flight_legs = [
        leg for leg in proof_legs if leg.mode == JourneyLeg.Mode.FLIGHT
    ]
    check(
        "flight_proofs_approved",
        not any(leg.pk in gap_ids for leg in journey_flight_legs),
        flight_leg_ids=[leg.pk for leg in journey_flight_legs],
    )
    check(
        "sea_proofs_approved",
        not any(leg.pk in gap_ids for leg in journey_sea_legs),
        sea_leg_ids=[leg.pk for leg in journey_sea_legs],
    )
    covered_flight_legs = [
        leg for leg in covered_legs if leg.mode == JourneyLeg.Mode.FLIGHT
    ]
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
    reserved_by_leg = _reserved_on_unannotated_legs(covered_legs, at=at)
    capacity_rows: list[dict] = []
    capacity_ok = delivery_request.actual_weight_kg is not None
    volume_ok = True
    parcels_ok = True
    volume_unverified = False
    request_weight = Decimal(delivery_request.actual_weight_kg or 0)
    request_volume = request_volume_litres(delivery_request)
    for leg in covered_legs:
        reserved = (
            reserved_by_leg[leg.pk]
            if leg.pk in reserved_by_leg
            else _annotated_reservation(leg)
        )
        remaining = Decimal(leg.capacity_kg) - reserved.weight_kg
        row = {
            "journey_leg_id": leg.pk,
            "capacity_kg": str(leg.capacity_kg),
            "reserved_kg": str(reserved.weight_kg),
            "remaining_kg": str(remaining),
        }
        capacity_ok = capacity_ok and remaining >= request_weight
        if leg.capacity_volume_l is not None:
            remaining_volume = Decimal(leg.capacity_volume_l) - reserved.volume_l
            row["capacity_volume_l"] = leg.capacity_volume_l
            row["reserved_volume_l"] = str(reserved.volume_l)
            if request_volume is None:
                volume_unverified = True
            else:
                volume_ok = volume_ok and remaining_volume >= request_volume
        if leg.capacity_parcels is not None:
            row["capacity_parcels"] = leg.capacity_parcels
            row["reserved_parcels"] = reserved.parcels
            parcels_ok = parcels_ok and reserved.parcels < leg.capacity_parcels
        capacity_rows.append(row)
    check(
        "capacity_available_on_every_leg",
        capacity_ok,
        covered_leg_ids=leg_ids,
        request_weight_kg=str(request_weight),
    )
    check(
        "volume_available_on_every_leg",
        volume_ok,
        covered_leg_ids=leg_ids,
        request_volume_l=str(request_volume) if request_volume is not None else None,
    )
    check(
        "parcel_slots_available_on_every_leg",
        parcels_ok,
        covered_leg_ids=leg_ids,
    )
    if volume_unverified:
        limitations.append("volume_unverified")

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
