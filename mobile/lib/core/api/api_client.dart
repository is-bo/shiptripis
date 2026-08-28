/// The HTTP client every repository talks through.
///
/// Responsibilities, and nothing beyond them:
///
/// * attach the access token, and refresh it exactly once per burst of 401s
/// * normalise every non-2xx response into an [ApiException]
/// * retry idempotent reads on transient network failure, with jitter
/// * never log anything that could carry a handover code, a guest token, a
///   recipient's details or an auth token
///
/// It deliberately does **not** cache. Deal state, capacity and money are
/// authoritative on the server, and a stale cached copy of any of them is a
/// correctness bug rather than a performance win.
///
/// The verb surface is shape-explicit — [getObject], [getList], [postVoid] —
/// instead of one generic method. The API returns bare arrays from some
/// endpoints and objects from others, and naming the expected shape at the
/// call site turns a contract drift into a clear `ApiFailureKind.malformed`
/// rather than a cast error thrown from inside a model constructor.
library;

import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';

import '../env/app_config.dart';
import '../session/token_store.dart';
import 'api_exception.dart';
import 'error_codes.dart';

/// Called when refresh has definitively failed and the session is over.
typedef OnSessionExpired = void Function();

typedef Json = Map<String, dynamic>;

class ApiClient {
  ApiClient({
    required TokenStore tokens,
    Dio? dio,
    OnSessionExpired? onSessionExpired,
  }) : _tokens = tokens,
       _dio = dio ?? Dio() {
    _dio.options = _dio.options.copyWith(
      baseUrl: AppConfig.apiBaseUrl,
      connectTimeout: AppConfig.connectTimeout,
      receiveTimeout: AppConfig.requestTimeout,
      sendTimeout: AppConfig.requestTimeout,
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        // ngrok's free tier serves an HTML interstitial to anything it thinks
        // is a browser. Harmless elsewhere, and the difference between JSON
        // and an unparseable body when a dev tunnel is in play.
        'ngrok-skip-browser-warning': 'true',
      },
      // 4xx is data, not an exception: the domain envelope on a 409 is often
      // the most useful thing in the response. Non-2xx becomes a typed
      // failure in `_send` instead.
      validateStatus: (s) => s != null && s < 500,
    );
    _dio.interceptors.add(_AuthInterceptor(_dio, _tokens, onSessionExpired));
  }

  final Dio _dio;
  final TokenStore _tokens;

  /// Escape hatch for the two places that need the raw client: multipart
  /// uploads built elsewhere, and tests that install a mock adapter.
  Dio get raw => _dio;

  // ---------------------------------------------------------------------------
  // Reads
  // ---------------------------------------------------------------------------

  Future<Json> getObject(
    String path, {
    Json? query,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      () => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
      ),
      // Only reads are retried. Replaying a POST could double-charge a card
      // or burn one of five handover-code attempts.
      retries: 2,
    ),
    path,
  );

  /// Several V1 list endpoints return a bare JSON array rather than a
  /// paginated envelope; others return `{"count", "results"}`. This unwraps
  /// both so repositories do not each re-implement the guess.
  Future<List<dynamic>> getList(
    String path, {
    Json? query,
    CancelToken? cancelToken,
  }) async {
    final data = await _send(
      () => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
      ),
      retries: 2,
    );
    if (data is List) return data;
    if (data is Map) {
      final results = data['results'];
      if (results is List) return results;
    }
    throw _malformed('a list', data, path);
  }

  // ---------------------------------------------------------------------------
  // Writes
  // ---------------------------------------------------------------------------

  Future<Json> postObject(
    String path, {
    Object? body,
    Json? query,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      () => _dio.post<dynamic>(
        path,
        data: body,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
      ),
    ),
    path,
  );

  /// For endpoints whose success is a 204, or whose body the caller ignores.
  Future<void> postVoid(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async {
    await _send(
      () => _dio.post<dynamic>(path, data: body, cancelToken: cancelToken),
    );
  }

  Future<Json> patchObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      () => _dio.patch<dynamic>(path, data: body, cancelToken: cancelToken),
    ),
    path,
  );

  Future<Json> putObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      () => _dio.put<dynamic>(path, data: body, cancelToken: cancelToken),
    ),
    path,
  );

  Future<void> deleteVoid(String path, {CancelToken? cancelToken}) async {
    await _send(() => _dio.delete<dynamic>(path, cancelToken: cancelToken));
  }

  /// Multipart upload — parcel photos, dispute evidence, flight proof.
  ///
  /// [onProgress] drives a real progress bar. A 25 MiB video on a mobile
  /// connection needs one, and a spinner for ninety seconds is not a state.
  Future<Json> upload(
    String path, {
    required FormData form,
    void Function(int sent, int total)? onProgress,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      () => _dio.post<dynamic>(
        path,
        data: form,
        cancelToken: cancelToken,
        onSendProgress: onProgress,
        options: Options(
          contentType: 'multipart/form-data',
          // An upload is bounded by bandwidth, not by server think-time.
          sendTimeout: const Duration(minutes: 5),
          receiveTimeout: const Duration(minutes: 2),
        ),
      ),
    ),
    path,
  );

  // ---------------------------------------------------------------------------
  // Plumbing
  // ---------------------------------------------------------------------------

  Future<dynamic> _send(
    Future<Response<dynamic>> Function() call, {
    int retries = 0,
  }) async {
    var attempt = 0;
    while (true) {
      try {
        final response = await call();
        final status = response.statusCode ?? 0;
        if (status >= 200 && status < 300) return response.data;
        throw ApiException.fromResponse(response);
      } on ApiException {
        rethrow;
      } catch (error, stack) {
        final failure = ApiException.from(error, stack);
        final canRetry =
            attempt < retries &&
            (failure.kind == ApiFailureKind.offline ||
                failure.kind == ApiFailureKind.timeout);
        if (!canRetry) throw failure;

        // Exponential backoff with full jitter. Without the jitter every
        // screen that woke together on reconnect would retry in lockstep and
        // arrive at the server as one spike.
        final ceiling = 400 * (1 << attempt);
        await Future<void>.delayed(
          Duration(milliseconds: ceiling ~/ 2 + _random.nextInt(ceiling ~/ 2 + 1)),
        );
        attempt++;
      }
    }
  }

  static Json _expectObject(dynamic data, String path) {
    if (data is Map<String, dynamic>) return data;
    if (data is Map) return Map<String, dynamic>.from(data);
    // A 204 answering a POST whose caller wanted a body is a contract change
    // worth surfacing rather than silently treating as `{}`.
    throw _malformed('an object', data, path);
  }

  static ApiException _malformed(String expected, dynamic got, String path) =>
      ApiException(
        kind: ApiFailureKind.malformed,
        code: ApiErrorCode.unknown,
        serverDetail:
            'Expected $expected from $path but received ${got.runtimeType}.',
      );

  /// Drops null query values so `?kg=null` never reaches the server.
  static Json? _clean(Json? query) {
    if (query == null) return null;
    final out = <String, dynamic>{};
    for (final entry in query.entries) {
      if (entry.value != null) out[entry.key] = entry.value;
    }
    return out.isEmpty ? null : out;
  }

  static final _random = Random();
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

