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

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:shiptrip/core/api/api_client.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/time/clock.dart';
import 'package:shiptrip/core/session/token_store.dart';

/// One request the client actually made.
class RecordedRequest {
  RecordedRequest({
    required this.method,
    required this.path,
    required this.body,
    this.query = const <String, dynamic>{},
  });

  final String method;
  final String path;

  /// The decoded JSON body, or `{}` for a request that carried none.
  final Map<String, dynamic> body;
  final Map<String, dynamic> query;

  /// True once the client cancelled this request while it was in flight.
  bool cancelled = false;

  @override
  String toString() => '$method $path $body';
}

/// What the fake should answer with.
class FakeResponse {
  const FakeResponse(this.statusCode, [this.body = const <String, dynamic>{}])
    : headers = const <String, List<String>>{};

  /// For a contract carried in headers — the K4 bare-array lists say whether
  /// another page follows in `X-Next-Page`, not in the body.
  const FakeResponse.withHeaders(this.statusCode, this.body, this.headers);

  final int statusCode;
  final Object body;
  final Map<String, List<String>> headers;
}

typedef FakeHandler = FutureOr<FakeResponse> Function(RecordedRequest request);

class FakeBackend {
  final List<RecordedRequest> requests = <RecordedRequest>[];
  final Map<String, FakeHandler> _routes = <String, FakeHandler>{};

  /// Answers any request no route claims. Null keeps the default: an unrouted
  /// call is a loud failure. A whole-app test that boots every tab sets this
  /// rather than enumerating each endpoint the shell happens to touch.
  FakeHandler? fallback;

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

  Future<FakeResponse> _dispatch(RecordedRequest request) async {
    requests.add(request);
    final handler = _routes[_key(request.method, request.path)] ?? fallback;
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
      body: switch (raw) {
        final Map<dynamic, dynamic> map => Map<String, dynamic>.from(map),
        // A multipart upload is a wire contract too — the field names, the
        // idempotency key, the declared content type. Flattening it here lets
        // a test assert on what would actually reach Django instead of
        // stopping at "something was posted".
        final FormData form => {
          for (final field in form.fields) field.key: field.value,
          for (final file in form.files)
            '${file.key}__filename': file.value.filename ?? '',
          for (final file in form.files)
            '${file.key}__content_type':
                file.value.contentType?.toString() ?? '',
        },
        _ => <String, dynamic>{},
      },
      query: Map<String, dynamic>.from(options.queryParameters),
    );
    unawaited(cancelFuture?.then((_) => request.cancelled = true));

