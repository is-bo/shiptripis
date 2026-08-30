/// One exception type for everything the API can go wrong with, plus a parser
/// that copes with the fact that the backend does not ship a single error
/// envelope.
///
/// ## The four shapes that actually arrive
///
/// The Django monolith has no custom exception handler, so DRF's default is in
/// play alongside three hand-written conventions. All of these are real:
///
/// ```jsonc
/// {"code": "capacity_exceeded", "detail": "…", "journey_leg_ids": [4, 5]}  // domain
/// {"detail": "No Journey matches the given query."}                        // DRF builtin
/// {"pickup_location_id": ["This field is required."]}                      // DRF field
/// {"code": ["client_supplied_amount_rejected"], "detail": ["…"]}           // wrapped by
///                                                                          // Serializer.validate
/// ```
///
/// Plus `{"error": "…"}` from the Go KYC service, and occasionally an HTML
/// body from a proxy that never reached Django at all.
///
/// Every one of these is normalised here, once, so no screen ever writes
/// `response.data['detail']` and no screen ever branches on an English
/// message. Screens branch on [code].
library;

import 'dart:io';

import 'package:dio/dio.dart';

import 'error_codes.dart';

/// How the failure should be presented, independent of which code caused it.
enum ApiFailureKind {
  /// The device could not reach the server: no connectivity, DNS, timeout.
  offline,

  /// Reached the server, but it took too long to answer.
  timeout,

  /// Credentials are missing or expired and refresh did not recover.
  unauthenticated,

  /// Authenticated, but not allowed to do this.
  forbidden,

  /// The thing is gone or was never visible to this user.
  notFound,

  /// The request was well-formed but the server rejected its contents.
  validation,

  /// The world moved: someone else acted, capacity went, the offer is no
  /// longer pending. The screen's state is stale and must be refreshed.
  conflict,

  /// Slow down.
  rateLimited,

  /// This capability has been retired in V1.
  gone,

  /// The server failed.
  server,

  /// The response was not something this client can read at all.
  malformed,

  /// Cancelled by the app, e.g. the screen was disposed.
  cancelled,
}

class ApiException implements Exception {
  ApiException({
    required this.kind,
    required this.code,
    this.statusCode,
    this.serverDetail,
    this.fieldErrors = const {},
    this.extras = const {},
    this.cause,
  });

  final ApiFailureKind kind;

  /// The machine-readable code, or [ApiErrorCode.unknown] when the response
  /// carried none. Never null, so a screen can `switch` without a null guard.
  final ApiErrorCode code;

  final int? statusCode;

  /// The server's own message. Useful for logs and for a debug affordance —
  /// **never** rendered directly to a user, because it is not localized and
  /// is frequently a Django internal string.
  final String? serverDetail;

  /// DRF field errors, keyed by the API field name. Forms map these onto
  /// their inputs; anything unmapped is surfaced as a form-level message.
  final Map<String, List<String>> fieldErrors;

  /// Everything else the domain envelope carried alongside `code`:
  /// `attempts_remaining`, `locked_until`, `minimum_reward_eur_cents`,
  /// `journey_leg_ids`, `rejection_codes`, `retry_after_seconds`, …
  final Map<String, dynamic> extras;

  final Object? cause;

  /// True when the correct response is to re-fetch server state and re-render
  /// rather than to show a dead end. Every one of these means the user is
  /// looking at a screen that no longer reflects reality.
  bool get isStale =>
      kind == ApiFailureKind.conflict || code.impliesStaleClientState;

  /// True when retrying the identical request could plausibly succeed.
  bool get isRetryable =>
      kind == ApiFailureKind.offline ||
      kind == ApiFailureKind.timeout ||
      kind == ApiFailureKind.server;

  /// How long the server asked us to wait, when it said so.
  ///
  /// Only ever set on a throttle. Note that [isRetryable] stays false for a
  /// 429 on purpose: the fix is for the *user* to wait, not for the client to
  /// hammer the same endpoint on a timer.
  Duration? get retryAfter {
    final seconds = intExtra('retry_after_seconds');
    return seconds == null ? null : Duration(seconds: seconds);
  }

