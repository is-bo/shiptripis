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
      headers: {
        'Content-Type': 'application/json',
        // ngrok's free tier serves an HTML interstitial to anything it thinks
        // is a browser; this header opts out. Harmless against any other host,
        // and it's the difference between JSON and an unparseable HTML body
        // when the dev tunnel is in play.
        'ngrok-skip-browser-warning': 'true',
      },
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
  Future<String?>? _refreshInFlight;

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
      final currentAccess = await _storage.readAccess();
      if (currentAccess != null &&
          req.headers['Authorization'] != 'Bearer $currentAccess') {
        // Another request already refreshed while this 401 was in flight.
        // Retry with the newer access token without rotating refresh again.
        req.extra['retried'] = true;
        req.headers['Authorization'] = 'Bearer $currentAccess';
        return handler.resolve(await _dio.fetch(req));
      }

      final refresh = await _storage.readRefresh();
      if (refresh == null) {
        await _storage.clear();
        return handler.next(response);
      }
      final access = await _refreshAccess(refresh);
      if (access != null) {
        // Every request that joined the same refresh retries with the one
        // rotated access token. This avoids blacklisting the refresh token
        // multiple times when several requests receive 401 together.
        req.extra['retried'] = true;
        req.headers['Authorization'] = 'Bearer $access';
        final retried = await _dio.fetch(req);
        return handler.resolve(retried);
      }

      // Do not erase credentials written by a newer login/refresh while this
      // request was in flight.
      if (await _storage.readRefresh() == refresh) {
        await _storage.clear();
      }
    }
    handler.next(response);
  }

  Future<String?> _refreshAccess(String refresh) async {
    final active = _refreshInFlight;
    if (active != null) return active;

    final future = _performRefresh(refresh);
    _refreshInFlight = future;
    try {
      return await future;
    } finally {
      if (identical(_refreshInFlight, future)) {
        _refreshInFlight = null;
      }
    }
  }

  Future<String?> _performRefresh(String refresh) async {
    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/api/auth/refresh',
        data: {'refresh': refresh},
      );
      final access = r.data?['access'];
      if (r.statusCode != 200 || access is! String) return null;

      final rotatedRefresh = r.data?['refresh'];
      if (rotatedRefresh is String) {
        await _storage.save(access: access, refresh: rotatedRefresh);
      } else {
        await _storage.updateAccess(access);
      }
      return access;
    } catch (_) {
      return null;
    }
  }
}
