import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/dio_client.dart';
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
      state = AuthSignedIn(user);
    } catch (_) {
      await _storage.clear();
      state = const AuthSignedOut();
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
