from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_CEILING, Decimal
from math import ceil, floor

from django.db.models import Count, Sum
from django.utils import timezone

from apps.deals.models import Deal, DealLegAllocation
from apps.locations.models import AirportLocalityMapping, Location, Place
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.routing.geometry import GeoPoint, haversine_meters
from apps.routing.providers import RouteProvider, RouteProviderError, get_route_provider
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


def _optional_leg_point(leg: JourneyLeg, *, origin: bool) -> GeoPoint | None:
    """A route endpoint's catalogue place, if it has coordinates.

    Every launch-country catalogue city carries coordinates (the release-data
    test enforces it), so ``None`` here is a crash guard for a place outside
    that catalogue, never a normal route.
    """

    value = leg.origin_place if origin else leg.destination_place
    if value is None or value.latitude is None or value.longitude is None:
        return None
    return GeoPoint(float(value.latitude), float(value.longitude))


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


def _canonical_candidate_anchors(place: Place, legs: list[JourneyLeg]) -> list[float]:
    """The stops (route node indices) at the place's matching locality.

    Preferred pins are intentionally absent from this function: they are an
    operational handoff detail and never alter V1 compatibility.
    """

    locality_id = _matching_locality_id(place)
    if locality_id is None:
        return []
    nodes = [legs[0].origin_place, *[leg.destination_place for leg in legs]]
    return [
        float(index)
        for index, node in enumerate(nodes)
        if _matching_locality_id(node) == locality_id
    ]


def _time_at_position(
    position: float,
    legs: list[JourneyLeg],
    *,
    pickup: bool,
) -> datetime | None:
    node = int(round(position))
    if pickup:
        return legs[node].depart_at if node < len(legs) else None
    return legs[node - 1].arrive_at if node > 0 else None


