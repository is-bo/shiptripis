import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class AuthStorage {
  AuthStorage([FlutterSecureStorage? storage])
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  static const _kAccess = 'auth.access';
  static const _kRefresh = 'auth.refresh';
  static const _kRole = 'app.role';

  Future<void> save({required String access, required String refresh}) async {
    await _storage.write(key: _kAccess, value: access);
    await _storage.write(key: _kRefresh, value: refresh);
  }

  Future<String?> readAccess() => _storage.read(key: _kAccess);
  Future<String?> readRefresh() => _storage.read(key: _kRefresh);

  Future<void> updateAccess(String access) =>
      _storage.write(key: _kAccess, value: access);

  // Local-only override for users whose server role is "both". Survives
  // restarts so a traveler who picked "Travel" on onboarding doesn't get
  // dropped into the sender UI on next launch.
  Future<String?> readRole() => _storage.read(key: _kRole);
  Future<void> writeRole(String role) =>
      _storage.write(key: _kRole, value: role);

  Future<void> clear() async {
    await _storage.delete(key: _kAccess);
    await _storage.delete(key: _kRefresh);
    await _storage.delete(key: _kRole);
  }
}
