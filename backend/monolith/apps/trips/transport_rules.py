"""Which transport modes are physically possible on a Journey leg.

There are three modes: FLIGHT, DRIVE and SEA (spec 5.2). The catalogue serves
four countries, and not every pair of them is reachable by road: Algeria is
separated from the European corridor by the Mediterranean. A traveller who
declares a DRIVE leg from Jijel to Marseille is describing a journey nobody
can make, and every downstream promise built on it — capacity, timing, a
sender's delivery window — is false.

So a leg's *availability* is derived from geography rather than trusted from
the client:

* Two places on the same road network may be joined by DRIVE.
* Any two places may be joined by FLIGHT; the airport endpoints and flight
  number a flight needs are checked by the write serializer, because they are
  flight facts rather than geography.
* Two port cities may be joined by SEA only while the "Sea legs" switch is on
  and an *active* `locations.SeaCrossing` joins them in that direction, both
  ports still being active catalogue cities.

The road networks are declared, not inferred. Algeria is its own network;
France, Spain and Germany share the continental European one. A country the
catalogue serves but this table does not name is treated as its own isolated
network, which fails closed: an unknown pair cannot drive across an ocean.

Port cities are ordinary catalogue localities (spec 5.3): a sea endpoint must
be a LOCALITY place, resolved through `Place.resolve_matching_locality()` like
every other endpoint, and a "port city" is any locality that is an endpoint of
a crossing, active or not.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.db.models import Exists, OuterRef

from apps.locations.models import Place, SeaCrossing

logger = logging.getLogger("apps.trips")

# Road networks reachable without leaving the ground.  Keys are ISO 3166-1
# alpha-2 codes, exactly as `locations.Country.code` stores them.
ROAD_NETWORK_BY_COUNTRY: dict[str, str] = {
    "DZ": "dz-maghreb",
    "FR": "eu-continental-west",
    "ES": "eu-continental-west",
    "DE": "eu-continental-west",
}

# A country with no declared network is its own island.  Prefixing keeps a
# future real network named "unknown" from colliding with it.
_ISOLATED_PREFIX = "isolated:"

FLIGHT = "FLIGHT"
DRIVE = "DRIVE"
SEA = "SEA"

#: The stable, client-facing code for "you asked for a mode this leg cannot
#: have".  Flutter maps it to copy; support maps it to this module.
MODE_UNAVAILABLE_CODE = "journey_leg_mode_unavailable"

#: Machine reasons a SEA leg is refused. DRIVE refusals carry no reason, so
#: their payload stays exactly what it was before sea legs existed.
SEA_LEGS_DISABLED = "sea_legs_disabled"
SEA_CROSSING_UNAVAILABLE = "sea_crossing_unavailable"
SEA_ENDPOINT_NOT_PORT_CITY = "sea_endpoint_not_port_city"

_SEA_REASON_SENTENCES = {
    SEA_LEGS_DISABLED: "sea legs are not available at the moment",
    SEA_CROSSING_UNAVAILABLE: "no active sea crossing joins these two ports",
    SEA_ENDPOINT_NOT_PORT_CITY: "both ends of a sea leg must be port cities",
}


def road_network(country_code: str | None) -> str:
    """The road network ``country_code`` belongs to."""

    code = (country_code or "").strip().upper()
    if not code:
        return f"{_ISOLATED_PREFIX}unknown"
    return ROAD_NETWORK_BY_COUNTRY.get(code, f"{_ISOLATED_PREFIX}{code}")


def drive_is_available(origin_country: str | None, destination_country: str | None) -> bool:
    """Whether a road leg between these two countries is possible at all."""

    return road_network(origin_country) == road_network(destination_country)


def sea_legs_enabled() -> bool:
    """The admin "Sea legs" switch, read at the moment of the action.

    A missing or unreadable settings revision answers False: the switch ships
    off, and a configuration fault must never be what turns sea legs on.
    """

    from apps.core.business_settings import NoActiveBusinessSettings
    from apps.core.marketplace_policy import (
        InvalidMarketplacePolicy,
        marketplace_policy,
    )

    try:
        return marketplace_policy().sea_legs_enabled
    except (NoActiveBusinessSettings, InvalidMarketplacePolicy):
        logger.warning("trips.sea_switch_unreadable; sea legs treated as off")
        return False


def _port_locality(place: Place | None) -> Place | None:
    if place is None or place.place_type != Place.PlaceType.LOCALITY:
        return None
    return place.resolve_matching_locality()


def sea_leg_refusal(
    origin: Place | None,
    destination: Place | None,
    *,
    enabled: bool,
) -> str | None:
    """Why a SEA leg between these places is impossible now, or ``None``.

    ``enabled`` is the switch as the caller read it at the moment of action;
    write paths pass `sea_legs_enabled()`, a scan passes the one value it read
    for every candidate.
    """

    if not enabled:
        return SEA_LEGS_DISABLED
    origin_port = _port_locality(origin)
    destination_port = _port_locality(destination)
    if origin_port is None or destination_port is None:
        return SEA_ENDPOINT_NOT_PORT_CITY
    if SeaCrossing.objects.filter(
        is_active=True,
        origin_locality=origin_port,
        destination_locality=destination_port,
        origin_locality__active=True,
        destination_locality__active=True,
    ).exists():
        return None
    # A port city is an endpoint of any crossing, live or not, so a line staff
    # paused reads as "no crossing now" rather than "this is not a port".
    port_ids = {origin_port.pk, destination_port.pk}
    served = set(
        SeaCrossing.objects.filter(origin_locality_id__in=port_ids).values_list(
            "origin_locality_id", flat=True
        )
    ) | set(
        SeaCrossing.objects.filter(destination_locality_id__in=port_ids).values_list(
            "destination_locality_id", flat=True
        )
    )
    if served != port_ids:
        return SEA_ENDPOINT_NOT_PORT_CITY
    return SEA_CROSSING_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class ModeViolation:
    """One leg whose declared mode is impossible, described for a client."""

    position: int
    mode: str
    origin_country: str
    destination_country: str
    required_mode: str | None
    reason: str | None = None

    def as_payload(self) -> dict:
        """The refusal's fields. A road refusal names the mode that would work;
        a sea refusal has no such mode and names its reason instead, so each
        key carries a real value (an API error never renders ``None``)."""

        payload = {
            "leg_position": self.position,
            "declared_mode": self.mode,
            "origin_country": self.origin_country,
            "destination_country": self.destination_country,
        }
        if self.required_mode is not None:
            payload["required_mode"] = self.required_mode
        if self.reason is not None:
            payload["reason"] = self.reason
        return payload


def check_leg_mode(
    *,
    position: int,
    mode: str,
    origin: Place | None,
    destination: Place | None,
) -> ModeViolation | None:
    """Return the violation for one leg, or ``None`` when it is possible.

    The sea switch and the crossing table are read only for a SEA leg, so a
    flight or road leg costs exactly what it did before sea legs existed.
    """

    origin_country = (getattr(origin, "country_id", None) or "").upper()
    destination_country = (getattr(destination, "country_id", None) or "").upper()
    if mode == DRIVE:
        if drive_is_available(origin_country, destination_country):
            return None
        return ModeViolation(
            position=position,
            mode=mode,
            origin_country=origin_country,
            destination_country=destination_country,
            required_mode=FLIGHT,
        )
    if mode == SEA:
        reason = sea_leg_refusal(origin, destination, enabled=sea_legs_enabled())
        if reason is None:
            return None
        return ModeViolation(
            position=position,
            mode=mode,
            origin_country=origin_country,
            destination_country=destination_country,
            required_mode=None,
            reason=reason,
        )
    return None


def mode_violation_message(violation: ModeViolation) -> str:
    """A stable English sentence for logs, admin and non-localized clients."""

    if violation.mode == SEA:
        return (
            f"Leg {violation.position} cannot be a sea leg: "
            f"{_SEA_REASON_SENTENCES[violation.reason]}."
        )
    return (
        f"Leg {violation.position} cannot be driven between "
        f"{violation.origin_country or 'an unknown country'} and "
        f"{violation.destination_country or 'an unknown country'}; "
        f"this segment must be a {violation.required_mode.lower()}."
    )


def sea_crossing_active_exists():
    """SQL annotation for a leg queryset: an active crossing joins its ports.

    A sea leg's endpoints are LOCALITY places (the write rules refuse anything
    else), so the leg's own place ids are the crossing's localities.
    """

    return Exists(
        SeaCrossing.objects.filter(
            is_active=True,
            origin_locality_id=OuterRef("origin_place_id"),
            destination_locality_id=OuterRef("destination_place_id"),
            origin_locality__active=True,
            destination_locality__active=True,
        )
    )


def sea_crossing_active(leg) -> bool:
    """Whether an active crossing still joins this sea leg's two ports.

    Reads the ``sea_crossing_active_value`` annotation matching attaches, and
    falls back to one query.
    """

    annotated = getattr(leg, "sea_crossing_active_value", None)
    if annotated is not None:
        return bool(annotated)
    return SeaCrossing.objects.filter(
        is_active=True,
        origin_locality_id=leg.origin_place_id,
        destination_locality_id=leg.destination_place_id,
        origin_locality__active=True,
        destination_locality__active=True,
    ).exists()


def unavailable_sea_legs(legs, *, enabled: bool | None = None) -> list:
    """The sea legs, in the order given, that cannot take a new offer now.

    Spec 5.3: the switch turned off or a crossing deactivated closes every
    journey that uses it, not only the parcels that would sail. ``enabled``
    is the switch as the caller already read it; left out, it is read here,
    and only when there is a sea leg to judge.
    """

    sea = [leg for leg in legs if leg.mode == SEA]
    if not sea:
        return []
    if enabled is None:
        enabled = sea_legs_enabled()
    return [leg for leg in sea if not (enabled and sea_crossing_active(leg))]
