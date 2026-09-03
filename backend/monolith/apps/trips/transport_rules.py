"""Which transport modes are physically possible on a Journey leg.

V1 has two modes, FLIGHT and DRIVE, and the catalogue serves four countries.
Not every pair of those countries is reachable by road: Algeria is separated
from the European corridor by the Mediterranean, and ShipTrip does not carry
sea transport in V1.  A traveller who declares a DRIVE leg from Jijel to
Marseille is describing a journey nobody can make, and every downstream
promise built on it — capacity, timing, a sender's delivery window — is
false.

So a leg's *availability* is derived from geography rather than trusted from
the client:

* Two places on the same road network may be joined by DRIVE.
* Two places on different road networks must be joined by FLIGHT.

The networks are declared, not inferred.  Algeria is its own network; France,
Spain and Germany share the continental European one.  A country the
catalogue serves but this table does not name is treated as its own isolated
network, which fails closed: an unknown pair requires a flight rather than
silently permitting a road leg across an ocean.

Ferries are deliberately absent.  Adding one is a product decision with real
proof, capacity and timing consequences, not a table entry.
"""

from __future__ import annotations

from dataclasses import dataclass

from apps.locations.models import Place

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

#: The stable, client-facing code for "you asked for a mode this leg cannot
#: have".  Flutter maps it to copy; support maps it to this module.
MODE_UNAVAILABLE_CODE = "journey_leg_mode_unavailable"


def road_network(country_code: str | None) -> str:
    """The road network ``country_code`` belongs to."""

    code = (country_code or "").strip().upper()
    if not code:
        return f"{_ISOLATED_PREFIX}unknown"
    return ROAD_NETWORK_BY_COUNTRY.get(code, f"{_ISOLATED_PREFIX}{code}")


def drive_is_available(origin_country: str | None, destination_country: str | None) -> bool:
    """Whether a road leg between these two countries is possible at all."""

    return road_network(origin_country) == road_network(destination_country)


def flight_is_required(
    origin_country: str | None, destination_country: str | None
) -> bool:
    """Whether the only V1 mode for this pair is FLIGHT."""

    return not drive_is_available(origin_country, destination_country)


def available_modes(
    origin_country: str | None, destination_country: str | None
) -> tuple[str, ...]:
    """Every mode this pair may legally declare, in preference order."""

    if flight_is_required(origin_country, destination_country):
        return (FLIGHT,)
    return (FLIGHT, DRIVE)


def default_mode(origin: Place | None, destination: Place | None) -> str:
    """The mode to pre-select for a freshly derived segment.

    Helping rather than guessing: a pair that can only fly defaults to FLIGHT,
    two airports default to FLIGHT because that is what an airport pair is
    for, and anything else on one road network defaults to DRIVE.  The default
    is never a mode the pair cannot have.
    """

    origin_country = getattr(origin, "country_id", None)
    destination_country = getattr(destination, "country_id", None)
    if flight_is_required(origin_country, destination_country):
        return FLIGHT
    both_airports = (
        getattr(origin, "place_type", None) == Place.PlaceType.AIRPORT
        and getattr(destination, "place_type", None) == Place.PlaceType.AIRPORT
    )
    return FLIGHT if both_airports else DRIVE


@dataclass(frozen=True, slots=True)
class ModeViolation:
    """One leg whose declared mode is impossible, described for a client."""

    position: int
    mode: str
    origin_country: str
    destination_country: str
    required_mode: str

    def as_payload(self) -> dict:
        return {
            "leg_position": self.position,
            "declared_mode": self.mode,
            "required_mode": self.required_mode,
            "origin_country": self.origin_country,
            "destination_country": self.destination_country,
        }


def check_leg_mode(
    *,
    position: int,
    mode: str,
    origin: Place | None,
    destination: Place | None,
) -> ModeViolation | None:
    """Return the violation for one leg, or ``None`` when it is possible."""

    origin_country = (getattr(origin, "country_id", None) or "").upper()
    destination_country = (getattr(destination, "country_id", None) or "").upper()
    if mode != DRIVE:
        return None
    if drive_is_available(origin_country, destination_country):
        return None
    return ModeViolation(
        position=position,
        mode=mode,
        origin_country=origin_country,
        destination_country=destination_country,
        required_mode=FLIGHT,
    )


def mode_violation_message(violation: ModeViolation) -> str:
    """A stable English sentence for logs, admin and non-localized clients."""

    return (
        f"Leg {violation.position} cannot be driven between "
        f"{violation.origin_country or 'an unknown country'} and "
        f"{violation.destination_country or 'an unknown country'}; "
        f"this segment must be a {violation.required_mode.lower()}."
    )
