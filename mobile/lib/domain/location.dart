/// Places, and how much of a place the viewer is allowed to know.
///
/// The API has **two** location shapes and they are not a superset/subset pair:
///
/// * The private shape (the owner's own record) carries `latitude`,
///   `longitude`, `private_label` and `normalized_label`.
/// * The public shape carries `coarse_latitude`/`coarse_longitude` — quantised
///   to 0.1°, roughly an 11 km cell — and `public_label` only.
///
/// A journey leg goes further: a non-owner does not get `distance_meters` at
/// all, they get a `distance_band` object *instead*. The key is swapped, not
/// nulled. [AppLocation.fromJson] and [DistanceBand.fromJson] therefore branch
/// on which keys are present rather than assuming both exist.
///
/// [AppLocation.isExact] is the single question a screen should ask before
/// rendering a pin or a street: it is true only when the server actually sent
/// exact coordinates, which it does only once entitlement allows.
library;

import 'json.dart';

enum LocationKind {
  city,
  exactAddress,
  mapPoint,
  airport,
  publicMeetingPoint,
  unknown,
}

enum LocationPrecision {
  exact,
  rooftop,
  building,
  street,
  neighborhood,
  city,
  region,
  country,
  approximate,
  unknown,
}

class AppLocation {
  const AppLocation({
    required this.id,
    required this.kind,
    required this.publicLabel,
    required this.city,
    required this.region,
    required this.countryCode,
    required this.precision,
    required this.coordinatesTrusted,
    this.coarseLatitude,
    this.coarseLongitude,
    this.airportIata,
    this.privateLabel,
    this.normalizedLabel,
    this.latitude,
    this.longitude,
  });

  factory AppLocation.fromJson(Map<String, dynamic> json) => AppLocation(
    id: readInt(json['id']) ?? 0,
    kind: readEnum(
      json['kind'],
      LocationKind.values,
      fallback: LocationKind.unknown,
    ),
    publicLabel: readText(json['public_label']),
    city: readText(json['city']),
    region: readText(json['region']),
    countryCode: readText(json['country_code']),
    precision: readEnum(
      json['precision'],
      LocationPrecision.values,
      fallback: LocationPrecision.unknown,
    ),
    coordinatesTrusted: readBool(json['coordinates_trusted']),
    coarseLatitude: readDouble(json['coarse_latitude']),
    coarseLongitude: readDouble(json['coarse_longitude']),
    airportIata: readString(json['airport']),
    privateLabel: readString(json['private_label']),
    normalizedLabel: readString(json['normalized_label']),
    latitude: readDouble(json['latitude']),
    longitude: readDouble(json['longitude']),
  );

  /// Builds a location from the legacy airport shape that still appears under
  /// `parcel.origin`/`parcel.destination` on a pre-V1 Match.
  ///
  /// Not an invention of data: every field comes from the payload. It exists
  /// so a screen never has to know that one key can hold two shapes.
  factory AppLocation.fromAirportJson(Map<String, dynamic> json) => AppLocation(
    id: 0,
    kind: LocationKind.airport,
    publicLabel: [
      readText(json['city']),
      readText(json['country']),
    ].where((s) => s.isNotEmpty).join(', '),
    city: readText(json['city']),
    region: '',
    countryCode: readText(json['country']),
    precision: LocationPrecision.city,
    coordinatesTrusted: true,
    airportIata: readString(json['iata']),
  );

  /// Parses either shape found under a single key.
  static AppLocation? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    if (json.containsKey('iata') && !json.containsKey('public_label')) {
      return AppLocation.fromAirportJson(json);
    }
    return AppLocation.fromJson(json);
  }

  final int id;
  final LocationKind kind;

  /// City-level label, safe to show to anyone.
  final String publicLabel;

  final String city;
  final String region;
  final String countryCode;
  final LocationPrecision precision;

  /// Whether the coordinates came from a reviewed dataset rather than a
  /// provider guess. Only meaningful for airports.
  final bool coordinatesTrusted;

  final double? coarseLatitude;
  final double? coarseLongitude;
  final String? airportIata;

  // ---- Owner-only, absent unless the viewer is entitled ----

  /// May contain a street address. Never rendered to a counterparty, never
  /// logged.
  final String? privateLabel;

  final String? normalizedLabel;
  final double? latitude;
  final double? longitude;

  /// True only when the server released exact coordinates to this viewer.
  bool get isExact => latitude != null && longitude != null;

  /// The best coordinates the viewer is entitled to, or null if the server
  /// sent none at all.
  ({double lat, double lng})? get point {
    if (latitude != null && longitude != null) {
      return (lat: latitude!, lng: longitude!);
    }
    if (coarseLatitude != null && coarseLongitude != null) {
      return (lat: coarseLatitude!, lng: coarseLongitude!);
    }
    return null;
  }

  /// What to put on screen. Falls back through the labels the viewer has
  /// rather than rendering an empty string.
  String get displayLabel {
    if (privateLabel != null && privateLabel!.isNotEmpty) return privateLabel!;
    if (publicLabel.isNotEmpty) return publicLabel;
    if (normalizedLabel != null && normalizedLabel!.isNotEmpty) {
      return normalizedLabel!;
    }
    if (city.isNotEmpty) {
      return countryCode.isEmpty ? city : '$city, $countryCode';
    }
    return airportIata ?? '';
  }

  /// The coarse label, even when this viewer could see more. For the places a
  /// screen must show city-level precision regardless of entitlement.
  String get coarseLabel {
    if (publicLabel.isNotEmpty) return publicLabel;
    if (city.isNotEmpty) {
      return countryCode.isEmpty ? city : '$city, $countryCode';
    }
    return airportIata ?? '';
  }
}

/// A distance the server refuses to state exactly.
///
/// Bands are a privacy ladder, not a rounding convenience: an exact carried
/// distance combined with two coarse endpoints can reconstruct a pickup
/// address. The client renders the band and never the midpoint.
class DistanceBand {
  const DistanceBand({
    required this.label,
    required this.minMeters,
    required this.maxMeters,
  });

  static DistanceBand? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return DistanceBand(
      label: readText(json['label']),
      minMeters: readInt(json['min_meters']),
      maxMeters: readInt(json['max_meters']),
    );
  }

  /// The wire label, e.g. `under_100km`, `1500_3000km`, `over_5000km`.
  final String label;

  final int? minMeters;
  final int? maxMeters;
}

/// How much detour a candidate adds to the traveller's route.
///
/// Wire values are `under_5km`, `5_15km`, `over_15km` — the middle one cannot
/// be a Dart identifier, so all three go through the alias table.
enum DetourBand {
  small,
  moderate,
  large,
  unknown;

  static DetourBand parse(Object? raw) => readEnum(
    raw,
    DetourBand.values,
    fallback: DetourBand.unknown,
    aliases: const {
      'under_5km': DetourBand.small,
      '5_15km': DetourBand.moderate,
      'over_15km': DetourBand.large,
    },
  );
}

/// How the matched distance was arrived at. Shown to nobody directly; used to
/// decide whether a distance is worth stating at all.
enum DistancePrecision { unavailable, mixed, estimated, routed, unknown }

/// An airport, from `GET /api/airports`.
class Airport {
  const Airport({
    required this.iata,
    required this.city,
    required this.name,
    required this.country,
  });

  factory Airport.fromJson(Map<String, dynamic> json) => Airport(
    iata: readText(json['iata']),
    city: readText(json['city']),
    name: readText(json['name']),
    country: readText(json['country']),
  );

  final String iata;
  final String city;
  final String name;
  final String country;

  String get label => '$city ($iata)';
}
