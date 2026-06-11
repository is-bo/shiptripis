import 'package:dio/dio.dart';

import 'auth_storage.dart';

class AuthFailure implements Exception {
  AuthFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class AuthUser {
  AuthUser({
    required this.id,
    required this.email,
    required this.fullName,
    required this.phone,
    required this.wilaya,
    required this.role,
    required this.isKycVerified,
    required this.isPhoneVerified,
    required this.isEmailVerified,
    this.dateJoined,
  });

  factory AuthUser.fromJson(Map<String, dynamic> j) => AuthUser(
        id: j['id'] as int,
        email: j['email'] as String,
        fullName: (j['full_name'] as String?) ?? '',
        phone: (j['phone'] as String?) ?? '',
        wilaya: (j['wilaya'] as String?) ?? '',
        role: (j['role'] as String?) ?? 'sender',
        isKycVerified: (j['is_kyc_verified'] as bool?) ?? false,
        isPhoneVerified: (j['is_phone_verified'] as bool?) ?? false,
        isEmailVerified: (j['is_email_verified'] as bool?) ?? false,
        dateJoined: j['date_joined'] is String
            ? DateTime.tryParse(j['date_joined'] as String)
            : null,
      );

  final int id;
  final String email;
  final String fullName;
  final String phone;
  final String wilaya;
  final String role;
  final bool isKycVerified;
  final bool isPhoneVerified;
  final bool isEmailVerified;
  final DateTime? dateJoined;

  String get initials {
    final parts = fullName.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty || parts.first.isEmpty) {
      return email.isNotEmpty ? email[0].toUpperCase() : '?';
    }
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

class AuthRepository {
  AuthRepository(this._dio, this._storage);
  final Dio _dio;
  final AuthStorage _storage;

  Future<AuthUser> signUp({
    required String fullName,
    required String email,
    required String password,
    required String phone,
    required String wilaya,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/auth/sign-up',
      data: {
        'full_name': fullName,
        'email': email,
        'password': password,
        'phone': phone,
        'wilaya': wilaya,
      },
    );
    return _handleAuth(r);
  }

  Future<AuthUser> signIn({
    required String email,
    required String password,
  }) async {
    final r = await _dio.post<Map<String, dynamic>>(
      '/api/auth/sign-in',
      data: {'email': email, 'password': password},
    );
    return _handleAuth(r);
  }

  Future<void> signOut() async {
    final refresh = await _storage.readRefresh();
    if (refresh != null) {
      try {
        await _dio.post<dynamic>(
          '/api/auth/sign-out',
          data: {'refresh': refresh},
        );
      } catch (_) {/* ignore — clear locally regardless */}
    }
    await _storage.clear();
  }

  Future<AuthUser> me() async {
    final r = await _dio.get<Map<String, dynamic>>('/api/me');
    if (r.statusCode == 200 && r.data != null) {
      return AuthUser.fromJson(r.data!);
    }
    throw AuthFailure('Could not fetch profile.');
  }

  Future<void> requestPasswordReset(String email) async {
    // Server always returns 202 — don't surface enumeration signals.
    await _dio.post<dynamic>(
      '/api/auth/password/reset/request',
      data: {'email': email},
    );
  }

  Future<void> confirmPasswordReset({
    required String email,
    required String code,
    required String newPassword,
  }) async {
    final r = await _dio.post<dynamic>(
      '/api/auth/password/reset/confirm',
      data: {
        'email': email,
        'code': code,
        'new_password': newPassword,
      },
    );
    if (r.statusCode != 204) {
      throw AuthFailure(_extractMessage(r) ?? 'Invalid or expired code.');
    }
  }

  Future<AuthUser> _handleAuth(Response<Map<String, dynamic>> r) async {
    final data = r.data;
    if (r.statusCode == 200 || r.statusCode == 201) {
      if (data == null ||
          data['access'] is! String ||
          data['refresh'] is! String ||
          data['user'] is! Map) {
        throw AuthFailure('Unexpected response from server.');
      }
      await _storage.save(
        access: data['access'] as String,
        refresh: data['refresh'] as String,
      );
      return AuthUser.fromJson(Map<String, dynamic>.from(data['user'] as Map));
    }
    throw AuthFailure(_extractMessage(r) ?? 'Authentication failed.');
  }

  String? _extractMessage(Response r) {
    final d = r.data;
    if (d is Map) {
      if (d['detail'] is String) return d['detail'] as String;
      // DRF field errors: take the first string we find.
      for (final v in d.values) {
        if (v is List && v.isNotEmpty && v.first is String) {
          return v.first as String;
        }
        if (v is String) return v;
      }
    }
    return null;
  }
}