  /// The server's correlation id for the request that failed, when it sent
  /// one. Shown to the user only in the "contact support" affordance — it is
  /// noise in a normal error message.
  String? get requestId => extras['request_id'] as String?;

  int? intExtra(String key) => switch (extras[key]) {
    final int v => v,
    final num v => v.toInt(),
    final String v => int.tryParse(v),
    _ => null,
  };

  DateTime? dateExtra(String key) {
    final raw = extras[key];
    return raw is String ? DateTime.tryParse(raw)?.toLocal() : null;
  }

  List<String> stringListExtra(String key) {
    final raw = extras[key];
    if (raw is List) return raw.whereType<String>().toList(growable: false);
    if (raw is String) return [raw];
    return const [];
  }

  // ---------------------------------------------------------------------------
  // Parsing
  // ---------------------------------------------------------------------------

  /// Normalises anything Dio can throw or return into an [ApiException].
  factory ApiException.from(Object error, [StackTrace? _]) {
    if (error is ApiException) return error;
    if (error is! DioException) {
      return ApiException(
        kind: ApiFailureKind.malformed,
        code: ApiErrorCode.unknown,
        cause: error,
      );
    }

    switch (error.type) {
      case DioExceptionType.cancel:
        return ApiException(
          kind: ApiFailureKind.cancelled,
          code: ApiErrorCode.unknown,
          cause: error,
        );
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
      // Dio 5.11 added this for a response body that stalls mid-transform.
      // It is a timeout from the user's point of view and must be handled, or
      // a slow upload surfaces as an unexplained failure.
      case DioExceptionType.transformTimeout:
        return ApiException(
          kind: ApiFailureKind.timeout,
          code: ApiErrorCode.unknown,
          cause: error,
        );
      case DioExceptionType.connectionError:
        return ApiException(
          kind: ApiFailureKind.offline,
          code: ApiErrorCode.unknown,
          cause: error,
        );
      case DioExceptionType.badCertificate:
        return ApiException(
          kind: ApiFailureKind.offline,
          code: ApiErrorCode.unknown,
          cause: error,
        );
      case DioExceptionType.unknown:
        if (error.error is SocketException || error.error is HttpException) {
          return ApiException(
            kind: ApiFailureKind.offline,
            code: ApiErrorCode.unknown,
            cause: error,
          );
        }
        if (error.response == null) {
          return ApiException(
            kind: ApiFailureKind.malformed,
            code: ApiErrorCode.unknown,
            cause: error,
          );
        }
      case DioExceptionType.badResponse:
        break;
    }

    return ApiException.fromResponse(error.response!, cause: error);
  }

  /// Builds from a non-2xx [Response]. The client uses a permissive
  /// `validateStatus`, so most failures arrive here rather than as a throw.
  factory ApiException.fromResponse(
    Response<dynamic> response, {
    Object? cause,
  }) {
    final status = response.statusCode ?? 0;
    final data = response.data;

    var codeString = <String>[];
    String? detail;
    final fields = <String, List<String>>{};
    final extras = <String, dynamic>{..._headerExtras(response)};

    if (data is Map) {
      for (final entry in data.entries) {
        final key = entry.key;
        if (key is! String) continue;
        final value = entry.value;

        switch (key) {
          case 'code':
            // Bare string on a hand-written domain error; a one-element list
            // when the same error was raised from `Serializer.validate`,
            // because DRF wraps scalars from there.
            codeString = _asStringList(value);
          case 'detail':
            detail = _asStringList(value).firstOrNull ?? _stringify(value);
          case 'error':
            // The Go KYC service's envelope.
            detail ??= _stringify(value);
          case 'non_field_errors':
            final msgs = _asStringList(value);
            if (msgs.isNotEmpty) {
              detail ??= msgs.first;
              fields[key] = msgs;
            }
          default:
            final msgs = _asStringList(value);
            // A list of human sentences is a DRF field error. Anything else —
            // an int, a list of ids, a nested object — is domain metadata the
            // screen may need, so it is preserved verbatim.
            if (msgs.isNotEmpty && value is List && _looksLikeMessages(msgs)) {
              fields[key] = msgs;
            } else {
              extras[key] = value;
            }
        }
      }
    } else if (data is String && data.isNotEmpty) {
      // A proxy interstitial, an HTML 502, or a plain-text body. There is no
      // structure to read; record it as malformed rather than pretending the
      // first 200 characters are a message for the user.
      return ApiException(
        kind: _kindFor(status, ApiErrorCode.unknown),
        code: ApiErrorCode.unknown,
        statusCode: status,
        serverDetail: data.length > 300 ? '${data.substring(0, 300)}…' : data,
        // A gateway 502 has no JSON at all, and its request id is the only
        // thread support can pull on. Keep it.
        extras: Map.unmodifiable(extras),
        cause: cause,
      );
    }

    final code = ApiErrorCode.parse(codeString.firstOrNull);

    return ApiException(
      kind: _kindFor(status, code, hasFieldErrors: fields.isNotEmpty),
      code: code,
      statusCode: status,
      serverDetail: detail,
      fieldErrors: Map.unmodifiable(fields),
      extras: Map.unmodifiable(extras),
      cause: cause,
    );
  }

