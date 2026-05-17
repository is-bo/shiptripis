/// Base URL for the ShipTrip backend gateway.
///
/// Override at build time:
///   flutter build apk --release --dart-define=API_BASE_URL=http://192.168.1.42:8080
///
/// Defaults:
/// - Android emulator (`10.0.2.2`) reaches the host machine's localhost.
/// - For a physical phone, pass your PC's LAN IP via --dart-define.
class ApiConfig {
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8080',
  );

  /// WebSocket origin derived from `baseUrl` (http→ws, https→wss).
  /// Append the specific path (e.g. `/ws/notifications`) at the call site.
  static String get wsBaseUrl {
    if (baseUrl.startsWith('https://')) {
      return 'wss://${baseUrl.substring(8)}';
    }
    if (baseUrl.startsWith('http://')) {
      return 'ws://${baseUrl.substring(7)}';
    }
    return baseUrl;
  }
}
