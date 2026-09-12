"""The funded route, projected for a Deal party.

The sender has paid a traveler to carry a parcel along a route and, until I1A,
could not see it. This module answers that: the ordered legs that actually carry
*this* parcel, their transport mode, their canonical endpoints and their
scheduled times.

Three boundaries define it.

**Only this Deal's legs.** The traveler's Journey may carry several parcels over
several segments. The projection is built from `DealLegAllocation` -- the legs
this Deal's capacity is reserved on -- so it discloses the route the sender's
parcel takes and not the traveler's itinerary.

**Only after funding.** Before funding there is no funded route and the
pre-funding privacy ladder in `apps.matching.public_contract` governs what a
counterparty may see. This returns `None` until `funded_at` exists.

**Identifiers, places and times only.** No polyline, no route metadata, no
airport metadata, no proof, no measured distance or duration, no capacity and no
sight of the traveler's other allocations. `apps.trips.serializers` withholds
exactly that set from a non-owner and this projection is built from the frozen
snapshot rather than by relaxing that serializer.

Canonical `Place` rows are a public catalogue, so their labels are safe. Legacy
version-1 journeys have no Places, only user-owned `Location` rows; those are
projected at their **coarse** public label, never the private one, because a
leg endpoint is the traveler's own meeting detail and is not part of what
funding unlocks to the sender.
"""

from __future__ import annotations

from .arrival import parse_instant
from .models import Deal

BASIS_FUNDED_SNAPSHOT = "funded_snapshot"
BASIS_LIVE_JOURNEY = "live_journey"


def funded_route(*, deal: Deal, viewer_id: int | None, is_staff: bool = False):
    """The ordered carrying route, or `None` when it must not be shown.

    Served from `Deal.arrival_snapshot["route"]`, which was frozen inside the
    funding transaction. That is what makes the sender's view historically
    accurate: it is the route the money was taken against, not whatever the
    Journey rows say today.

    A Deal funded before I1A has no route snapshot. It falls back to the live
    allocated legs, and says so in `basis`, so a client is never told a live read
    is a frozen one.
    """

    if viewer_id not in (deal.sender_id, deal.traveler_id) and not is_staff:
        return None
    if deal.funded_at is None:
        return None

    frozen = (deal.arrival_snapshot or {}).get("route")
    if isinstance(frozen, list) and frozen:
        legs = [row for row in frozen if isinstance(row, dict)]
        legs.sort(key=lambda row: (row.get("position", 0), row.get("leg_id", 0)))
        return {
            "basis": BASIS_FUNDED_SNAPSHOT,
            "journey_id": deal.journey_id,
            "legs": [_snapshot_leg(row, deal) for row in legs],
        }
    return _live_route(deal)


def _live_route(deal: Deal) -> dict:
    allocations = sorted(
        deal.leg_allocations.all(),
        key=lambda row: (row.journey_leg.position, row.journey_leg_id),
    )
    return {
        "basis": BASIS_LIVE_JOURNEY,
        "journey_id": deal.journey_id,
        "legs": [_live_leg(row.journey_leg) for row in allocations],
    }


def _snapshot_leg(row: dict, deal: Deal) -> dict:
    depart = row.get("depart_at")
    arrive = row.get("arrive_at")
    return {
        "leg_id": row.get("leg_id"),
        "position": row.get("position"),
        "mode": row.get("mode"),
        "origin": _endpoint(
            place_id=row.get("origin_place_id"),
            location_id=row.get("origin_location_id"),
            deal=deal,
        ),
        "destination": _endpoint(
            place_id=row.get("destination_place_id"),
            location_id=row.get("destination_location_id"),
            deal=deal,
        ),
        "depart_at": parse_instant(depart) if isinstance(depart, str) else None,
        "arrive_at": parse_instant(arrive) if isinstance(arrive, str) else None,
        "carries_parcel": True,
    }


def _live_leg(leg) -> dict:
    return {
        "leg_id": leg.pk,
        "position": int(leg.position),
        "mode": leg.mode,
        "origin": _place_summary(leg.origin_place) or _location_summary(leg.origin),
        "destination": (
            _place_summary(leg.destination_place) or _location_summary(leg.destination)
        ),
        "depart_at": leg.depart_at,
        "arrive_at": leg.arrive_at,
        "carries_parcel": True,
    }


def _endpoint(*, place_id, location_id, deal: Deal):
    """Resolve one frozen endpoint id to a display summary.

    The snapshot stores identities, not labels. A `Place` identity is immutable
    and its display label is not, so resolving the label at read time is the
    correct direction: the sender sees the current name of the same place rather
    than a label that was correct months ago.
    """

    cache = _resolver_cache(deal)
    if place_id is not None:
        return cache["places"].get(place_id)
    if location_id is not None:
        return cache["locations"].get(location_id)
    return None


def _resolver_cache(deal: Deal) -> dict:
    """One query for places and one for locations, per Deal, per request."""

    cached = getattr(deal, "_i1a_route_endpoints", None)
    if cached is not None:
        return cached
    from apps.locations.models import Location, Place

    place_ids: set[int] = set()
    location_ids: set[int] = set()
    for row in (deal.arrival_snapshot or {}).get("route") or []:
        if not isinstance(row, dict):
            continue
        for key, sink in (
            ("origin_place_id", place_ids),
            ("destination_place_id", place_ids),
            ("origin_location_id", location_ids),
            ("destination_location_id", location_ids),
        ):
            value = row.get(key)
            if isinstance(value, int):
                sink.add(value)
    places = {
        place.pk: _place_summary(place)
        for place in Place.objects.filter(pk__in=place_ids).select_related("parent")
    }
    locations = {
        row.pk: _location_summary(row)
        for row in Location.objects.filter(pk__in=location_ids)
    }
    cached = {"places": places, "locations": locations}
    deal._i1a_route_endpoints = cached  # noqa: SLF001 - per-instance read cache
    return cached


def _place_summary(place) -> dict | None:
    if place is None:
        return None
    return {
        "kind": "place",
        "id": place.pk,
        "name": place.name,
        "display_label": place.display_label,
        "place_type": place.place_type,
        "iata_code": place.iata_code or None,
        "country_code": place.country_id,
        "parent_name": place.parent.name if place.parent_id and place.parent else None,
    }


def _location_summary(location) -> dict | None:
    """Legacy version-1 endpoints, at coarse precision only."""

    if location is None:
        return None
    return {
        "kind": "coarse_location",
        "id": location.pk,
        "name": location.public_label or location.city,
        "display_label": location.public_label or location.city,
        "place_type": "",
        "iata_code": None,
        "country_code": location.country_code,
        "parent_name": None,
    }
