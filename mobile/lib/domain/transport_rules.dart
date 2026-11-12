/// Which transport modes a segment can physically have.
///
/// This is a mirror of `apps/trips/transport_rules.py`, and deliberately so.
/// The server is the authority — it refuses an impossible leg with
/// `journey_leg_mode_unavailable` whatever the client believes — but a
/// traveller should never be *offered* a mode that will be refused. Letting
/// someone fill in six fields for a drive from Jijel to Marseille and then
/// bouncing them is the worst version of this form.
///
/// The road rule is about road networks, not about Algeria. Algeria is
/// separated from the European corridor by the Mediterranean, so those two
/// networks are joined by air or by a ferry line. France, Spain and Germany
/// share a continental network and stay driveable.
///
/// A country with no declared network is its own island, which fails closed:
/// an unknown pair needs a flight rather than silently permitting a road leg
/// across an ocean.
///
/// The sea rule is the server's list, not geography: a sea leg joins two port
/// cities that an active crossing connects, and only while the owner's switch
/// is on ([SeaCrossings]). Until that list has loaded, or if it cannot be
/// loaded, Sea is simply not offered; flight and road editing never wait for
/// it.
library;

import 'canonical_place.dart';
import 'sea_crossings.dart';

/// ISO 3166-1 alpha-2 → the road network reachable without leaving the ground.
const Map<String, String> roadNetworkByCountry = {
  'DZ': 'dz-maghreb',
  'FR': 'eu-continental-west',
  'ES': 'eu-continental-west',
  'DE': 'eu-continental-west',
};

String _network(String? countryCode) {
  final code = (countryCode ?? '').trim().toUpperCase();
  if (code.isEmpty) return 'isolated:unknown';
  return roadNetworkByCountry[code] ?? 'isolated:$code';
}

/// The modes a leg may declare.
enum LegMode {
  flight,
  drive,
  sea;

  bool get isFlight => this == LegMode.flight;
  bool get isSea => this == LegMode.sea;
}

/// Why the server refuses a sea leg. The three values are its `reason` codes.
enum SeaRefusal {
  /// The "Sea legs" switch is off (`sea_legs_disabled`).
  switchedOff,

  /// Both ends are port cities but no active line joins them this way
  /// (`sea_crossing_unavailable`).
  noCrossing,

  /// An end is an airport, or a city no line touches
  /// (`sea_endpoint_not_port_city`).
  notPortCity;

  static SeaRefusal? fromServer(String? reason) => switch (reason) {
    'sea_legs_disabled' => switchedOff,
    'sea_crossing_unavailable' => noCrossing,
    'sea_endpoint_not_port_city' => notPortCity,
    _ => null,
  };
}

/// Whether a road leg between these two countries is possible at all.
bool driveIsAvailable(String? originCountry, String? destinationCountry) =>
    _network(originCountry) == _network(destinationCountry);

/// Whether a road leg is impossible, which leaves flight (and sea, where a
/// ferry line exists).
bool flightIsRequired(String? originCountry, String? destinationCountry) =>
    !driveIsAvailable(originCountry, destinationCountry);

/// Whether Sea is missing from a pair *only because* the switch is off.
///
/// A pair without a ferry line says nothing about sea at all, because there is
/// nothing to explain. [crossings] null means the list is not known (still
/// loading or failed), which also says nothing here.
bool seaIsSwitchedOff(
  CanonicalPlace? origin,
  CanonicalPlace? destination,
  SeaCrossings? crossings,
) {
  if (crossings == null || crossings.enabled) return false;
  if (origin == null || destination == null) return false;
  if (origin.isAirport || destination.isAirport) return false;
  return crossings.hasLine(
    origin.matchingLocalityId,
    destination.matchingLocalityId,
  );
}

/// What the server would say about a sea leg between these cities right now,
/// or null when it would accept it.
///
/// [crossings] null means the list is unknown, which is never a reason to
/// refuse a leg the traveller already has: the server stays the authority.
SeaRefusal? seaRefusal(
  CanonicalPlace? origin,
  CanonicalPlace? destination,
  SeaCrossings? crossings,
) {
  if (crossings == null || origin == null || destination == null) return null;
  if (origin.isAirport || destination.isAirport) return SeaRefusal.notPortCity;
  if (!crossings.enabled) return SeaRefusal.switchedOff;
  return crossings.hasLine(
        origin.matchingLocalityId,
        destination.matchingLocalityId,
      )
      ? null
      : SeaRefusal.noCrossing;
}

/// Every mode this pair may legally declare.
///
/// [origin] and [destination] are the *cities* of the two stops: a sea leg
/// runs between two port cities, never between airports, so an airport stop
/// can fly or drive but never sail.
Set<LegMode> availableModes(
  CanonicalPlace? origin,
  CanonicalPlace? destination, {
  SeaCrossings? crossings,
}) {
  if (origin == null || destination == null) {
    return {LegMode.flight, LegMode.drive};
  }
  final modes = <LegMode>{LegMode.flight};
  if (driveIsAvailable(origin.countryCode, destination.countryCode)) {
    modes.add(LegMode.drive);
  }
  if (crossings != null &&
      !origin.isAirport &&
      !destination.isAirport &&
      crossings.offers(
        origin.matchingLocalityId,
        destination.matchingLocalityId,
      )) {
    modes.add(LegMode.sea);
  }
  return modes;
}

/// The mode to pre-select for a freshly derived segment.
///
/// Helping rather than guessing: a pair that can only fly defaults to flight,
/// two airports default to flight because that is what an airport pair is for,
/// and anything else on one road network defaults to drive. The default is
/// never a mode the pair cannot have.
LegMode defaultModeFor(CanonicalPlace? origin, CanonicalPlace? destination) {
  if (origin == null || destination == null) return LegMode.drive;
  if (flightIsRequired(origin.countryCode, destination.countryCode)) {
    return LegMode.flight;
  }
  if (origin.isAirport && destination.isAirport) return LegMode.flight;
  return LegMode.drive;
}
