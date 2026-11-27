/// Credential storage.
///
/// ## What is allowed on this device, and what is not
///
/// Stored: the access token, the refresh token, the user's chosen role
/// context, and a snapshot of the last server-confirmed profile (presentation
/// fields only — see `Account.toSnapshotJson`). All four go in the platform
/// keystore, and all four are wiped on sign-out. Beside them sit a few things
/// that belong to the phone rather than the account and so survive sign-out: a
/// random installation ID, a pending push token, the count of notification
/// permission requests and the number of the newest push registration.
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
  Future<void> _phoneWriteTail = Future<void>.value();

  /// Changes synchronously before any credential mutation awaits platform
  /// storage. Token refresh uses it to reject a response started by an older
  /// login, even when the next account signs in while that response is in
  /// flight.
  int get identityGeneration => _identityGeneration;

  /// Invalidates requests and refreshes belonging to the current login while
  /// retaining the bytes long enough for best-effort server sign-out.
  int invalidateIdentity() => ++_identityGeneration;

  /// True while nobody is signed in: requests then go without a bearer, even
  /// while the previous member's bytes are still stored for the server
  /// sign-out. Set by the session the moment it turns signed out, so a guest's
  /// first read never carries the member's token.
  bool bearerWithheld = false;

  static const _kAccess = 'auth.access';
  static const _kRefresh = 'auth.refresh';
  static const _kRoleContext = 'app.role_context';
  static const _kLocale = 'app.locale';
  static const _kInstallationId = 'push.installation_id';
  static const _kPendingPushToken = 'push.pending_token';
  static const _kPushPermissionRequests = 'push.permission_requests';
  static const _kPushBindingSequence = 'push.binding_sequence';

  /// The last profile the server confirmed for the stored credentials.
  ///
  /// Bound to them, not merely stored beside them: it is written only under
  /// the identity generation that fetched it, and every credential change —
  /// a new sign-in, a sign-out, a terminal expiry — deletes it. So a launch
  /// can never show one account's snapshot over another account's tokens.
  static const _kAccountSnapshot = 'auth.account_snapshot';

  /// Keys written by the retired build. Removed on every start.
  static const _legacyKeys = <String>['handover.codes', 'app.role'];

  Future<void> save({required String access, required String refresh}) {
    _identityGeneration++;
    return _serializeCredentialWrite(() async {
      await _storage.delete(key: _kAccountSnapshot);
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
    await _storage.delete(key: _kAccountSnapshot);
    await _storage.write(key: _kAccess, value: access);
    if (_identityGeneration != expectedIdentityGeneration) return false;
    await _storage.write(key: _kRefresh, value: refresh);
    return _identityGeneration == expectedIdentityGeneration;
  });

  /// The stored profile snapshot, read behind any pending credential write so
  /// it can never be one account's profile over another account's tokens.
  Future<String?> readAccountSnapshot() => _readCredential(_kAccountSnapshot);

  /// Stores [json] only if no credential change happened since
  /// [expectedIdentityGeneration] — the generation the profile was read under.
  Future<bool> writeAccountSnapshotIfCurrent({
    required int expectedIdentityGeneration,
    required String json,
  }) => _serializeCredentialWrite(() async {
    if (_identityGeneration != expectedIdentityGeneration) return false;
    await _storage.write(key: _kAccountSnapshot, value: json);
    return _identityGeneration == expectedIdentityGeneration;
  });

  /// Deleted at the very start of a sign-out, ahead of the network call.
  /// Serialized with the writes, so one queued before it cannot land after.
  Future<void> deleteAccountSnapshot() =>
      _serializeCredentialWrite(() => _storage.delete(key: _kAccountSnapshot));

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
  ///
  /// Created once: the read-then-write runs in the phone's write queue, so a
  /// startup registration and a token-refresh registration that both find the
  /// key empty share one UUID instead of each minting their own.
  Future<String> readOrCreateInstallationId() => _serializePhoneWrite(() async {
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
  });

  /// How many times this installation has asked the operating system for
  /// notification permission, from the app's first-open prompt or from Profile.
  ///
  /// Android 13+ reports a permission it was never asked for as a plain denial,
  /// so the system status alone cannot say whether the first-open prompt was
  /// spent; this count is the installation history that settles it. Like the
  /// installation ID it belongs to the phone, not the account: it survives
  /// logout, so the next person to sign in is never asked again.
  Future<int> readPushPermissionRequests() async =>
      int.tryParse(await _storage.read(key: _kPushPermissionRequests) ?? '') ??
      0;

  /// Counts one more request, to be written *before* the system is asked: a
  /// prompt interrupted by the app being killed still counts as spent.
  ///
  /// [afterDenial]: the system already holds a denial. An installation that
  /// counted nothing was asked by an app from before the count, so that
  /// earlier request is counted first and stays counted; taking this request
  /// back ([releasePushPermissionRequest]) leaves it.
  Future<int> recordPushPermissionRequest({bool afterDenial = false}) =>
      _serializePhoneWrite(() async {
        final current = await readPushPermissionRequests();
        final next = afterDenial && current < 1 ? 2 : current + 1;
        await _storage.write(key: _kPushPermissionRequests, value: '$next');
        return next;
      });

  /// Takes back a count whose system dialog never opened: the app left the
  /// screen between the count and the request, or the request itself failed.
  Future<int> releasePushPermissionRequest() =>
      _addToCounter(_kPushPermissionRequests, -1);

  /// The next number for a push registration or a sign-out of this
  /// installation. The server applies them in this order and refuses a request
  /// numbered below one it has already applied, so a registration that was
  /// slow on the network can never rebind the phone to an account that has
  /// since signed out or been replaced. Like the installation ID it belongs to
  /// the phone and only grows; it holds no account information.
  Future<int> nextPushBindingSequence() =>
      _addToCounter(_kPushBindingSequence, 1);

  /// Moves the counter up to at least [sequence], the newest number the server
  /// reported, so a phone whose counter was lost numbers its next request
  /// above everything the server has seen. Never lowers it.
  Future<void> raisePushBindingSequence(int sequence) => _serializePhoneWrite(
    () async {
      final current =
          int.tryParse(await _storage.read(key: _kPushBindingSequence) ?? '') ??
          0;
      if (sequence > current) {
        await _storage.write(key: _kPushBindingSequence, value: '$sequence');
      }
    },
  );

  Future<int> _addToCounter(String key, int delta) =>
      _serializePhoneWrite(() async {
        final current = int.tryParse(await _storage.read(key: key) ?? '') ?? 0;
        final next = current + delta < 0 ? 0 : current + delta;
        await _storage.write(key: key, value: '$next');
        return next;
      });

  /// The phone's own keys read, change and write, so two at once would lose one
  /// (a counter) or disagree (the installation ID).
  Future<T> _serializePhoneWrite<T>(Future<T> Function() operation) {
    final result = _phoneWriteTail.then((_) => operation());
    _phoneWriteTail = result.then<void>(
      (_) {},
      onError: (Object _, StackTrace _) {},
    );
    return result;
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
    await _storage.delete(key: _kAccountSnapshot);
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