    final response = await backend._dispatch(request);
    return ResponseBody.fromString(
      jsonEncode(response.body),
      response.statusCode,
      headers: {
        Headers.contentTypeHeader: [Headers.jsonContentType],
        ...response.headers,
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
  FakeTokenStore({
    this.refresh = 'refresh-token',
    String? locale,
    this.accountSnapshot,
  }) : _locale = locale,
       super(const FlutterSecureStorage());

  final String? refresh;

  /// The launch snapshot, as secure storage would hold it. Null by default,
  /// so a test not about K5's fast launch keeps the `/api/me`-first restore.
  String? accountSnapshot;
  String? _locale;
  String? _roleContext;

  @override
  Future<void> save({required String access, required String refresh}) async {
    invalidateIdentity();
    accountSnapshot = null;
  }

  @override
  Future<String?> readAccountSnapshot() async => accountSnapshot;

  @override
  Future<bool> writeAccountSnapshotIfCurrent({
    required int expectedIdentityGeneration,
    required String json,
  }) async {
    if (identityGeneration != expectedIdentityGeneration) return false;
    accountSnapshot = json;
    return true;
  }

  @override
  Future<void> deleteAccountSnapshot() async => accountSnapshot = null;

  @override
  Future<String?> readAccess() async => 'access-token';

  @override
  Future<String?> readRefresh() async => refresh;

  @override
  Future<void> updateAccess(String access) async {}

  @override
  Future<bool> saveRefreshedIfCurrent({
    required int expectedIdentityGeneration,
    required String expectedRefresh,
    required String access,
    String? refresh,
  }) async =>
      identityGeneration == expectedIdentityGeneration &&
      this.refresh == expectedRefresh;

  @override
  Future<bool> saveAuthenticationIfCurrent({
    required int expectedIdentityGeneration,
    required String access,
    required String refresh,
  }) async {
    if (identityGeneration != expectedIdentityGeneration) return false;
    accountSnapshot = null;
    return true;
  }

  @override
  Future<String?> readRoleContext() async => _roleContext;

  @override
  Future<void> writeRoleContext(String value) async => _roleContext = value;

  @override
  Future<String?> readLocale() async => _locale;

  @override
  Future<void> writeLocale(String? tag) async => _locale = tag;

  @override
  Future<void> clear() async {
    invalidateIdentity();
    accountSnapshot = null;
  }

  @override
  Future<bool> clearIfIdentityCurrent(int expectedIdentityGeneration) async {
    if (identityGeneration != expectedIdentityGeneration) return false;
    invalidateIdentity();
    accountSnapshot = null;
    return true;
  }

  @override
  Future<void> purgeLegacyArtifacts() async {}
}

/// A container whose HTTP layer is [backend] and whose keystore is in memory.
///
/// Everything else — repositories, session, providers — is the real thing.
ProviderContainer containerFor(
  FakeBackend backend, {
  FakeTokenStore? tokens,
  DateTime Function()? now,
}) {
  final store = tokens ?? FakeTokenStore();
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
      if (now != null) clockProvider.overrideWithValue(now),
    ],
  );
}

/// The real [ApiClient], talking to [backend].
///
/// Exposed for a test that needs to build its own container — one standing in
/// for a camera, say. `Override` is not nameable from Riverpod 3's public API,
/// so the override list has to be written as a literal at the call site rather
/// than passed in here.
///
/// [tokens] may be a real [TokenStore] over in-memory storage, for a test about
/// what the store itself keeps; [onSessionExpired] wires the terminal-refresh
/// path the way `apiClientProvider` does in the app.
ApiClient apiClientFor(
  FakeBackend backend,
  TokenStore tokens, {
  OnSessionExpired? onSessionExpired,
}) => ApiClient(
  tokens: tokens,
  dio: Dio()..httpClientAdapter = _FakeAdapter(backend),
  onSessionExpired: onSessionExpired,
);

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

// ---------------------------------------------------------------------------
// Discovery (L2A contract, `docs/PHASE_L2A_DISCOVERY_CONTRACT.md`)
// ---------------------------------------------------------------------------

/// `{"place_id", "label", "country_code"}` — the one place block every
/// discovery card uses.
Map<String, dynamic> discoveryPlace(
  int id,
  String label, [
  String country = 'FR',
]) => {'place_id': id, 'label': label, 'country_code': country};

Map<String, dynamic> discoveryPersonFields({
  String name = 'Samira',
  bool verified = true,
  Object? rating,
  int deliveries = 0,
}) => {
  'display_name': name,
  'identity_verified': verified,
  'rating': rating,
  'completed_deliveries': deliveries,
};

/// A trip card. [id] doubles as the journey id.
Map<String, dynamic> tripCardFixture(
  int id, {
  String name = 'Samira',
  String from = 'Paris',
  String to = 'Algiers',
  String departs = '2026-12-02T10:00:00Z',
  String capacity = '5_to_10kg',
  Map<String, dynamic>? price,
}) => {
  'journey_id': id,
  'traveler': discoveryPersonFields(name: name, rating: 4.8, deliveries: 3),
  'stops': [discoveryPlace(1, from), discoveryPlace(2, to, 'DZ')],
  'legs': [
    {
      'mode': 'flight',
      'depart_at': departs,
      'arrive_at': '2026-12-02T13:00:00Z',
    },
  ],
  'departs_at': departs,
  'next_departure_at': departs,
  'arrives_at': '2026-12-02T13:00:00Z',
  'capacity_band': capacity,
  'price': price,
};

