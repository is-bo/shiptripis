"""Staff management of sea crossings (spec 5.3, plan L3A).

Every change names a reason and writes one audit row, exactly as every other
staff action does. There is deliberately no generic "edit": a crossing's two
ports are its identity, and a correction is a new crossing plus deactivating
the wrong one, which keeps the audit trail readable.

Deactivating a crossing blocks new sea legs and new offers on every journey
that uses it, from the next request on (`apps.trips.transport_rules` and the
`sea_legs_available` matching check read the row at the moment of action). It
never touches a funded deal, because nothing here or there reads a crossing
after funding.

The console's "Sea crossings" screens (`apps.admin_panel.console_sea`) call these.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q

from apps.locations.geography import normalize_search_name
from apps.routing.geometry import GeoPoint, haversine_meters

from .models import Place, SeaCrossing

#: Crossings are geography configuration, which staff manage under Settings.
MANAGE_CROSSINGS_PERMISSION = "manage_settings"

@dataclass(frozen=True)
class SeaCrossingError(Exception):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


def _require_permission(actor) -> None:
    from apps.admin_panel.permissions import has_admin_permission

    if not has_admin_permission(actor, MANAGE_CROSSINGS_PERMISSION):
        raise PermissionDenied("Managing sea crossings requires manage_settings.")


def _clean_reason(reason: str) -> str:
    cleaned = (reason or "").strip()
    if not cleaned:
        raise SeaCrossingError(
            "sea_crossing_reason_required", "A reason is required for this change."
        )
    return cleaned


def _state(crossing: SeaCrossing) -> dict:
    return {
        "origin_locality_id": crossing.origin_locality_id,
        "destination_locality_id": crossing.destination_locality_id,
        "distance_meters": crossing.distance_meters,
        "is_active": crossing.is_active,
    }


def great_circle_meters(origin: Place, destination: Place) -> int | None:
    """Catalogue great-circle distance, or None when a city has no coordinates.

    The same haversine function a flight leg uses (spec 5.4).
    """

    if None in (
        origin.latitude,
        origin.longitude,
        destination.latitude,
        destination.longitude,
    ):
        return None
    return haversine_meters(
        GeoPoint(float(origin.latitude), float(origin.longitude)),
        GeoPoint(float(destination.latitude), float(destination.longitude)),
    )


def resolve_port(country: str, name: str) -> tuple[Place | None, str]:
    """The one active catalogue city called ``name`` in ``country``, or why not.

    Matches the city's name or a source-backed alternate name. Never guesses:
    no match and more than one match both answer ``None`` with a reason. The
    seed command and the console's "Add a crossing" form share this, so staff
    and the reviewed list resolve a port the same way.
    """

    normalized = normalize_search_name(name)
    candidates = list(
        Place.objects.filter(
            country_id=country,
            place_type=Place.PlaceType.LOCALITY,
            active=True,
        )
        .filter(
            Q(normalized_name=normalized)
            | Q(
                alternate_name_records__normalized_name=normalized,
                alternate_name_records__active=True,
            )
        )
        .distinct()
        .order_by("pk")[:2]
    )
    if not candidates:
        return None, "no active catalogue city has this name"
    if len(candidates) > 1:
        return None, "more than one active catalogue city has this name"
    return candidates[0], ""


def _port(place_id: int, field: str) -> Place:
    place = Place.objects.filter(pk=place_id).first()
    if (
        place is None
        or not place.active
        or place.place_type != Place.PlaceType.LOCALITY
    ):
        raise SeaCrossingError(
            "sea_crossing_port_invalid",
            f"The {field} must be an active catalogue city.",
        )
    return place


@transaction.atomic
def create_crossing(
    *,
    actor,
    origin_locality_id: int,
    destination_locality_id: int,
    reason: str,
    active: bool = False,
) -> SeaCrossing:
    """Add one direction of a ferry line.

    The distance is the great-circle distance between the two cities'
    catalogue coordinates, which every launch-country city has. A city
    without them is refused rather than given a distance from anywhere else.
    """

    _require_permission(actor)
    cleaned = _clean_reason(reason)
    origin = _port(origin_locality_id, "origin")
    destination = _port(destination_locality_id, "destination")
    if origin.pk == destination.pk:
        raise SeaCrossingError(
            "sea_crossing_ports_identical", "A crossing joins two different ports."
        )
    distance = great_circle_meters(origin, destination)
    if distance is None:
        raise SeaCrossingError(
            "sea_crossing_coordinates_missing",
            "One of these cities has no catalogue coordinates, so the crossing "
            "has no distance.",
        )
    try:
        with transaction.atomic():
            crossing = SeaCrossing.objects.create(
                origin_locality=origin,
                destination_locality=destination,
                distance_meters=distance,
                is_active=active,
            )
    except IntegrityError as exc:
        raise SeaCrossingError(
            "sea_crossing_exists", "This crossing already exists in this direction."
        ) from exc

    from apps.admin_panel.services import record_admin_action

    record_admin_action(
        actor=actor,
        action="sea_crossing.created",
        target=crossing,
        before={},
        after=_state(crossing),
        reason=cleaned,
    )
    return crossing


def _set_active(*, actor, crossing_id: int, reason: str, active: bool) -> SeaCrossing:
    _require_permission(actor)
    cleaned = _clean_reason(reason)
    crossing = (
        SeaCrossing.objects.select_for_update(no_key=True)
        .filter(pk=crossing_id)
        .first()
    )
    if crossing is None:
        raise SeaCrossingError("sea_crossing_not_found", "No such sea crossing.")
    if crossing.is_active == active:
        return crossing
    before = _state(crossing)
    crossing.is_active = active
    crossing.save(update_fields=["is_active", "updated_at"])

    from apps.admin_panel.services import record_admin_action

    record_admin_action(
        actor=actor,
        action="sea_crossing.activated" if active else "sea_crossing.deactivated",
        target=crossing,
        before=before,
        after=_state(crossing),
        reason=cleaned,
    )
    return crossing


@transaction.atomic
def activate_crossing(*, actor, crossing_id: int, reason: str) -> SeaCrossing:
    return _set_active(actor=actor, crossing_id=crossing_id, reason=reason, active=True)


@transaction.atomic
def deactivate_crossing(*, actor, crossing_id: int, reason: str) -> SeaCrossing:
    return _set_active(
        actor=actor, crossing_id=crossing_id, reason=reason, active=False
    )