class _AuthInterceptor extends Interceptor {
  _AuthInterceptor(this._dio, this._tokens, this._onExpired);

  final Dio _dio;
  final TokenStore _tokens;
  final OnSessionExpired? _onExpired;

  /// Shared across every 401 in flight, so a burst of parallel requests
  /// rotates the refresh token once instead of racing and blacklisting it.
  Future<String?>? _refreshInFlight;

  static const _authPaths = [
    '/api/auth/sign-in',
    '/api/auth/sign-up',
    '/api/auth/refresh',
    '/api/auth/oauth/',
    '/api/auth/password/reset/',
  ];

  static bool _isAuthEndpoint(String path) => _authPaths.any(path.contains);

  /// The guest payment surface is deliberately unauthenticated. Sending a
  /// signed-in user's bearer token to it would attach an identity the guest
  /// flow exists specifically not to have.
  static bool _isGuestEndpoint(String path) =>
      path.contains('/api/payments/guest/');

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    if (!_isAuthEndpoint(options.path) && !_isGuestEndpoint(options.path)) {
      final access = await _tokens.readAccess();
      if (access != null) options.headers['Authorization'] = 'Bearer $access';
    }
    handler.next(options);
  }

  @override
  Future<void> onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) async {
    final request = response.requestOptions;
    final shouldRefresh =
        response.statusCode == 401 &&
        !_isAuthEndpoint(request.path) &&
        !_isGuestEndpoint(request.path) &&
        request.extra['st.retried'] != true;

    if (!shouldRefresh) return handler.next(response);

    // Another request may have refreshed while this 401 was in flight. If the
    // stored token is already newer than the one we sent, just replay.
    final current = await _tokens.readAccess();
    if (current != null &&
        request.headers['Authorization'] != 'Bearer $current') {
      return handler.resolve(await _replay(request, current));
    }

    final refresh = await _tokens.readRefresh();
    if (refresh == null) {
      await _endSession();
      return handler.next(response);
    }

    final rotated = await _refreshOnce(refresh);
    if (rotated != null) {
      return handler.resolve(await _replay(request, rotated));
    }

    // Do not wipe credentials that a newer sign-in wrote while this was in
    // flight.
    if (await _tokens.readRefresh() == refresh) await _endSession();
    handler.next(response);
  }

  Future<Response<dynamic>> _replay(RequestOptions request, String access) {
    request.extra['st.retried'] = true;
    request.headers['Authorization'] = 'Bearer $access';
    return _dio.fetch<dynamic>(request);
  }

  Future<String?> _refreshOnce(String refresh) {
    final active = _refreshInFlight;
    if (active != null) return active;

    final future = _performRefresh(refresh);
    _refreshInFlight = future;
    return future.whenComplete(() {
      if (identical(_refreshInFlight, future)) _refreshInFlight = null;
    });
  }

  Future<String?> _performRefresh(String refresh) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/api/auth/refresh',
        data: {'refresh': refresh},
      );
      if (response.statusCode != 200) return null;

      final access = response.data?['access'];
      if (access is! String) return null;

      final rotated = response.data?['refresh'];
      if (rotated is String) {
        await _tokens.save(access: access, refresh: rotated);
      } else {
        await _tokens.updateAccess(access);
      }
      return access;
    } catch (_) {
      return null;
    }
  }

  Future<void> _endSession() async {
    await _tokens.clear();
    _onExpired?.call();
  }
}
