/// How a leg of a journey is travelled.
///
/// Lives in the domain rather than the design system because models parse it
/// and models must not depend on widgets. The icon and colour for each mode
/// are added back on in `design/components/status.dart`.
///
/// The API sends `"FLIGHT"` / `"DRIVE"` in **uppercase** — the one enum in the
/// whole V1 contract that does, which is exactly why parsing it is centralised
/// here instead of spelled out at each call site.
library;

enum TransportMode {
  flight,
  drive,
  unknown;

  static TransportMode parse(Object? raw) {
    final text = raw is String ? raw.toUpperCase() : '';
    return switch (text) {
      'FLIGHT' => TransportMode.flight,
      'DRIVE' => TransportMode.drive,
      _ => TransportMode.unknown,
    };
  }

  /// The value to send back to the server.
  String get wire => switch (this) {
    TransportMode.flight => 'FLIGHT',
    TransportMode.drive => 'DRIVE',
    TransportMode.unknown => '',
  };

  /// Only flight legs require transport proof before a journey can publish.
  bool get requiresProof => this == TransportMode.flight;
}
