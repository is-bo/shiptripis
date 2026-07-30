import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/dio_client.dart';
import '../state/role_provider.dart';
import 'auth_repository.dart';
import 'auth_storage.dart';

final authStorageProvider = Provider<AuthStorage>((ref) => AuthStorage());

final dioProvider = Provider<Dio>((ref) {
  return buildDioClient(ref.read(authStorageProvider));
});

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  return AuthRepository(ref.read(dioProvider), ref.read(authStorageProvider));
});

sealed class AuthState {
  const AuthState();
}

class AuthInitial extends AuthState {
  const AuthInitial();
}

class AuthLoading extends AuthState {
  const AuthLoading();
}

class AuthSignedIn extends AuthState {
  const AuthSignedIn(this.user);
  final AuthUser user;
}

class AuthSignedOut extends AuthState {
  const AuthSignedOut();
}

class AuthError extends AuthState {
  const AuthError(this.message);
  final String message;
}

class AuthNotifier extends Notifier<AuthState> {
  late final AuthRepository _repo;
  late final AuthStorage _storage;

  @override
  AuthState build() {
    _repo = ref.read(authRepositoryProvider);
    _storage = ref.read(authStorageProvider);
    return const AuthInitial();
  }

  Future<void> bootstrap() async {
    final access = await _storage.readAccess();
    if (access == null) {
      state = const AuthSignedOut();
      return;
    }
    state = const AuthLoading();
    try {
      final user = await _repo.me();
      // Seed the saved UI role BEFORE the shell mounts so "both" users don't
      // see a first-frame flip (pure roles are server-locked downstream).
      // Reading roleProvider.notifier here also triggers RoleNotifier.build()
      // → _hydrate(), which reads the same storage key and lands on the same
      // value, so there's no late flip that would undo this seed.
      final savedRole = await _storage.readRole();
      if (savedRole == 'traveler') {
        ref.read(roleProvider.notifier).seed(AppRole.traveler);
      } else if (savedRole == 'sender') {
        ref.read(roleProvider.notifier).seed(AppRole.sender);
      }
      state = AuthSignedIn(user);
    } catch (_) {
      await _storage.clear();
      state = const AuthSignedOut();
    }
  }

  /// Re-read `/me` and swap the cached user in place. Used after a flow that
  /// changes server-side profile flags (e.g. a KYC submission that flips
  /// `is_kyc_verified`) so badges update without a restart. Deliberately
  /// silent: a failure leaves the existing user alone rather than bouncing
  /// the session, since the caller's own operation already succeeded.
  Future<void> refreshUser() async {
    if (state is! AuthSignedIn) return;
    try {
      state = AuthSignedIn(await _repo.me());
    } catch (_) {
      // Keep the current user; the caller's flow isn't invalidated by this.
    }
  }

  Future<bool> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    required String wilaya,
  }) async {
    state = const AuthLoading();
    try {
      final user = await _repo.signUp(
        fullName: fullName,
        email: email,
        password: password,
        phone: phone,
        wilaya: wilaya,
      );
      state = AuthSignedIn(user);
      return true;
    } on AuthFailure catch (e) {
      state = AuthError(e.message);
      return false;
    } catch (e) {
      state = AuthError('Network error. Check your connection.');
      return false;
    }
  }

  Future<bool> signIn({required String email, required String password}) async {
    state = const AuthLoading();
    try {
      final user = await _repo.signIn(email: email, password: password);
      state = AuthSignedIn(user);
      return true;
    } on AuthFailure catch (e) {
      state = AuthError(e.message);
      return false;
    } catch (e) {
      state = AuthError('Network error. Check your connection.');
      return false;
    }
  }

  Future<void> signOut() async {
    await _repo.signOut();
    state = const AuthSignedOut();
  }

  Future<void> requestPasswordReset(String email) async {
    try {
      await _repo.requestPasswordReset(email);
    } catch (_) {/* server is always 202; swallow network errors quietly */}
  }

  Future<bool> confirmPasswordReset({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    try {
      await _repo.confirmPasswordReset(
        email: email,
        code: code,
        newPassword: newPassword,
      );
      return true;
    } on AuthFailure catch (e) {
      state = AuthError(e.message);
      return false;
    } catch (_) {
      state = const AuthError('Network error. Check your connection.');
      return false;
    }
  }
}

final authNotifierProvider = NotifierProvider<AuthNotifier, AuthState>(
  AuthNotifier.new,
);
