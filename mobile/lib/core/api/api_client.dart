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
    _auth = _AuthInterceptor(_dio, _tokens, onSessionExpired);
    _dio.interceptors.add(_auth);
  }

  final Dio _dio;
  final TokenStore _tokens;
  late final _AuthInterceptor _auth;

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
      (identity) => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(identity),
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
      (identity) => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(identity),
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
      (identity) => _dio.post<dynamic>(
        path,
        data: body,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(identity),
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
      (identity) => _dio.post<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(identity),
      ),
    );
  }

  Future<Json> patchObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      (identity) => _dio.patch<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(identity),
      ),
    ),
    path,
  );

  Future<Json> putObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _send(
      (identity) => _dio.put<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(identity),
      ),
    ),
    path,
  );

  Future<void> deleteVoid(String path, {CancelToken? cancelToken}) async {
    await _send(
      (identity) => _dio.delete<dynamic>(
        path,
        cancelToken: cancelToken,
        options: _requestOptions(identity),
      ),
    );
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
      (identity) => _dio.post<dynamic>(
        path,
        data: form,
        cancelToken: cancelToken,
        onSendProgress: onProgress,
        options: Options(
          contentType: 'multipart/form-data',
          extra: {'st.identity_generation': identity},
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
    Future<Response<dynamic>> Function(int identityGeneration) call, {
    int retries = 0,
  }) async {
    final identityGeneration = _tokens.identityGeneration;
    final budget = Stopwatch()..start();
    var attempt = 0;
    while (true) {
      try {
        if (identityGeneration != _tokens.identityGeneration) {
          throw _AuthInterceptor.sessionChanged();
        }
        final response = await call(identityGeneration);
        if (identityGeneration != _tokens.identityGeneration) {
          throw _AuthInterceptor.sessionChanged(response.requestOptions);
        }
        final status = response.statusCode ?? 0;
        if (status >= 200 && status < 300) return response.data;
        throw ApiException.fromResponse(response);
      } on ApiException {
        rethrow;
      } catch (error, stack) {
        final failure = ApiException.from(error, stack);
        final canRetry =
            attempt < retries &&
            // A retry that starts after the budget is spent cannot finish
            // inside it. Stopping here is what bounds the whole read rather
            // than only each attempt of it.
            budget.elapsed < AppConfig.requestBudget &&
            (failure.kind == ApiFailureKind.offline ||
                failure.kind == ApiFailureKind.timeout);
        if (!canRetry) throw failure;

        // Exponential backoff with full jitter. Without the jitter every
        // screen that woke together on reconnect would retry in lockstep and
        // arrive at the server as one spike.
        final ceiling = 400 * (1 << attempt);
        await Future<void>.delayed(
          Duration(
            milliseconds: ceiling ~/ 2 + _random.nextInt(ceiling ~/ 2 + 1),
          ),
        );
        if (identityGeneration != _tokens.identityGeneration) {
          throw ApiException.from(_AuthInterceptor.sessionChanged());
        }
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

  Options _requestOptions(int identityGeneration) =>
      Options(extra: {'st.identity_generation': identityGeneration});

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
  int? _refreshGeneration;

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
      final existingIdentity = options.extra['st.identity_generation'];
      final identityGeneration = existingIdentity is int
          ? existingIdentity
          : _tokens.identityGeneration;
      options.extra['st.identity_generation'] = identityGeneration;
      if (identityGeneration != _tokens.identityGeneration) {
        return handler.reject(sessionChanged(options));
      }
      final access = await _tokens.readAccess();
      if (identityGeneration != _tokens.identityGeneration) {
        return handler.reject(sessionChanged(options));
      }
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
        !request.path.contains('/api/auth/sign-out') &&
        !_isGuestEndpoint(request.path) &&
        request.extra['st.retried'] != true;

    if (!shouldRefresh) return handler.next(response);

    final requestIdentity = request.extra['st.identity_generation'];
    if (requestIdentity is! int ||
        requestIdentity != _tokens.identityGeneration) {
      // This response belongs to the account that was logged out while the
      // request was in flight. Replaying it with the next account's bearer
      // could perform the old user's action as the new user.
      return handler.next(response);
    }

    // Another request may have refreshed while this 401 was in flight. If the
    // stored token is already newer than the one we sent, just replay.
    final current = await _tokens.readAccess();
    if (requestIdentity != _tokens.identityGeneration) {
      return handler.next(response);
    }
    if (current != null &&
        request.headers['Authorization'] != 'Bearer $current') {
      return _resolveReplay(handler, request, current, requestIdentity);
    }

    final refresh = await _tokens.readRefresh();
    if (requestIdentity != _tokens.identityGeneration) {
      return handler.next(response);
    }
    if (refresh == null) {
      await _endSession(expectedIdentityGeneration: requestIdentity);
      return handler.next(response);
    }

    final rotated = await _refreshOnce(refresh, requestIdentity);
    if (rotated != null && requestIdentity == _tokens.identityGeneration) {
      return _resolveReplay(handler, request, rotated, requestIdentity);
    }

    // Do not wipe credentials that a newer sign-in wrote while this was in
    // flight.
    if (_tokens.identityGeneration == requestIdentity &&
        await _tokens.readRefresh() == refresh &&
        _tokens.identityGeneration == requestIdentity) {
      await _endSession(
        expectedIdentityGeneration: requestIdentity,
        expectedRefresh: refresh,
      );
    }
    handler.next(response);
  }

  Future<void> _resolveReplay(
    ResponseInterceptorHandler handler,
    RequestOptions request,
    String access,
    int identityGeneration,
  ) async {
    try {
      handler.resolve(await _replay(request, access, identityGeneration));
    } on DioException catch (error) {
      handler.reject(error);
    } catch (error, stackTrace) {
      handler.reject(
        DioException(
          requestOptions: request,
          error: error,
          stackTrace: stackTrace,
        ),
      );
    }
  }

  Future<Response<dynamic>> _replay(
    RequestOptions request,
    String access,
    int identityGeneration,
  ) {
    if (identityGeneration != _tokens.identityGeneration) {
      return Future<Response<dynamic>>.error(sessionChanged(request));
    }
    request.extra['st.retried'] = true;
    request.extra['st.identity_generation'] = identityGeneration;
    request.headers['Authorization'] = 'Bearer $access';
    return _dio.fetch<dynamic>(request);
  }

  static DioException sessionChanged([RequestOptions? request]) => DioException(
    requestOptions: request ?? RequestOptions(),
    type: DioExceptionType.cancel,
    error: StateError('The authenticated session changed.'),
  );

  Future<String?> _refreshOnce(String refresh, int identityGeneration) {
    final active = _refreshInFlight;
    if (active != null && _refreshGeneration == identityGeneration) {
      return active;
    }

    final future = _performRefresh(refresh, identityGeneration);
    _refreshInFlight = future;
    _refreshGeneration = identityGeneration;
    return future.whenComplete(() {
      if (identical(_refreshInFlight, future)) {
        _refreshInFlight = null;
        _refreshGeneration = null;
      }
    });
  }

  Future<String?> _performRefresh(
    String refresh,
    int identityGeneration,
  ) async {
    try {
      final response = await _dio.post<Map<String, dynamic>>(
        '/api/auth/refresh',
        data: {'refresh': refresh},
      );
      if (response.statusCode != 200) return null;

      final access = response.data?['access'];
      if (access is! String) return null;

      // A logout or another login happened while the network request was in
      // flight. Never let this older refresh overwrite the new credentials.
      final rotated = response.data?['refresh'];
      final saved = await _tokens.saveRefreshedIfCurrent(
        expectedIdentityGeneration: identityGeneration,
        expectedRefresh: refresh,
        access: access,
        refresh: rotated is String ? rotated : null,
      );
      return saved ? access : null;
    } catch (_) {
      return null;
    }
  }

  Future<void> _endSession({
    required int expectedIdentityGeneration,
    String? expectedRefresh,
  }) async {
    if (_tokens.identityGeneration != expectedIdentityGeneration) return;
    if (expectedRefresh != null &&
        await _tokens.readRefresh() != expectedRefresh) {
      return;
    }
    if (await _tokens.clearIfIdentityCurrent(expectedIdentityGeneration)) {
      _onExpired?.call();
    }
  }
}
