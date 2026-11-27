/// Where the pending-pick marker of `PickGuard` is kept.
///
/// The marker (a purpose and a nonce: nothing secret) is written before a
/// picker opens and cleared when it answers. If the phone ends the app while the
/// picker is open it is still there at the next launch, which is how the next
/// pick learns that an earlier one never ended.
///
/// That only works if a write that reports success is on the disk. On Android
/// `flutter_secure_storage` writes through `SharedPreferences.Editor.apply()`,
/// which answers before the disk is written and cannot report a failure, so
/// there the marker goes through `wassla/pick_marker` (`PickMarkerStore.kt`),
/// which uses `commit()` and answers whether the disk took it. Everywhere else
/// the keychain write is synchronous and secure storage is used.
///
/// Every method throws when the change could not be made; the pick then does
/// not open its picker.
library;

import 'dart:io' show Platform;

import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract interface class PendingPickStore {
  Future<String?> read();

  /// Makes [marker] the pending pick and answers the one it replaced.
  Future<String?> exchange(String marker);

  /// Clears the pending pick, but only while it is still [marker].
  Future<void> release(String marker);

  /// A pick still open at sign-out names nobody: a marker, if there is one,
  /// becomes the bare [closedBySignOut].
  Future<void> closeBySignOut();

  /// What a marker becomes when the member signs out with a picker open.
  static const closedBySignOut = 'signed-out';

  /// The store this platform can trust: committed writes on Android, secure
  /// storage elsewhere.
  static PendingPickStore forPlatform(FlutterSecureStorage storage) =>
      Platform.isAndroid
      ? const CommittedPendingPickStore()
      : SecurePendingPickStore(storage);
}

/// The marker in secure storage, as the keychain keeps it.
class SecurePendingPickStore implements PendingPickStore {
  const SecurePendingPickStore(this._storage);

  final FlutterSecureStorage _storage;

  static const key = 'media.pending_pick';

  @override
  Future<String?> read() => _storage.read(key: key);

  @override
  Future<String?> exchange(String marker) async {
    final previous = await _storage.read(key: key);
    await _storage.write(key: key, value: marker);
    return previous;
  }

  @override
  Future<void> release(String marker) async {
    if (await _storage.read(key: key) == marker) {
      await _storage.delete(key: key);
    }
  }

  @override
  Future<void> closeBySignOut() async {
    if (await _storage.read(key: key) != null) {
      await _storage.write(key: key, value: PendingPickStore.closedBySignOut);
    }
  }
}

/// The marker in Android preferences, every change committed to the disk.
class CommittedPendingPickStore implements PendingPickStore {
  const CommittedPendingPickStore([
    this._channel = const MethodChannel('wassla/pick_marker'),
  ]);

  final MethodChannel _channel;

  @override
  Future<String?> read() => _channel.invokeMethod<String>('read');

  @override
  Future<String?> exchange(String marker) =>
      _channel.invokeMethod<String>('exchange', {'marker': marker});

  @override
  Future<void> release(String marker) =>
      _channel.invokeMethod<void>('release', {'marker': marker});

  @override
  Future<void> closeBySignOut() =>
      _channel.invokeMethod<void>('closeBySignOut');
}