/// A request card. [id] doubles as the request id.
Map<String, dynamic> requestCardFixture(
  int id, {
  String title = 'Documents',
  String sender = 'Yacine',
  String from = 'Algiers',
  String to = 'Paris',
}) => {
  'request_id': id,
  'sender': {'display_name': sender},
  'pickup': discoveryPlace(2, from, 'DZ'),
  'delivery': discoveryPlace(1, to),
  'title': title,
  'category': 'documents',
  'fragile': false,
  'weight_kg': 2.5,
  'ready_window_start': '2026-12-01T08:00:00Z',
  'ready_window_end': '2026-12-03T18:00:00Z',
  'deadline_at': '2026-12-10T18:00:00Z',
  'total_offered_reward_eur_cents': 2500,
};

/// A profile card as the People list returns it.
Map<String, dynamic> profileCardFixture({
  String id = 'p-1',
  String name = 'Samira',
  List<Map<String, dynamic>> routes = const [],
}) => {
  'id': id,
  ...discoveryPersonFields(name: name, deliveries: 2),
  'member_since': '2026-03',
  'usual_routes': routes,
};

Map<String, dynamic> usualRouteFixture({
  String from = 'Paris',
  String to = 'Algiers',
}) => {
  'origin': discoveryPlace(1, from),
  'destination': discoveryPlace(2, to, 'DZ'),
};

/// `GET`/`PUT /api/discovery/profile/me`.
Map<String, dynamic> ownProfileFixture({
  String state = 'not_visible',
  bool discoverable = false,
  bool showPrompt = false,
  List<Map<String, dynamic>> routes = const [],
}) => {
  'state': state,
  'is_discoverable': discoverable,
  'show_prompt': showPrompt,
  'consent_version': 'l2a-2026-11',
  'usual_routes': routes,
  'card': profileCardFixture(id: 'me', name: 'Amina', routes: routes),
};

Map<String, dynamic> alertFixture(
  int id, {
  String watches = 'trips',
  String from = 'Paris',
  String to = 'Algiers',
  Map<String, dynamic>? subject,
}) => {
  'id': id,
  'watches': watches,
  'origin': discoveryPlace(1, from),
  'destination': discoveryPlace(2, to, 'DZ'),
  'subject': subject,
  'created_at': '2026-11-12T09:00:00Z',
};

/// A paged discovery list answer.
FakeResponse discoveryPage(List<Map<String, dynamic>> rows, {int? next}) =>
    FakeResponse(200, {
      'state': rows.isEmpty ? 'empty' : 'results',
      'results': rows,
      'next_offset': next,
    });

extension DiscoveryRoutes on FakeBackend {
  /// Calm answers for every discovery read: nothing to match, nothing listed,
  /// no profiles, no alerts, no opt-in prompt. A screen that merely contains
  /// Home gets harmless sections and its own assertions stay about itself.
  void emptyDiscovery() {
    on(
      'GET',
      '/api/discovery/matches',
      const FakeResponse(200, {
        'state': 'no_active_items',
        'groups': <Object>[],
      }),
    );
    on('GET', '/api/discovery/trips', discoveryPage(const []));
    on('GET', '/api/discovery/requests', discoveryPage(const []));
    on('GET', '/api/discovery/people', discoveryPage(const []));
    on(
      'GET',
      '/api/discovery/profile/me',
      FakeResponse(200, ownProfileFixture()),
    );
    on(
      'GET',
      '/api/discovery/alerts',
      const FakeResponse(200, {'results': <Object>[]}),
    );
  }
}