def _route_distance(
    *,
    legs: list[JourneyLeg],
    pickup_position: float,
    delivery_position: float,
    provider: RouteProvider,
) -> tuple[int, str, tuple[dict, ...], list[str]]:
    """Measure only the route on which the parcel is actually carried.

    The approach before pickup and the return after drop-off do not carry the
    parcel, so only the legs between the two stops count.
    """

    components: list[dict] = []
    limitations: list[str] = []
    total = 0
    start_index = floor(pickup_position)
    end_index = ceil(delivery_position) - 1
    for index in range(start_index, end_index + 1):
        leg = legs[index]
        start_fraction = pickup_position - index if index == start_index else 0.0
        end_fraction = delivery_position - index if index == end_index else 1.0
        end_fraction = min(1.0, end_fraction)
        covered_fraction = max(0.0, end_fraction - start_fraction)

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
        elif leg.distance_meters is not None:
            distance = int(leg.distance_meters)
            method = "stored_routed_road_distance"
            covered_distance = distance
        else:
            carried_start = _optional_leg_point(leg, origin=True)
            carried_end = _optional_leg_point(leg, origin=False)
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
                    method = "provider_routed_road_distance"
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
                "partial_start": False,
                "partial_end": False,
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
    _anchor_pair: tuple[float, float] | None = None,
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

    check("request_active", delivery_request.status == ParcelRequest.Status.OPEN)
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
    geography_complete = (
        _matching_locality_id(delivery_request.pickup_place) is not None
        and _matching_locality_id(delivery_request.delivery_place) is not None
    )
    check("canonical_geography_complete", geography_complete)

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

    def refused() -> CompatibilityResult:
        return replace(
            empty,
            checks=tuple(checks),
            rejection_codes=tuple(dict.fromkeys(rejection_codes)),
        )

    # Reuse the same leg objects while evaluating alternate anchors so that
    # annotations and covered-leg identity remain stable without extra queries.
    journey._matching_legs = legs

    def pair_sort_key(pair: tuple[float, float]) -> tuple[float, float]:
        return (pair[1] - pair[0], pair[0])

    if _anchor_pair is None:
        if not geography_complete:
            # No route search can place this request on this journey: a
            # request city the catalogue cannot place (an airport whose served
            # mapping was retired, say). The failed
            # `canonical_geography_complete` is the whole answer: no stop is
            # reported missing and no order is claimed.
            return refused()
        pickup_anchors = _canonical_candidate_anchors(
            delivery_request.pickup_place, legs
        )
        delivery_anchors = _canonical_candidate_anchors(
            delivery_request.delivery_place, legs
        )
        ordered_pairs = [
            (pickup, delivery)
            for pickup in pickup_anchors
            for delivery in delivery_anchors
            if pickup + 1e-9 < delivery
        ]
        if not ordered_pairs:
            # A route that never visits a request city is a different failure
            # from one that visits both but has no pickup stop before a later
            # drop-off stop (it goes the other way, or both request places are
            # the same stop), and neither is a date problem. So each end has
            # its own gate, and `pickup_before_delivery` fails only when both
            # stops are there.
            check("pickup_stop_on_route", bool(pickup_anchors))
            check("delivery_stop_on_route", bool(delivery_anchors))
            if pickup_anchors and delivery_anchors:
                check(
                    "pickup_before_delivery",
                    False,
                    pickup_positions=sorted(pickup_anchors),
                    delivery_positions=sorted(delivery_anchors),
                )
            return refused()
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
        pickup_position, delivery_position = ordered_pairs[0]
    else:
        pickup_position, delivery_position = _anchor_pair
    check("pickup_stop_on_route", True)
    check("delivery_stop_on_route", True)
    check(
        "pickup_before_delivery",
        True,
        pickup_position=pickup_position,
        delivery_position=delivery_position,
    )
    # Spec 5.1: the parcel boards at a stop that accepts pickup and leaves at
    # one that accepts drop-off.
    pickup_node = int(round(pickup_position))
    delivery_node = int(round(delivery_position))
    check(
        "stop_services_allow_handover",
        _stop_accepts_pickup(journey, legs, pickup_node)
        and _stop_accepts_dropoff(journey, legs, delivery_node),
        pickup_stop=pickup_node,
        dropoff_stop=delivery_node,
    )

    # The parcel joins and leaves the route at stops, so it adds no detour.
    pickup_detour = 0
    delivery_detour = 0
    added_distance = 0
    added_duration = 0
    check("pickup_detour_within_limit", True, actual_meters=0)
    check("delivery_detour_within_limit", True, actual_meters=0)
    check("total_added_distance_within_limit", True, actual_meters=0)
    check("total_added_duration_within_limit", True, actual_seconds=0, available=True)
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
    check(
        "total_added_duration_within_limit",
        added_duration <= policy.max_total_added_duration_seconds,
        actual_seconds=added_duration,
        limit_seconds=policy.max_total_added_duration_seconds,
        available=True,
    )

    start_index = floor(pickup_position)
    end_index = ceil(delivery_position) - 1
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
    check(
        "flight_coordinates_trusted",
        trusted_flight_coordinates,
        flight_leg_ids=[leg.pk for leg in covered_flight_legs],
    )
    pickup_at = _time_at_position(pickup_position, legs, pickup=True)
    delivery_at = _time_at_position(delivery_position, legs, pickup=False)
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
            pickup_position=pickup_position,
            delivery_position=delivery_position,
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
        pickup_position=pickup_position,
        delivery_position=delivery_position,
        pickup_at=pickup_at,
        delivery_at=delivery_at,
        pickup_added_duration_seconds=0,
        pickup_detour_meters=pickup_detour,
        delivery_detour_meters=delivery_detour,
        added_distance_meters=added_distance,
        added_duration_seconds=added_duration,
        matched_distance_meters=matched_distance,
        matched_distance_method=distance_method,
        distance_components=components,
        capacity_remaining_by_leg=tuple(capacity_rows),
        limitations=tuple(dict.fromkeys(limitations)),
        route_provider=None,
    )