  /// Metadata the transport carries rather than the body.
  ///
  /// Two headers matter to a user-facing client:
  ///
  /// * `Retry-After` on a 429. The backend's throttles are distributed and
  ///   shared across instances, so a throttle is a real, reachable state
  ///   rather than a theoretical one — and "try again later" with no idea of
  ///   *when* is a dead end. Parsed as seconds; the HTTP-date form is
  ///   deliberately not supported, because the server only ever sends the
  ///   delta form and guessing at clock skew would be worse than saying
  ///   nothing.
  /// * `X-Request-ID` on anything. The server generates one per request and
  ///   stamps it into its structured logs. Surfacing it is the difference
  ///   between a support ticket that can be traced and one that cannot.
  static Map<String, dynamic> _headerExtras(Response<dynamic> response) {
    final headers = response.headers;
    final extras = <String, dynamic>{};

    final retryAfter = headers.value('retry-after');
    final seconds = retryAfter == null ? null : int.tryParse(retryAfter.trim());
    if (seconds != null && seconds > 0) extras['retry_after_seconds'] = seconds;

    final requestId = headers.value('x-request-id');
    if (requestId != null && requestId.trim().isNotEmpty) {
      extras['request_id'] = requestId.trim();
    }
    return extras;
  }

  static ApiFailureKind _kindFor(
    int status,
    ApiErrorCode code, {
    bool hasFieldErrors = false,
  }) {
    // A domain code that means "the world moved" is treated as stale even when
    // the endpoint returned 400 rather than 409 — the envelope is not
    // consistent about which status a given code travels on, and the recovery
    // the user needs depends on the code, not the number.
    if (code.impliesStaleClientState) return ApiFailureKind.conflict;

    return switch (status) {
      401 => ApiFailureKind.unauthenticated,
      403 => ApiFailureKind.forbidden,
      404 => ApiFailureKind.notFound,
      409 => ApiFailureKind.conflict,
      410 => ApiFailureKind.gone,
      429 => ApiFailureKind.rateLimited,
      400 || 422 => ApiFailureKind.validation,
      >= 500 => ApiFailureKind.server,
      _ => ApiFailureKind.server,
    };
  }

  static List<String> _asStringList(Object? value) {
    if (value is String) return [value];
    if (value is List) {
      return value.map(_stringify).whereType<String>().toList(growable: false);
    }
    return const [];
  }

  static String? _stringify(Object? value) =>
      value is String ? value : (value == null ? null : '$value');

  /// A DRF field error is a list of sentences. A list of integers (leg ids) or
  /// of snake_case tokens (rejection codes) is data, not a message.
  static bool _looksLikeMessages(List<String> values) =>
      values.every((v) => v.contains(' ') || v.endsWith('.'));

  @override
  String toString() =>
      'ApiException(${kind.name}, ${code.raw}, http=$statusCode, '
      'detail=$serverDetail, fields=${fieldErrors.keys.toList()})';
}

extension _FirstOrNull<T> on List<T> {
  T? get firstOrNull => isEmpty ? null : first;
}
