/// A fake server, wired under the real client.
///
/// These tests deliberately do **not** stub repositories. The thing Phase 6D
/// can get wrong is the wire contract — a field named `language` instead of
/// `communication_language`, a `Locale` object where the server wants `"ar"`,
/// a PATCH that never leaves — and a stubbed repository proves none of it.
///
/// So the fake sits at the bottom, as a Dio adapter, and everything above it
/// is production code: `ApiClient`, its auth interceptor, the real
/// repositories, the real `SessionController`, the real screens. Each request
/// is recorded so a test can assert on the exact JSON that would have gone to
/// Django.
library;

import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shiptrip/core/api/api_client.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';

/// One request the client actually made.
class RecordedRequest {
  RecordedRequest({
    required this.method,
    required this.path,
    required this.body,
  });

  final String method;
  final String path;

  /// The decoded JSON body, or `{}` for a request that carried none.
  final Map<String, dynamic> body;

  @override
  String toString() => '$method $path $body';
}

/// What the fake should answer with.
class FakeResponse {
  const FakeResponse(this.statusCode, [this.body = const <String, dynamic>{}]);

  final int statusCode;
  final Object body;
}

typedef FakeHandler = FakeResponse Function(RecordedRequest request);

class FakeBackend {
  final List<RecordedRequest> requests = <RecordedRequest>[];
  final Map<String, FakeHandler> _routes = <String, FakeHandler>{};

  static String _key(String method, String path) =>
      '${method.toUpperCase()} $path';

  /// Registers a fixed answer for one route.
  void on(String method, String path, FakeResponse response) {
    _routes[_key(method, path)] = (_) => response;
  }

  /// Registers an answer computed from the request — for asserting on what was
  /// sent, or for a route whose reply changes after a write.
  void handle(String method, String path, FakeHandler handler) {
    _routes[_key(method, path)] = handler;
  }

  /// Every request made to one route, in order.
  List<RecordedRequest> to(String method, String path) => requests
      .where((r) => r.method == method.toUpperCase() && r.path == path)
      .toList(growable: false);

  /// The last request made to one route, or null.
  RecordedRequest? lastTo(String method, String path) {
    final matches = to(method, path);
    return matches.isEmpty ? null : matches.last;
  }

  FakeResponse _dispatch(RecordedRequest request) {
    requests.add(request);
    final handler = _routes[_key(request.method, request.path)];
    if (handler == null) {
      // Louder than a 404: an unrouted call means the test's picture of the
      // contract and the client's disagree, and that is the bug worth seeing.
      throw StateError('no fake route for ${request.method} ${request.path}');
    }
    return handler(request);
  }
}

class _FakeAdapter implements HttpClientAdapter {
  _FakeAdapter(this.backend);

  final FakeBackend backend;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    final raw = options.data;
    final request = RecordedRequest(
      method: options.method.toUpperCase(),
      path: options.uri.path,
      body: raw is Map ? Map<String, dynamic>.from(raw) : <String, dynamic>{},
    );

    final response = backend._dispatch(request);
    return ResponseBody.fromString(
      jsonEncode(response.body),
      response.statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

/// A keystore that answers from memory.
///
/// Subclassed rather than mocked at the channel so the production
/// `SessionController.restore()` path runs exactly as it does on a device: it
/// finds a refresh token, calls `/api/me`, and signs the user in.
class FakeTokenStore extends TokenStore {
  FakeTokenStore({this.refresh = 'refresh-token', String? locale})
    : _locale = locale,
      super(const FlutterSecureStorage());

  final String? refresh;
  String? _locale;
  String? _roleContext;

  @override
  Future<void> save({required String access, required String refresh}) async {}

  @override
  Future<String?> readAccess() async => 'access-token';

  @override
  Future<String?> readRefresh() async => refresh;

  @override
  Future<void> updateAccess(String access) async {}

  @override
  Future<String?> readRoleContext() async => _roleContext;

  @override
  Future<void> writeRoleContext(String value) async => _roleContext = value;

  @override
  Future<String?> readLocale() async => _locale;

  @override
  Future<void> writeLocale(String? tag) async => _locale = tag;

  @override
  Future<void> clear() async {}

  @override
  Future<void> purgeLegacyArtifacts() async {}
}

/// A container whose HTTP layer is [backend] and whose keystore is in memory.
///
/// Everything else — repositories, session, providers — is the real thing.
ProviderContainer containerFor(FakeBackend backend, {FakeTokenStore? tokens}) {
  final store = tokens ?? FakeTokenStore();
  final dio = Dio()..httpClientAdapter = _FakeAdapter(backend);
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(ApiClient(tokens: store, dio: dio)),
    ],
  );
}

// ---------------------------------------------------------------------------
// Fixtures, shaped from the real Phase 6C responses
// ---------------------------------------------------------------------------

/// `GET /api/me`.
///
/// [preferredLanguage] is passed through verbatim, including `null` and `''`,
/// so a test can reproduce a legacy row exactly as an older deployment would
/// serialise it rather than as the client wishes it looked.
Map<String, dynamic> meFixture({Object? preferredLanguage = 'en'}) => {
  'id': 42,
  'email': 'sender@example.com',
  'full_name': 'Amina Bouzid',
  'phone': '+213555000111',
  'wilaya': '16',
  'role': 'both',
  'preferred_language': preferredLanguage,
  'is_phone_verified': true,
  'is_email_verified': true,
  'is_kyc_verified': true,
  'kyc_status': 'verified',
  'kyc_rejection_reason': null,
  'date_joined': '2026-01-04T09:00:00Z',
};

/// `GET /api/deals/{id}` as the **sender** sees it.
///
/// Pass `recipient: null` for a deal whose recipient has not been recorded
/// yet, which is the case the "default from sender" rule governs.
Map<String, dynamic> dealFixture({
  int id = 7,
  String status = 'funded',
  Map<String, dynamic>? recipient,
  String? pickupConfirmedAt,
}) => {
  'id': id,
  'sender_id': 42,
  'traveler_id': 99,
  'status': status,
  'is_legacy': false,
  'leg_allocations': <Object>[],
  'funded_at': '2026-08-20T10:00:00Z',
  'pickup_confirmed_at': pickupConfirmedAt,
  // Absent, not null, for a deal whose recipient has not been recorded — the
  // server omits the key entirely rather than sending an empty object.
  'recipient': ?recipient,
};

/// The sender's full recipient projection.
///
/// `communicationLanguage` is deliberately typed as `Object?`: the tests need
/// to send `''` for a legacy row and omit the key entirely for a deployment
/// that predates the field.
Map<String, dynamic> recipientFixture({
  Object? communicationLanguage = 'en',
  bool includeLanguage = true,
}) => {
  'full_name': 'Yacine Haddad',
  'email': 'yacine@example.com',
  'phone': '+213770112233',
  'delivery_note': 'Second floor, blue door.',
  if (includeLanguage) 'communication_language': communicationLanguage,
  'revision': 1,
  'updated_at': '2026-08-21T08:30:00Z',
};
