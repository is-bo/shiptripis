"""The Listings tier: published trips and open requests, strictly public.

Two rules shape every function here.

**Listed means sellable now.** A trip is listed only while the matching engine
itself could still offer on it: the lifecycle says it is active, unpaused and
has inventory ahead (`trips.lifecycle.discoverable`), the traveler is an
active, unbanned member with a current ID check, every ticket the journey
needs is approved (`trips.proofs`), every sea leg's crossing is open and the
switch is on, and every leg still ahead has room by weight, volume and parcel
slots. A request is listed only while it is open,
untargeted, unexpired, inside its ready window and free of any active Deal,
the same scope `compatible_requests_for_journey` scans. Listing a row the
engine would refuse is the failure this module exists to prevent.

**Cards are allowlists.** `trip_card` and `request_card` build their payload
key by key from spec 4.2. A field that is not written here cannot be
published here, and `tests/test_privacy.py` walks every payload for the keys
and strings that must never appear.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from django.db.models import (
    Count,
    DecimalField,
    Exists,
    F,
    IntegerField,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from apps.deals.models import Deal, DealLegAllocation
from apps.matching.compatibility import ACTIVE_DEAL_STATUSES
from apps.matching.discovery import _matching_journey_queryset, _place_matching_prefetches
from apps.matching.find_travelers import first_name, project_route
from apps.parcels.models import DeliveryRequest, ParcelRequest
from apps.trips.lifecycle import discoverable
from apps.trips.models import Journey, JourneyLeg
from apps.trips.pricing import JourneyPrice
from apps.trips.proofs import proof_gap_exists
from apps.trips.transport_rules import sea_crossing_active_exists

from .places import locality_block

#: Default and largest page of a listing. Five cards fill Home's section; a
#: full browse screen pages twenty at a time.
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 50

#: Remaining-capacity bands on a trip card. The exact free weight discloses
#: the traveler's other bookings (`apps.matching.public_contract`), so a card
#: publishes which band the smallest free weight still ahead falls in.
CAPACITY_UNDER_5KG = "under_5kg"
CAPACITY_5_TO_10KG = "5_to_10kg"
CAPACITY_10_TO_20KG = "10_to_20kg"
CAPACITY_20KG_PLUS = "20kg_plus"
CAPACITY_BANDS: tuple[str, ...] = (
    CAPACITY_UNDER_5KG,
    CAPACITY_5_TO_10KG,
    CAPACITY_10_TO_20KG,
    CAPACITY_20KG_PLUS,
)

_DECIMAL = DecimalField(max_digits=10, decimal_places=3)


@dataclass(frozen=True, slots=True)
class RouteFilter:
    """Where a listing must go, as catalogue rows and country codes.

    `origin_place_ids` / `destination_place_ids` are already expanded with
    `places.place_ids_for_locality`, so a filter on a city matches the city and
    every airport that serves it.
    """

    origin_place_ids: frozenset[int] | None = None
    destination_place_ids: frozenset[int] | None = None
    origin_country: str | None = None
    destination_country: str | None = None

    @property
    def has_origin(self) -> bool:
        return self.origin_place_ids is not None or self.origin_country is not None

    @property
    def has_destination(self) -> bool:
        return (
            self.destination_place_ids is not None
            or self.destination_country is not None
        )


def _end_q(field: str, place_ids: frozenset[int] | None, country: str | None) -> Q:
    condition = Q()
    if place_ids is not None:
        condition &= Q(**{f"{field}_id__in": place_ids})
    if country is not None:
        condition &= Q(**{f"{field}__country_id": country})
    return condition


def journey_route_exists(
    route: RouteFilter, *, journey_ref: str = "pk", departing_after: datetime | None
) -> Q:
    """True when the journey picks up at the origin and later reaches the destination.

    A stop is a leg endpoint, so "from A to B" means some leg departs from A
    and that leg or a later one arrives at B. That is the node order canonical
    matching requires; a journey that only passes B before A is not "A to B".
    With `departing_after`, the pickup leg must still be ahead, because a stop
    the traveler has already left cannot take a parcel.
    """

    if not route.has_origin and not route.has_destination:
        return Q()
    origin = _end_q("origin_place", route.origin_place_ids, route.origin_country)
    destination = _end_q(
        "destination_place", route.destination_place_ids, route.destination_country
    )
    legs = JourneyLeg.objects.filter(journey_id=OuterRef(journey_ref))
    if departing_after is not None:
        legs = legs.filter(depart_at__gt=departing_after)
    if not route.has_origin:
        return Q(Exists(legs.filter(destination)))
    if not route.has_destination:
        return Q(Exists(legs.filter(origin)))
    later = JourneyLeg.objects.filter(
        journey_id=OuterRef("journey_id"), position__gte=OuterRef("position")
    ).filter(destination)
    return Q(Exists(legs.filter(origin).filter(Exists(later))))


def request_route_q(route: RouteFilter) -> Q:
    return _end_q("pickup_place", route.origin_place_ids, route.origin_country) & _end_q(
        "delivery_place", route.destination_place_ids, route.destination_country
    )


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------


def listable_journeys(*, at: datetime, sea_legs_enabled: bool) -> QuerySet:
    """Every journey a member may browse right now, with its card's rows loaded.

    The leg prefetch is matching's own (`_matching_journey_queryset`): it brings
    each stop's served mapping and the reserved weight per leg, so projecting a
    card reads nothing more.

    ``sea_legs_enabled`` is the "Sea legs" switch the caller read from its own
    `marketplace_policy()` at the moment of the request. With it off, no
    journey with a sea leg is listed; with it on, one is listed only while
    every crossing it uses is active (spec 5.3).
    """

    active_allocations = (
        DealLegAllocation.objects.active(at=at)
        .filter(journey_leg_id=OuterRef("pk"))
        .values("journey_leg_id")
    )
    reserved = active_allocations.annotate(total=Sum("allocated_weight_kg")).values(
        "total"
    )[:1]
    reserved_volume = active_allocations.annotate(
        total=Sum("allocated_volume_l")
    ).values("total")[:1]
    reserved_parcels = active_allocations.annotate(total=Count("pk")).values(
        "total"
    )[:1]
    full_leg_ahead = (
        JourneyLeg.objects.filter(journey_id=OuterRef("pk"), depart_at__gt=at)
        .annotate(
            reserved_weight=Coalesce(
                Subquery(reserved, output_field=_DECIMAL),
                Value(Decimal("0.000")),
                output_field=_DECIMAL,
            ),
            reserved_volume=Coalesce(
                Subquery(reserved_volume, output_field=_DECIMAL),
                Value(Decimal("0.000")),
                output_field=_DECIMAL,
            ),
            reserved_parcels=Coalesce(
                Subquery(reserved_parcels, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
        )
        .filter(
            Q(capacity_kg__lte=F("reserved_weight"))
            | Q(capacity_volume_l__isnull=False, capacity_volume_l__lte=F("reserved_volume"))
            | Q(capacity_parcels__isnull=False, capacity_parcels__lte=F("reserved_parcels"))
        )
    )
    sea_legs = JourneyLeg.objects.filter(
        journey_id=OuterRef("pk"), mode=JourneyLeg.Mode.SEA
    )
    if sea_legs_enabled:
        sea_legs = sea_legs.alias(open=sea_crossing_active_exists()).filter(open=False)
    next_departure = (
        JourneyLeg.objects.filter(journey_id=OuterRef("pk"), depart_at__gt=at)
        .order_by("depart_at", "pk")
        .values("depart_at")[:1]
    )
    return (
        discoverable(_matching_journey_queryset(at=at), at=at)
        .filter(
            schema_version__gte=2,
            traveler__is_active=True,
            traveler__is_banned=False,
            has_current_kyc_value=True,
        )
        .alias(
            proof_gap=proof_gap_exists(),
            unavailable_sea_leg=Exists(sea_legs),
            full_leg_ahead=Exists(full_leg_ahead),
        )
        .filter(proof_gap=False, unavailable_sea_leg=False, full_leg_ahead=False)
        .annotate(next_departure=Subquery(next_departure))
        .filter(next_departure__isnull=False)
    )


def capacity_band(free_kg: Decimal) -> str:
    if free_kg < 5:
        return CAPACITY_UNDER_5KG
    if free_kg < 10:
        return CAPACITY_5_TO_10KG
    if free_kg < 20:
        return CAPACITY_10_TO_20KG
    return CAPACITY_20KG_PLUS


def _isoformat(value) -> str | None:
    return value.isoformat() if value is not None else None


def trip_card(
    journey: Journey, *, trust: dict, at: datetime, pricing_enabled: bool
) -> dict:
    """Spec 4.2 trip card. Every key is written here, and nothing else ships.

    Stops are cities (`locality_block`), never an airport name, a street or a
    coordinate. The traveler appears by first name with the same trust summary
    Find Travelers shows for them, so the two screens can never disagree.

    `price` is the traveler's own price per kg and minimum (L4A), never a
    listed reward: a card is not about one parcel. It is null when the journey
    has none or traveler pricing is off (``pricing_enabled``, read by the
    caller from the same revision as its other switches).
    """

    legs = list(journey._matching_legs)
    route = project_route(
        legs,
        journey_leg_count=len(legs),
        first_covered_position=0 if legs else None,
        last_covered_position=len(legs) - 1 if legs else None,
    )
    ahead = [leg for leg in legs if leg.depart_at > at]
    smallest_free = min(
        (Decimal(leg.capacity_kg) - leg.reserved_capacity_value for leg in ahead),
        default=Decimal("0"),
    )
    return {
        "journey_id": journey.pk,
        "traveler": {
            "display_name": first_name(journey.traveler.full_name),
            # A listed trip has passed the current-ID gate; see the queryset.
            "identity_verified": True,
            "rating": trust["rating"],
            "completed_deliveries": trust["completed_deliveries"],
        },
        "stops": [
            {
                "place_id": stop["place_id"],
                "label": stop["label"],
                "country_code": stop["country_code"],
            }
            for stop in route["stops"]
        ],
        "legs": [
            {
                "mode": segment["mode"],
                "depart_at": segment["depart_at"],
                "arrive_at": segment["arrive_at"],
            }
            for segment in route["segments"]
        ],
        "departs_at": _isoformat(legs[0].depart_at) if legs else None,
        "next_departure_at": _isoformat(ahead[0].depart_at) if ahead else None,
        "arrives_at": _isoformat(legs[-1].arrive_at) if legs else None,
        "capacity_band": capacity_band(smallest_free),
        "price": (
            JourneyPrice.of(journey).as_public_dict() if pricing_enabled else None
        ),
    }


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


def listable_requests(*, at: datetime) -> QuerySet:
    """Every open request a traveler may browse right now, card rows loaded."""

    active_deal = Deal.objects.filter(
        delivery_request_id=OuterRef("pk"), status__in=ACTIVE_DEAL_STATUSES
    )
    return (
        DeliveryRequest.objects.select_related(
            "sender", "pickup_place__parent", "delivery_place__parent"
        )
        .prefetch_related(*_place_matching_prefetches("pickup_place", "delivery_place"))
        .filter(
            kind=ParcelRequest.Kind.DELIVERY,
            schema_version=3,
            status=ParcelRequest.Status.OPEN,
            target_traveler__isnull=True,
            sender__is_active=True,
            sender__is_banned=False,
            deadline_at__gt=at,
            ready_window_end__gt=at,
            actual_weight_kg__isnull=False,
        )
        .alias(has_active_deal=Exists(active_deal))
        .filter(has_active_deal=False)
    )


def request_card(delivery_request: DeliveryRequest) -> dict:
    """Spec 4.2 request card. Never the recipient, the address or a dimension."""

    reward = int(delivery_request.traveler_reward_eur_cents or 0)
    boost = int(delivery_request.boost_eur_cents or 0)
    return {
        "request_id": delivery_request.pk,
        "sender": {"display_name": first_name(delivery_request.sender.full_name)},
        "pickup": locality_block(delivery_request.pickup_place),
        "delivery": locality_block(delivery_request.delivery_place),
        "title": delivery_request.title,
        "category": delivery_request.category,
        "fragile": bool(delivery_request.fragile),
        "weight_kg": str(delivery_request.actual_weight_kg),
        "ready_window_start": _isoformat(delivery_request.ready_window_start),
        "ready_window_end": _isoformat(delivery_request.ready_window_end),
        "deadline_at": _isoformat(delivery_request.deadline_at),
        "currency": "EUR",
        "traveler_reward_eur_cents": reward,
        "boost_eur_cents": boost,
        "total_offered_reward_eur_cents": reward + boost,
    }


def window(queryset: QuerySet, *, limit: int, offset: int) -> tuple[list, int | None]:
    """One page and the offset of the next, read as `limit + 1` rows.

    No COUNT: a listing never needs the total, only whether there is more.
    """

    rows = list(queryset[offset : offset + limit + 1])
    has_more = len(rows) > limit
    return rows[:limit], (offset + limit) if has_more else None
