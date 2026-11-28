/// The HTTP client every repository talks through.
///
/// Responsibilities, and nothing beyond them:
///
/// * attach the access token, and refresh it exactly once per burst of 401s
/// * normalise every non-2xx response into an [ApiException]
/// * retry idempotent reads on transient network failure, with jitter
/// * send an opted-in read once when several callers ask for it at once
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
import '../session/session_core.dart';
import 'api_exception.dart';
import 'error_codes.dart';

typedef Json = Map<String, dynamic>;

class ApiClient {
  ApiClient({required SessionCore session, Dio? dio})
    : _session = session,
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
    _dio.interceptors.add(_AuthInterceptor(_dio, _session));
  }

  final Dio _dio;
  final SessionCore _session;

  /// Shared reads in flight, by sign-in, write epoch, path and query.
  final Map<String, _SharedRead> _sharedReads = {};

  /// Moves when any write starts and again when it ends, so a read asked for
  /// after a write never shares one that began before it and may have missed
  /// its effect.
  int _writeEpoch = 0;

  /// Escape hatch for the two places that need the raw client: multipart
  /// uploads built elsewhere, and tests that install a mock adapter.
  Dio get raw => _dio;

  // ---------------------------------------------------------------------------
  // Reads
  // ---------------------------------------------------------------------------

  /// [share] lets identical reads in flight at the same time go out as one
  /// request (K5): the read joins one already in flight for the same sign-in,
  /// or starts one later shared reads may join. [fresh] still starts a new
  /// one, for a caller whose reason to ask — a live event — may postdate the
  /// read in flight. Only for small reads several callers ask for at once.
  Future<Json> getObject(
    String path, {
    Json? query,
    CancelToken? cancelToken,
    bool share = false,
    bool fresh = false,
  }) async {
    Future<dynamic> read(CancelToken? token) => _send(
      (sid) => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: token,
        options: _requestOptions(sid),
      ),
      // Only reads are retried. Replaying a POST could double-charge a card
      // or burn one of five handover-code attempts.
      retries: 2,
    );
    return _expectObject(
      share
          ? await _shared(path, query, cancelToken, read, fresh: fresh)
          : await read(cancelToken),
      path,
    );
  }

  /// Several V1 list endpoints return a bare JSON array rather than a
  /// paginated envelope; others return `{"count", "results"}`. This unwraps
  /// both so repositories do not each re-implement the guess.
  Future<List<dynamic>> getList(
    String path, {
    Json? query,
    CancelToken? cancelToken,
  }) async {
    final data = await _send(
      (sid) => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(sid),
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

  /// One page of a collection, in either of the server's two paging shapes.
  ///
  /// DRF envelopes (`{"count", "next", "results"}`) say whether more follows
  /// in the body; the K4 bare-array collections say it in `X-Next-Page`.
  /// [getList] reads only the first page of either, which is how a user with
  /// more than one page of Deals silently lost the older ones (K5).
  Future<ListPage> getListPage(
    String path, {
    Json? query,
    CancelToken? cancelToken,
  }) async {
    final response = await _sendResponse(
      (sid) => _dio.get<dynamic>(
        path,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(sid),
      ),
      retries: 2,
    );
    final data = response.data;
    if (data is List) {
      return ListPage(
        rows: data,
        hasNext: response.headers.value('x-next-page') != null,
        total: int.tryParse(response.headers.value('x-total-count') ?? ''),
      );
    }
    if (data is Map && data['results'] is List) {
      final count = data['count'];
      return ListPage(
        rows: data['results'] as List,
        hasNext: data['next'] != null,
        total: count is int ? count : null,
      );
    }
    throw _malformed('a list', data, path);
  }

  /// Every row of an account's own, naturally bounded collection.
  ///
  /// For sets that stay small by construction — current Deals, a sender's own
  /// requests, a traveller's own journeys — where a screen needs the whole set
  /// to be correct. Not for history or search: those page lazily. [maxPages]
  /// is a safety bound against a server that never stops saying "next"; at
  /// 100 rows a page it is far past any real account.
  ///
  /// Rows carrying an `id` appear once, first read wins: over newest-first
  /// page numbers, a row created between two reads pushes the rest down one,
  /// so the next page can repeat the last row of this one.
  Future<List<dynamic>> getAllPages(
    String path, {
    Json? query,
    int pageSize = 100,
    int maxPages = 10,
    CancelToken? cancelToken,
  }) async {
    final rows = <dynamic>[];
    final seen = <Object>{};
    for (var page = 1; page <= maxPages; page++) {
      final result = await getListPage(
        path,
        query: {...?query, 'page_size': pageSize, if (page > 1) 'page': page},
        cancelToken: cancelToken,
      );
      for (final row in result.rows) {
        final id = row is Map ? row['id'] : null;
        if (id == null || seen.add(id)) rows.add(row);
      }
      if (!result.hasNext) break;
    }
    return rows;
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
    await _write(
      (sid) => _dio.post<dynamic>(
        path,
        data: body,
        queryParameters: _clean(query),
        cancelToken: cancelToken,
        options: _requestOptions(sid),
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
    await _write(
      (sid) => _dio.post<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(sid),
      ),
    );
  }

  /// For `DELETE` endpoints, whose success is a 204.
  Future<void> deleteVoid(String path, {CancelToken? cancelToken}) async {
    await _write(
      (sid) => _dio.delete<dynamic>(
        path,
        cancelToken: cancelToken,
        options: _requestOptions(sid),
      ),
    );
  }

  Future<Json> patchObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _write(
      (sid) => _dio.patch<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(sid),
      ),
    ),
    path,
  );

  Future<Json> putObject(
    String path, {
    Object? body,
    CancelToken? cancelToken,
  }) async => _expectObject(
    await _write(
      (sid) => _dio.put<dynamic>(
        path,
        data: body,
        cancelToken: cancelToken,
        options: _requestOptions(sid),
      ),
    ),
    path,
  );

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
    await _write(
      (sid) => _dio.post<dynamic>(
        path,
        data: form,
        cancelToken: cancelToken,
        onSendProgress: onProgress,
        options: Options(
          contentType: 'multipart/form-data',
          extra: {_AuthInterceptor.signInKey: sid},
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
    Future<Response<dynamic>> Function(String? sid) call, {
    int retries = 0,
  }) async => (await _sendResponse(call, retries: retries)).data;

  /// Every write goes through here, never retried and never shared.
  Future<dynamic> _write(
    Future<Response<dynamic>> Function(String? sid) call,
  ) async {
    _writeEpoch++;
    try {
      return await _send(call);
    } finally {
      _writeEpoch++;
    }
  }

  /// Joins an identical shared read in flight, or starts one.
  ///
  /// The read runs on its own token. Each caller may leave on its own
  /// [caller] token without cancelling it for the others; it is cancelled
  /// only once every caller has left, and then forgotten, so the next caller
  /// starts afresh. A failure reaches every caller and is never remembered.
  /// The key carries the sign-in, so a read begun for one sign-in is never
  /// handed to the next.
  Future<dynamic> _shared(
    String path,
    Json? query,
    CancelToken? caller,
    Future<dynamic> Function(CancelToken token) read, {
    required bool fresh,
  }) {
    final key = '${_session.current?.sid}:$_writeEpoch $path ${_clean(query)}';
    var shared = fresh ? null : _sharedReads[key];
    if (shared == null) {
      final created = shared = _SharedRead(CancelToken());
      _sharedReads[key] = created;
      created.result = read(created.token).whenComplete(() {
        if (identical(_sharedReads[key], created)) _sharedReads.remove(key);
      });
    }
    final joined = shared;
    return joined.join(
      caller,
      path: path,
      onAbandoned: () {
        if (identical(_sharedReads[key], joined)) _sharedReads.remove(key);
      },
    );
  }

  /// Sends [call] for the sign-in current now, or as a guest when nobody is
  /// signed in. A member's answer that arrives after that sign-in ended is
  /// refused as "session changed": it belongs to someone who has left. A
  /// guest's read carried no bearer and belongs to no sign-in, so a sign-in
  /// finishing meanwhile does not void it.
  Future<Response<dynamic>> _sendResponse(
    Future<Response<dynamic>> Function(String? sid) call, {
    int retries = 0,
  }) async {
    final sid = _session.current?.sid;
    final budget = Stopwatch()..start();
    var attempt = 0;
    while (true) {
      try {
        if (sid != _session.current?.sid) {
          throw _AuthInterceptor.sessionChanged();
        }
        final response = await call(sid);
        if (sid != null && sid != _session.current?.sid) {
          throw _AuthInterceptor.sessionChanged(response.requestOptions);
        }
        final status = response.statusCode ?? 0;
        if (status >= 200 && status < 300) return response;
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
        if (sid != _session.current?.sid) {
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

  Options _requestOptions(String? sid) =>
      Options(extra: {_AuthInterceptor.signInKey: sid});

  static final _random = Random();
}

/// One shared read in flight and the callers waiting on it.
class _SharedRead {
  _SharedRead(this.token);

  final CancelToken token;
  late final Future<dynamic> result;
  int _waiting = 0;
  int _joined = 0;

  Future<dynamic> join(
    CancelToken? caller, {
    required String path,
    required void Function() onAbandoned,
  }) {
    final done = Completer<dynamic>();
    _waiting++;
    _joined++;
    result.then(
      (data) {
        if (done.isCompleted) return;
        _waiting--;
        // Decoded JSON is mutable; callers of one read must not share it.
        done.complete(_joined > 1 ? _copy(data) : data);
      },
      onError: (Object error, StackTrace stack) {
        if (done.isCompleted) return;
        _waiting--;
        done.completeError(error, stack);
      },
    );
    caller?.whenCancel.then((_) {
      if (done.isCompleted) return;
      done.completeError(
        ApiException.from(
          DioException(
            requestOptions: RequestOptions(path: path),
            type: DioExceptionType.cancel,
          ),
        ),
      );
      if (--_waiting == 0) {
        onAbandoned();
        token.cancel();
      }
    });
    return done.future;
  }

  static dynamic _copy(dynamic value) => switch (value) {
    final Map<dynamic, dynamic> map => <String, dynamic>{
      for (final entry in map.entries) '${entry.key}': _copy(entry.value),
    },
    final List<dynamic> list => [for (final item in list) _copy(item)],
    _ => value,
  };
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

class _AuthInterceptor extends Interceptor {
  _AuthInterceptor(this._dio, this._session);

  final Dio _dio;
  final SessionCore _session;

  /// The sign-in a request was sent for; null for a guest's request.
  static const signInKey = 'st.sid';

  /// Shared across every 401 in flight, so a burst of parallel requests
  /// rotates the refresh token once instead of racing and blacklisting it.
  Future<String?>? _refreshInFlight;
  String? _refreshSent;

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

  /// The bearer comes from the core, and only for the sign-in the request was
  /// sent for while it is still current: a request of a sign-in that ended
  /// is refused here rather than sent with anyone else's token.
  @override
  void onRequest(RequestOptions options, RequestInterceptorHandler handler) {
    if (_isAuthEndpoint(options.path) || _isGuestEndpoint(options.path)) {
      return handler.next(options);
    }
    final sid = options.extra.containsKey(signInKey)
        ? options.extra[signInKey] as String?
        : _session.current?.sid;
    options.extra[signInKey] = sid;
    if (sid == null) return handler.next(options);
    final access = _session.accessFor(sid);
    if (access == null) return handler.reject(sessionChanged(options));
    options.headers['Authorization'] = 'Bearer $access';
    handler.next(options);
  }

  @override
  Future<void> onResponse(
    Response<dynamic> response,
    ResponseInterceptorHandler handler,
  ) async {
    final request = response.requestOptions;
    final sid = request.extra[signInKey];
    final signIn = _session.current;
    if (response.statusCode != 401 ||
        sid is! String ||
        _isAuthEndpoint(request.path) ||
        _isGuestEndpoint(request.path) ||
        request.extra['st.retried'] == true ||
        // The sign-in this answer belongs to has ended. Replaying it with the
        // next sign-in's bearer could perform the old member's action as the
        // new one.
        signIn == null ||
        signIn.sid != sid) {
      return handler.next(response);
    }

    // Another request may have refreshed while this 401 was in flight. If the
    // current token is already newer than the one we sent, just replay.
    if (request.headers['Authorization'] !=
        'Bearer ${_session.accessFor(sid)}') {
      return _resolveReplay(handler, request, sid);
    }

    if (await _refreshOnce(sid, signIn.refresh)) {
      return _resolveReplay(handler, request, sid);
    }
    handler.next(response);
  }

  Future<void> _resolveReplay(
    ResponseInterceptorHandler handler,
    RequestOptions request,
    String sid,
  ) async {
    final access = _session.accessFor(sid);
    if (access == null) return handler.reject(sessionChanged(request));
    request.extra['st.retried'] = true;
    request.headers['Authorization'] = 'Bearer $access';
    try {
      handler.resolve(await _dio.fetch<dynamic>(request));
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

  static DioException sessionChanged([RequestOptions? request]) => DioException(
    requestOptions: request ?? RequestOptions(),
    type: DioExceptionType.cancel,
    error: StateError('The authenticated session changed.'),
  );

  /// One refresh at a time per refresh token sent. True when [sid] holds a
  /// new access token.
  Future<bool> _refreshOnce(String sid, String refresh) async {
    final active = _refreshInFlight;
    if (active != null && _refreshSent == refresh) {
      return await active != null;
    }
    final future = _performRefresh(sid, refresh);
    _refreshInFlight = future;
    _refreshSent = refresh;
    try {
      return await future != null;
    } finally {
      if (identical(_refreshInFlight, future)) {
        _refreshInFlight = null;
        _refreshSent = null;
      }
    }
  }

  /// Sends [refresh] once. Only the server's refusal of it (401) ends the
  /// sign-in, and only while it is still the current token: a refusal that
  /// arrives after another refresh replaced it says nothing. No network, a
  /// throttle or a server error keeps the member signed in.
  Future<String?> _performRefresh(String sid, String refresh) async {
    final Response<Map<String, dynamic>> response;
    try {
      response = await _dio.post<Map<String, dynamic>>(
        '/api/auth/refresh',
        data: {'refresh': refresh},
      );
    } on Object {
      return null;
    }
    if (response.statusCode == 401) {
      await _session.end(sid, EndReason.refused, refusedRefresh: refresh);
      return null;
    }
    final access = response.data?['access'];
    if (response.statusCode != 200 || access is! String) return null;
    final rotated = response.data?['refresh'];
    try {
      final replaced = await _session.replaceTokens(
        sid,
        sentRefresh: refresh,
        access: access,
        refresh: rotated is String ? rotated : null,
      );
      return replaced ? access : null;
    } on Object {
      return null;
    }
  }
}

/// One page of rows and whether the server has another after it.
class ListPage {
  const ListPage({required this.rows, required this.hasNext, this.total});

  final List<dynamic> rows;
  final bool hasNext;

  /// The server's count of the whole collection, when it states one.
  final int? total;
}
