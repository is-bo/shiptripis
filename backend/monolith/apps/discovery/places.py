"""Catalogue identity for discovery: the same locality identity matching uses.

A discovery filter, a usual route and a route alert all name a *city*. An
airport is a facet of the city it serves (spec 5.1 and the J1.2 route UX), so
an airport id given by a client is resolved to its matching locality with
`Place.resolve_matching_locality()`, and a filter matches every catalogue row
that resolves to that locality: the locality itself and each airport whose
active primary served mapping points at it. That is exactly the node identity
`apps.matching.discovery` matches on (`_canonical_node_mapping_q`), so a city
filter can never disagree with the match the same city would produce.
"""

from __future__ import annotations

from apps.locations.city_names import city_name
from apps.locations.models import AirportLocalityMapping, Place


class PlaceNotFound(ValueError):
    code = "place_not_found"


def resolve_locality(place_id: int) -> Place:
    """The active matching locality behind ``place_id``, or `PlaceNotFound`."""

    place = (
        Place.objects.select_related("parent")
        .prefetch_related("airport_mappings__locality__parent")
        .filter(pk=place_id, active=True)
        .first()
    )
    locality = place.resolve_matching_locality() if place is not None else None
    if locality is None:
        raise PlaceNotFound("No active catalogue city matches this place.")
    return locality


def place_ids_for_locality(locality_id: int) -> frozenset[int]:
    """Every catalogue row that resolves to this locality, for a SQL filter.

    One query. The mapping filter mirrors `_canonical_node_mapping_q` key for
    key, so the two cannot drift apart silently.
    """

    airports = AirportLocalityMapping.objects.filter(
        locality_id=locality_id,
        active=True,
        is_primary=True,
        relationship_type=AirportLocalityMapping.RelationshipType.SERVED,
        locality__active=True,
    ).values_list("airport_id", flat=True)
    return frozenset({locality_id, *airports})


def locality_block(place: Place | None) -> dict | None:
    """A city as discovery publishes it: catalogue id, label and country.

    The label is the public city name (`apps.locations.city_names`), never
    the catalogue's `"<name> · <parent>"` label, coordinates, a street or the
    airport's own name. The caller passes a place whose served mapping and
    parent are already loaded, so this reads no row.
    """

    locality = place.resolve_matching_locality() if place is not None else None
    if locality is None:
        return None
    return {
        "place_id": locality.pk,
        "label": city_name(locality),
        "country_code": locality.country_id,
    }
