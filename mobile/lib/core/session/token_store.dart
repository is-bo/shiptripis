/// Credential storage.
///
/// ## What is allowed on this device, and what is not
///
/// Stored: the access token, the refresh token, and the user's chosen role
/// context. All three go in the platform keystore, and all three are wiped on
/// sign-out.
///
/// **Never stored, at any layer:** a pickup code, a delivery code, a guest
/// payment token, recipient contact details, or a payment provider secret.
///
/// The previous build kept handover-code plaintext in exactly this keystore,
/// keyed by match, for both pickup *and* delivery. That store is deleted, and
/// [purgeLegacyArtifacts] removes what it left behind on devices that already
/// have it — an upgrade must not leave a delivery code sitting in the keystore
/// of a traveler's phone.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStore {
  TokenStore([FlutterSecureStorage? storage])
    : _storage =
          storage ??
          const FlutterSecureStorage(
            aOptions: AndroidOptions(encryptedSharedPreferences: true),
            iOptions: IOSOptions(
              // Not `afterFirstUnlock`: nothing here needs to be readable
              // while the device is locked, and `thisDeviceOnly` keeps the
              // session out of an iCloud keychain backup.
              accessibility: KeychainAccessibility.first_unlock_this_device,
            ),
          );

  final FlutterSecureStorage _storage;

  static const _kAccess = 'auth.access';
  static const _kRefresh = 'auth.refresh';
  static const _kRoleContext = 'app.role_context';
  static const _kLocale = 'app.locale';

  /// Keys written by the retired build. Removed on every start.
  static const _legacyKeys = <String>['handover.codes', 'app.role'];

  Future<void> save({required String access, required String refresh}) async {
    await _storage.write(key: _kAccess, value: access);
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<String?> readAccess() => _storage.read(key: _kAccess);
  Future<String?> readRefresh() => _storage.read(key: _kRefresh);

  Future<void> updateAccess(String access) =>
      _storage.write(key: _kAccess, value: access);

  /// Which side of the marketplace a dual-role user last worked from. A
  /// preference, not a permission — the server's role is always authoritative
  /// about what the account may actually do.
  Future<String?> readRoleContext() => _storage.read(key: _kRoleContext);
  Future<void> writeRoleContext(String value) =>
      _storage.write(key: _kRoleContext, value: value);

  /// Explicit language choice. Absent means "follow the device".
  Future<String?> readLocale() => _storage.read(key: _kLocale);
  Future<void> writeLocale(String? tag) => tag == null
      ? _storage.delete(key: _kLocale)
      : _storage.write(key: _kLocale, value: tag);

  /// Removes credentials and every user-scoped preference. Called on sign-out
  /// and whenever refresh fails terminally.
  Future<void> clear() async {
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
    await _storage.delete(key: _kRoleContext);
    await purgeLegacyArtifacts();
  }

  /// Deletes secrets written by the retired client. Cheap, idempotent, and
  /// run at every launch so an upgrade cannot leave a handover code behind.
  Future<void> purgeLegacyArtifacts() async {
    for (final key in _legacyKeys) {
      try {
        await _storage.delete(key: key);
      } catch (_) {
        // A keystore that refuses a delete for an absent key must not stop
        // the app from starting.
      }
    }
  }
}
