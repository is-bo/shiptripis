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

The console screens are L3B; these functions are what they will call.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from apps.routing.geometry import GeoPoint, haversine_meters

from .models import Place, SeaCrossing

#: Crossings are geography configuration, which staff manage under Settings.
MANAGE_CROSSINGS_PERMISSION = "manage_settings"

#: The longest line in the seeded list is about 760 km; nothing in the
#: Mediterranean is ten times that. The ceiling exists to catch a typo.
MAX_CROSSING_DISTANCE_KM = Decimal("5000")


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
    distance_km: Decimal | None = None,
) -> SeaCrossing:
    """Add one direction of a ferry line.

    The distance is the catalogue great-circle distance when both cities have
    coordinates. Most French and Spanish catalogue cities have none, so staff
    then give the distance in kilometres, measured the same way.
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
        if distance_km is None:
            raise SeaCrossingError(
                "sea_crossing_distance_required",
                "One of these cities has no catalogue coordinates; give the "
                "great-circle distance in kilometres.",
            )
        if not Decimal("0") < Decimal(distance_km) <= MAX_CROSSING_DISTANCE_KM:
            raise SeaCrossingError(
                "sea_crossing_distance_invalid",
                f"The distance must be above 0 and at most {MAX_CROSSING_DISTANCE_KM} km.",
            )
        distance = int(
            (Decimal(distance_km) * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
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
