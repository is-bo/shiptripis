/// Which transport modes a segment can physically have.
///
/// This is a mirror of `apps/trips/transport_rules.py`, and deliberately so.
/// The server is the authority — it refuses an impossible leg with
/// `journey_leg_mode_unavailable` whatever the client believes — but a
/// traveller should never be *offered* a mode that will be refused. Letting
/// someone fill in six fields for a drive from Jijel to Marseille and then
/// bouncing them is the worst version of this form.
///
/// The rule is about road networks, not about Algeria. Algeria is separated
/// from the European corridor by the Mediterranean and ShipTrip carries no sea
/// transport in V1, so those two networks are joined only by air. France,
/// Spain and Germany share a continental network and stay driveable.
///
/// A country with no declared network is its own island, which fails closed:
/// an unknown pair needs a flight rather than silently permitting a road leg
/// across an ocean.
library;

import 'canonical_place.dart';

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

/// The two modes a V1 leg may declare.
enum LegMode {
  flight,
  drive;

  bool get isFlight => this == LegMode.flight;
}

/// Whether a road leg between these two countries is possible at all.
bool driveIsAvailable(String? originCountry, String? destinationCountry) =>
    _network(originCountry) == _network(destinationCountry);

/// Whether the only V1 mode for this pair is a flight.
bool flightIsRequired(String? originCountry, String? destinationCountry) =>
    !driveIsAvailable(originCountry, destinationCountry);

/// Every mode this pair may legally declare.
Set<LegMode> availableModes(
  CanonicalPlace? origin,
  CanonicalPlace? destination,
) {
  if (origin == null || destination == null) {
    return {LegMode.flight, LegMode.drive};
  }
  if (flightIsRequired(origin.countryCode, destination.countryCode)) {
    return {LegMode.flight};
  }
  return {LegMode.flight, LegMode.drive};
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
