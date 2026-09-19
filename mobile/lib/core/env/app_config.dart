/// Build-time configuration.
///
/// Everything here is a `--dart-define`, never a checked-in secret. The client
/// holds no provider keys at all: checkout is created server-side and the app
/// only ever opens a URL the server handed it.
library;

import 'package:flutter/foundation.dart';

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
    defaultValue: kReleaseMode ? '' : 'http://10.0.2.2:8080',
  );

  /// Origin of the Go KYC service, which is a separate deployment with its own
  /// routing and its own `{"error": …}` envelope. Defaults to the gateway,
  /// which is how it is reached when Caddy fronts both.
  static const kycBaseUrl = String.fromEnvironment(
    'KYC_BASE_URL',
    defaultValue: apiBaseUrl,
  );

  /// Origin of the public marketing and legal site. Defaults to [apiBaseUrl],
  /// which matches the Caddy gateway hosting both the public site and API
  /// in development, staging and production.
  static const webBaseUrl = String.fromEnvironment(
    'WEB_BASE_URL',
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

  /// The longest a single read may take *including* its retries.
  ///
  /// Per-attempt timeouts stay where they are: they are sized for a phone on a
  /// bad connection, and shortening them would turn a slow answer into a false
  /// failure. What was unbounded is the sum. A read retries twice on a timeout,
  /// so a stalled request could hold a screen for three 20-second attempts plus
  /// backoff — around a minute — before the user was told anything, which is
  /// exactly the "it just hangs" symptom. Measured server behaviour does not
  /// justify waiting that long: on the deployed TEST runtime the authenticated
  /// API answers in tens of milliseconds, and the p95 excluding long-lived
  /// websocket connections is a fifth of a second.
  ///
  /// A read that has already spent this long is not retried again; the timeout
  /// is reported, the screen keeps whatever it had, and the user can retry
  /// deliberately.
  static const requestBudget = Duration(seconds: 30);

  /// A release must name its deployment. Assertions are disabled in release,
  /// so reject invalid configuration explicitly before any service starts.
  static void validate({bool release = kReleaseMode}) {
    if (!release) return;
    validateReleaseOrigin(apiBaseUrl);
    validateReleaseOrigin(kycBaseUrl);
    validateReleaseOrigin(webBaseUrl);
  }

  static void validateReleaseOrigin(String value) {
    final uri = Uri.tryParse(value);
    if (uri == null ||
        uri.scheme != 'https' ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        uri.hasQuery ||
        uri.hasFragment ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        {'localhost', '127.0.0.1', '10.0.2.2', '::1'}.contains(uri.host) ||
        uri.host.endsWith('.invalid') ||
        uri.host.endsWith('.test')) {
      throw StateError(
        'Release builds require an explicit HTTPS API/KYC origin.',
      );
    }
  }

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
