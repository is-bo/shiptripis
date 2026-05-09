import 'package:dio/dio.dart';

import '../auth/auth_storage.dart';
import '../config/api_config.dart';

/// Builds the app-wide Dio client with a JWT auth + refresh interceptor.
///
/// Behavior:
/// - Attaches `Authorization: Bearer <access>` if we have one.
/// - On 401, tries `/api/auth/refresh` once with the stored refresh token.
///   If refresh succeeds, retries the original request. Otherwise, clears
///   tokens (caller should redirect to sign-in via auth state).
Dio buildDioClient(AuthStorage storage) {
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConfig.baseUrl,
      connectTimeout: const Duration(seconds: 10),
      receiveTimeout: const Duration(seconds: 15),
      headers: {'Content-Type': 'application/json'},
      // Don't throw on 4xx — let callers inspect the response.
      validateStatus: (s) => s != null && s < 500,
    ),
  );

  dio.interceptors.add(_AuthInterceptor(dio, storage));
  return dio;
}

class _AuthInterceptor extends Interceptor {
  _AuthInterceptor(this._dio, this._storage);
  final Dio _dio;
  final AuthStorage _storage;

  bool _isAuthEndpoint(String path) {
    return path.contains('/api/auth/sign-in') ||
        path.contains('/api/auth/sign-up') ||
        path.contains('/api/auth/refresh') ||
        path.contains('/api/auth/oauth/') ||
        path.contains('/api/auth/password/reset/');
  }

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (!_isAuthEndpoint(options.path)) {
      final access = await _storage.readAccess();
      if (access != null) {
        options.headers['Authorization'] = 'Bearer $access';
      }
    }
    handler.next(options);
  }

  @override
  Future<void> onResponse(
    Response response,
    ResponseInterceptorHandler handler,
  ) async {
    final req = response.requestOptions;
    if (response.statusCode == 401 &&
        !_isAuthEndpoint(req.path) &&
        req.extra['retried'] != true) {
      final refresh = await _storage.readRefresh();
      if (refresh == null) {
        await _storage.clear();
        return handler.next(response);
      }
      try {
        final r = await _dio.post<Map<String, dynamic>>(
          '/api/auth/refresh',
          data: {'refresh': refresh},
        );
        if (r.statusCode == 200 && r.data?['access'] is String) {
          await _storage.updateAccess(r.data!['access'] as String);
          if (r.data?['refresh'] is String) {
            await _storage.save(
              access: r.data!['access'] as String,
              refresh: r.data!['refresh'] as String,
            );
          }
          // Retry original request with the new token.
          req.extra['retried'] = true;
          req.headers['Authorization'] =
              'Bearer ${await _storage.readAccess()}';
          final retried = await _dio.fetch(req);
          return handler.resolve(retried);
        }
      } catch (_) {
        // Fall through to clear + propagate 401.
      }
      await _storage.clear();
    }
    handler.next(response);
  }
}