/// One row of Find Travelers, as the matches fan-in forwards it.
Map<String, dynamic> travelerCandidateFixture(
  int journeyId, {
  String name = 'Karim',
  String from = 'Paris',
  String to = 'Algiers',
}) => {
  'journey_id': journeyId,
  'traveler': {
    'id': 200 + journeyId,
    'display_name': name,
    'identity_verified': true,
    'rating': {'state': 'rated', 'count': 24, 'average': 4.8},
    'completed_deliveries': 12,
  },
  'route': {
    'stops': [
      {
        'place_id': 1,
        'label': from,
        'country_code': 'FR',
        'airport_iata': 'CDG',
      },
      {'place_id': 2, 'label': to, 'country_code': 'DZ', 'airport_iata': 'ALG'},
    ],
    'segments': [
      {'journey_leg_id': 1, 'mode': 'FLIGHT'},
    ],
    'continues_before': false,
    'continues_after': false,
  },
  'route_fit': 'excellent',
  'departs_at': '2026-12-02T10:00:00Z',
  'arrives_at': '2026-12-02T14:00:00Z',
  'transfers': 0,
  'primary_mode': 'FLIGHT',
  'match_reasons': <Object>[],
  'caveats': <String>[],
  'actions': [
    {'code': 'view_journey', 'available': true},
  ],
};

/// One row of the compatible-requests list, as the matches fan-in forwards it.
Map<String, dynamic> compatibleRequestFixture(
  int requestId, {
  String from = 'Algiers',
  String to = 'Paris',
}) => {
  'delivery_request': {
    'id': requestId,
    'sender_id': 7,
    'pickup': {'id': 1, 'public_label': from, 'city': from},
    'delivery': {'id': 2, 'public_label': to, 'city': to},
    'actual_weight_kg': 3.0,
    'deadline_at': '2026-12-20T18:00:00Z',
  },
  'compatibility': {'start_leg_id': 1, 'end_leg_id': 1},
};

FakeResponse senderMatches(List<Map<String, dynamic>> groups) => FakeResponse(
  200,
  {'state': groups.isEmpty ? 'none' : 'results', 'groups': groups},
);

/// A sender's open request with the travelers that fit it.
Map<String, dynamic> senderMatchGroup(
  int requestId,
  List<Map<String, dynamic>> travelers, {
  bool more = false,
}) => {
  'request': {
    'id': requestId,
    'pickup': discoveryPlace(2, 'Algiers', 'DZ'),
    'delivery': discoveryPlace(1, 'Paris'),
    'deadline_at': '2026-12-20T18:00:00Z',
  },
  'results': travelers,
  'more_available': more,
};

/// A traveler's journey with the requests that fit it.
Map<String, dynamic> travelerMatchGroup(
  int journeyId,
  List<Map<String, dynamic>> requests, {
  bool more = false,
}) => {
  'journey': {
    'id': journeyId,
    'origin': discoveryPlace(1, 'Paris'),
    'destination': discoveryPlace(2, 'Algiers', 'DZ'),
    'next_departure_at': '2026-12-02T10:00:00Z',
  },
  'results': requests,
  'more_available': more,
};

/// A traveler's live journey as `GET /api/journeys` lists it.
Map<String, dynamic> liveJourneyFixture(
  int id, {
  String from = 'Paris',
  String to = 'Algiers',
}) {
  Map<String, dynamic> place(int placeId, String name, String country) => {
    'id': placeId,
    'name': name,
    'display_label': name,
    'place_type': 'locality',
    'country_code': country,
    'parent_name': '',
    'matching_locality_id': placeId,
    'matching_locality_name': name,
  };
  return {
    'id': id,
    'traveler_id': 42,
    'traveler_name': 'Amina Bouzid',
    'status': 'active',
    'notes': '',
    'editable': false,
    'published_at': '2026-11-01T08:00:00Z',
    'start_place': place(1, from, 'FR'),
    'destination_place': place(2, to, 'DZ'),
    'legs': <Object>[],
  };
}

/// One of the signed-in sender's own requests, as `GET /api/parcels` lists it.
Map<String, dynamic> ownRequestFixture(
  int id, {
  String status = 'open',
  String title = 'My parcel',
}) => {
  'id': id,
  'sender_id': 42,
  'target_traveler_id': null,
  'kind': 'delivery',
  'status': status,
  'schema_version': 3,
  'title': title,
  'description': '',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'created_at': '2026-11-01T08:00:00Z',
};
