import 'json.dart';

enum CanonicalPlaceType { locality, airport, adminRegion, unknown }

/// Stable geography-catalogue identity.  Names are presentation only; the
/// server resolves [matchingLocalityId] and compatibility never compares text.
class CanonicalPlace {
  const CanonicalPlace({
    required this.id,
    required this.countryCode,
    required this.type,
    required this.name,
    required this.displayLabel,
    required this.parentName,
    required this.parentAdminLevel,
    required this.matchingLocalityId,
    this.iataCode,
    this.matchingLocalityName,
    this.latitude,
    this.longitude,
    this.availableForMatching = true,
  });

  factory CanonicalPlace.fromJson(Map<String, dynamic> json) {
    final matching = readObject(json['matching_locality']);
    return CanonicalPlace(
      id: readInt(json['id']) ?? 0,
      countryCode: readText(json['country_code']),
      type: readEnum(
        json['place_type'],
        CanonicalPlaceType.values,
        fallback: CanonicalPlaceType.unknown,
        aliases: const {'admin_region': CanonicalPlaceType.adminRegion},
      ),
      name: readText(json['name']),
      displayLabel: readText(json['display_label']),
      parentName: readText(json['parent_name']),
      parentAdminLevel: readText(json['parent_admin_level']),
      iataCode: readString(json['iata_code']),
      matchingLocalityId:
          readInt(json['matching_locality_id']) ?? readInt(matching?['id']),
      matchingLocalityName:
          readString(json['matching_locality_name']) ??
          readString(matching?['name']),
      latitude: readDouble(json['latitude']),
      longitude: readDouble(json['longitude']),
      availableForMatching: json['available_for_matching'] != false,
    );
  }

  final int id;
  final String countryCode;
  final CanonicalPlaceType type;
  final String name;
  final String displayLabel;
  final String parentName;

  /// The parent's own administrative tier as the reviewed catalogue records it
  /// — `wilaya`, `department`, `province`, `state` and so on. Empty when the
  /// source names no tier. Presentation only: the client never derives a tier
  /// from a country or a name.
  final String parentAdminLevel;
  final String? iataCode;
  final int? matchingLocalityId;
  final String? matchingLocalityName;
  final double? latitude;
  final double? longitude;
  final bool availableForMatching;

  bool get isAirport => type == CanonicalPlaceType.airport;

  String get typeLabel => isAirport ? 'Airport' : 'Locality';

  String get contextualLabel {
    final airport = isAirport && iataCode != null ? ' (${iataCode!})' : '';
    final context = parentName.isNotEmpty
        ? '\n$typeLabel · $parentName'
        : '\n$typeLabel';
    return '$name$airport$context';
  }
}

class GeographyCountry {
  const GeographyCountry({required this.code, required this.name});

  factory GeographyCountry.fromJson(Map<String, dynamic> json) =>
      GeographyCountry(
        code: readText(json['code']).toUpperCase(),
        name: readText(json['name']),
      );

  final String code;
  final String name;
}
