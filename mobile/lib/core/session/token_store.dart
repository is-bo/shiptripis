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

import 'dart:math';

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
  int _identityGeneration = 0;
  Future<void> _credentialWriteTail = Future<void>.value();

  /// Changes synchronously before any credential mutation awaits platform
  /// storage. Token refresh uses it to reject a response started by an older
  /// login, even when the next account signs in while that response is in
  /// flight.
  int get identityGeneration => _identityGeneration;

  /// Invalidates requests and refreshes belonging to the current login while
  /// retaining the bytes long enough for best-effort server sign-out.
  int invalidateIdentity() => ++_identityGeneration;

  static const _kAccess = 'auth.access';
  static const _kRefresh = 'auth.refresh';
  static const _kRoleContext = 'app.role_context';
  static const _kLocale = 'app.locale';
  static const _kInstallationId = 'push.installation_id';
  static const _kPendingPushToken = 'push.pending_token';

  /// Keys written by the retired build. Removed on every start.
  static const _legacyKeys = <String>['handover.codes', 'app.role'];

  Future<void> save({required String access, required String refresh}) {
    _identityGeneration++;
    return _serializeCredentialWrite(() async {
      await _storage.write(key: _kAccess, value: access);
      await _storage.write(key: _kRefresh, value: refresh);
    });
  }

  Future<String?> readAccess() => _readCredential(_kAccess);
  Future<String?> readRefresh() => _readCredential(_kRefresh);

  Future<void> updateAccess(String access) {
    return _serializeCredentialWrite(
      () => _storage.write(key: _kAccess, value: access),
    );
  }

  /// Commits a refresh only if the login that started it is still current.
  Future<bool> saveRefreshedIfCurrent({
    required int expectedIdentityGeneration,
    required String expectedRefresh,
    required String access,
    String? refresh,
  }) => _serializeCredentialWrite(() async {
    if (_identityGeneration != expectedIdentityGeneration) return false;
    final currentRefresh = await _storage.read(key: _kRefresh);
    if (_identityGeneration != expectedIdentityGeneration ||
        currentRefresh != expectedRefresh) {
      return false;
    }
    await _storage.write(key: _kAccess, value: access);
    if (_identityGeneration != expectedIdentityGeneration) return false;
    if (refresh != null) {
      await _storage.write(key: _kRefresh, value: refresh);
      if (_identityGeneration != expectedIdentityGeneration) return false;
    }
    return true;
  });

  Future<bool> saveAuthenticationIfCurrent({
    required int expectedIdentityGeneration,
    required String access,
    required String refresh,
  }) => _serializeCredentialWrite(() async {
    if (_identityGeneration != expectedIdentityGeneration) return false;
    await _storage.write(key: _kAccess, value: access);
    if (_identityGeneration != expectedIdentityGeneration) return false;
    await _storage.write(key: _kRefresh, value: refresh);
    return _identityGeneration == expectedIdentityGeneration;
  });

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

  /// Random per-installation UUID. It is deliberately retained across logout
  /// and is not a hardware, advertising, or vendor identifier.
  Future<String> readOrCreateInstallationId() async {
    final existing = await _storage.read(key: _kInstallationId);
    if (existing != null && existing.isNotEmpty) return existing;
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes
        .map((byte) => byte.toRadixString(16).padLeft(2, '0'))
        .join();
    final generated =
        '${hex.substring(0, 8)}-${hex.substring(8, 12)}-'
        '${hex.substring(12, 16)}-${hex.substring(16, 20)}-'
        '${hex.substring(20)}';
    await _storage.write(key: _kInstallationId, value: generated);
    return generated;
  }

  Future<String?> readPendingPushToken() =>
      _storage.read(key: _kPendingPushToken);

  Future<void> writePendingPushToken(String? token) => token == null
      ? _storage.delete(key: _kPendingPushToken)
      : _storage.write(key: _kPendingPushToken, value: token);

  /// Removes credentials and every user-scoped preference. Called on sign-out
  /// and whenever refresh fails terminally.
  Future<void> clear() {
    _identityGeneration++;
    return _serializeCredentialWrite(_clearCredentials);
  }

  Future<bool> clearIfIdentityCurrent(int expectedIdentityGeneration) =>
      _serializeCredentialWrite(() async {
        if (_identityGeneration != expectedIdentityGeneration) return false;
        final clearingGeneration = ++_identityGeneration;
        await _clearCredentials();
        return _identityGeneration == clearingGeneration;
      });

  Future<void> _clearCredentials() async {
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

  Future<T> _serializeCredentialWrite<T>(Future<T> Function() operation) {
    final result = _credentialWriteTail.then((_) => operation());
    _credentialWriteTail = result.then<void>(
      (_) {},
      onError: (Object _, StackTrace _) {},
    );
    return result;
  }

  Future<String?> _readCredential(String key) async {
    while (true) {
      final pending = _credentialWriteTail;
      await pending;
      if (!identical(pending, _credentialWriteTail)) continue;
      return _storage.read(key: key);
    }
  }
}
