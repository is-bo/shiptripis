/// Build-time configuration.
///
/// Everything here is a `--dart-define`, never a checked-in secret. The client
/// holds no provider keys at all: checkout is created server-side and the app
/// only ever opens a URL the server handed it.
library;

abstract final class AppConfig {
  /// Gateway origin.
  ///
  /// ```
  /// flutter run --dart-define=API_BASE_URL=http://192.168.1.42:8080
  /// ```
  ///
  /// `10.0.2.2` is the Android emulator's route to the host machine.
  static const apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8080',
  );

  /// Origin of the Go KYC service, which is a separate deployment with its own
  /// routing and its own `{"error": …}` envelope. Defaults to the gateway,
  /// which is how it is reached when Caddy fronts both.
  static const kycBaseUrl = String.fromEnvironment(
    'KYC_BASE_URL',
    defaultValue: apiBaseUrl,
  );

  /// Tile template for the map surface.
  ///
  /// Defaults to OpenStreetMap, which needs no credential and therefore keeps
  /// the app buildable and testable before a production map contract exists.
  /// OSM's public tiles are not licensed for production traffic; swapping this
  /// define is the release-stage step, in the same class as the Stripe and
  /// Chargily keys.
  static const mapTileUrl = String.fromEnvironment(
    'MAP_TILE_URL',
    defaultValue: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
  );

  /// Attribution required by the active tile source.
  static const mapAttribution = String.fromEnvironment(
    'MAP_ATTRIBUTION',
    defaultValue: '© OpenStreetMap contributors',
  );

  /// Sent as a tile-request User-Agent. OSM's policy requires a contactable
  /// identifier rather than the default Dart one.
  static const mapUserAgent = String.fromEnvironment(
    'MAP_USER_AGENT',
    defaultValue: 'com.shiptrip.app',
  );

  static const requestTimeout = Duration(seconds: 20);
  static const connectTimeout = Duration(seconds: 12);

  /// WebSocket origin derived from [apiBaseUrl].
  static String get wsBaseUrl {
    if (apiBaseUrl.startsWith('https://')) {
      return 'wss://${apiBaseUrl.substring('https://'.length)}';
    }
    if (apiBaseUrl.startsWith('http://')) {
      return 'ws://${apiBaseUrl.substring('http://'.length)}';
    }
    return apiBaseUrl;
  }
}
