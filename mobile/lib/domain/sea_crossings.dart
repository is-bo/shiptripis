/// The ferry lines the server will accept a sea leg on.
///
/// Mirrors `GET /api/geography/sea-crossings`: whether the owner's "Sea legs"
/// switch is on, and every active crossing as an ordered pair of port cities.
/// The server is the authority and refuses a sea leg whatever this says; the
/// list only exists so a traveller is never *offered* a crossing that would be
/// refused.
library;

import 'json.dart';

class SeaCrossings {
  const SeaCrossings({required this.enabled, required this.lines});

  factory SeaCrossings.fromJson(Map<String, dynamic> json) {
    final lines = <(int, int)>{};
    for (final row in readObjectList(json['crossings'])) {
      final origin = readInt(readObject(row['origin'])?['id']);
      final destination = readInt(readObject(row['destination'])?['id']);
      if (origin != null && destination != null) {
        lines.add((origin, destination));
      }
    }
    return SeaCrossings(enabled: json['enabled'] == true, lines: lines);
  }

  /// The switch is off and nothing is listed: no sea leg can be offered.
  static const off = SeaCrossings(enabled: false, lines: {});

  /// The "Sea legs" switch.
  final bool enabled;

  /// `(origin city id, destination city id)`, one entry per direction.
  final Set<(int, int)> lines;

  /// An active crossing exists in this direction, whatever the switch says.
  bool hasLine(int? originCityId, int? destinationCityId) =>
      originCityId != null &&
      destinationCityId != null &&
      lines.contains((originCityId, destinationCityId));

  /// A sea leg may be offered between these two cities right now.
  bool offers(int? originCityId, int? destinationCityId) =>
      enabled && hasLine(originCityId, destinationCityId);
}
