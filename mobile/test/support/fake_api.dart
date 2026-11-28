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
import 'package:flutter_test/flutter_test.dart' show WidgetTester;
import 'package:shiptrip/core/api/api_client.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/core/session/token_store.dart';
import 'package:shiptrip/core/time/clock.dart';
import 'package:shiptrip/domain/account.dart';

/// One request the client actually made.
class RecordedRequest {
  RecordedRequest({
    required this.method,
    required this.path,
    required this.body,
    this.query = const <String, dynamic>{},
    this.headers = const <String, dynamic>{},
  });

  final String method;
  final String path;

  /// The headers as sent, the bearer included.
  final Map<String, dynamic> headers;

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
  final Map<String, FakeHandler> _routes = <String, FakeHandler>{
    // Answers every screen that offers "contact support" (none set) and the
    // Profile rating (no ratings), so a test about something else need not.
    'GET /api/support': (_) => const FakeResponse(200, {'email': null}),
    'GET /api/users/me/ratings/summary': (_) =>
        const FakeResponse(200, {'state': 'new', 'average': null, 'count': 0}),
  };

  /// The phone's session core, posting its sign-outs here. [meFixture] is
  /// signed in unless a test sets another core.
  late SessionCore session = coreFor(this);

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
      headers: Map<String, dynamic>.from(options.headers),
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

/// Secure storage that answers from memory, as a keystore would.
///
/// [readError] and [writeError], while set, are thrown by every read or
/// write: a keystore can refuse either. [readGate] and [writeGate], while
/// set, hold every read or write until they complete.
class MemoryStorage extends FlutterSecureStorage {
  MemoryStorage([Map<String, String>? values]) : values = {...?values};

  final Map<String, String> values;
  Object? readError;
  Object? writeError;
  Completer<void>? readGate;
  Completer<void>? writeGate;
  int writes = 0;

  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    await readGate?.future;
    final error = readError;
    if (error != null) throw error;
    return values[key];
  }

  @override
  Future<void> write({
    required String key,
    required String? value,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    await writeGate?.future;
    final error = writeError;
    if (error != null) throw error;
    writes++;
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    final error = writeError;
    if (error != null) throw error;
    values.remove(key);
  }

  /// The session record as stored now.
  SessionRecord? get record => switch (values[SessionCore.recordKey]) {
    null => null,
    final String raw => SessionRecord.decode(raw),
  };
}

/// A JWT-shaped token of sign-in [sid]. The phone reads only its `sid`
/// claim; [kind] keeps the access token, the refresh token and each rotation
/// apart.
String fakeToken(String sid, [String kind = 'refresh']) =>
    'h.${base64Url.encode(utf8.encode(jsonEncode({'sid': sid, 'kind': kind})))}.s';

/// The answer to a sign-in, a sign-up or a provider sign-in that issues
/// sign-in [sid] for [user].
FakeResponse signInAnswer({String sid = 'sid-b', Map<String, dynamic>? user}) =>
    FakeResponse(200, {
      'access': fakeToken(sid, 'access'),
      'refresh': fakeToken(sid),
      'user': user ?? meFixture(),
    });

/// Sign-in [sid] of [account] ([meFixture] by default), as the server issued
/// it.
SignIn signInFor({String sid = 'sid-a', Map<String, dynamic>? account}) =>
    SignIn(
      sid: sid,
      account: Account.fromJson(account ?? meFixture()),
      access: fakeToken(sid, 'access'),
      refresh: fakeToken(sid),
    );

/// The record of a phone on which [account] is signed in as [sid].
String signedInRecord({
  String sid = 'sid-a',
  Map<String, dynamic>? account,
  List<EndedSignIn> ended = const [],
}) => SessionRecord(
  current: signInFor(sid: sid, account: account),
  ended: ended,
).encode();

/// The real [SessionCore] over [storage], posting its sign-outs to [backend].
/// Without [storage], the phone holds sign-in `sid-a` of [meFixture], or
/// nobody when [signedIn] is false.
SessionCore coreFor(
  FakeBackend backend, {
  MemoryStorage? storage,
  bool signedIn = true,
  Future<void> Function()? deletePushToken,
}) => SessionCore(
  storage:
      storage ??
      MemoryStorage({if (signedIn) SessionCore.recordKey: signedInRecord()}),
  http: Dio()..httpClientAdapter = _FakeAdapter(backend),
  deletePushToken: deletePushToken,
);

/// The phone's own keys, in memory.
class FakeTokenStore extends TokenStore {
  FakeTokenStore({String? locale})
    : _locale = locale,
      super(const FlutterSecureStorage());

  String? _locale;
  String? _roleContext;
  int _pushPermissionRequests = 0;

  @override
  Future<int> readPushPermissionRequests() async => _pushPermissionRequests;

  @override
  Future<int> recordPushPermissionRequest({bool afterDenial = false}) async =>
      _pushPermissionRequests = afterDenial && _pushPermissionRequests < 1
      ? 2
      : _pushPermissionRequests + 1;

  @override
  Future<int> releasePushPermissionRequest() async => _pushPermissionRequests =
      _pushPermissionRequests > 0 ? _pushPermissionRequests - 1 : 0;

  int _pushBindingSequence = 0;

  @override
  Future<int> nextPushBindingSequence() async => ++_pushBindingSequence;

  @override
  Future<void> raisePushBindingSequence(int sequence) async {
    if (sequence > _pushBindingSequence) _pushBindingSequence = sequence;
  }

  @override
  Future<String?> readRoleContext() async => _roleContext;

  @override
  Future<void> writeRoleContext(String? value) async => _roleContext = value;

  @override
  Future<String?> readLocale() async => _locale;

  @override
  Future<void> writeLocale(String? tag) async => _locale = tag;

  @override
  Future<void> purgeLegacyArtifacts() async {}
}

/// A container whose HTTP layer is [backend] and whose storage is in memory.
///
/// Everything else — the session core, repositories, session, providers — is
/// the real thing. Without [session], [meFixture] is signed in.
ProviderContainer containerFor(
  FakeBackend backend, {
  FakeTokenStore? tokens,
  SessionCore? session,
  DateTime Function()? now,
}) {
  final store = tokens ?? FakeTokenStore();
  final core = session ?? backend.session;
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      sessionCoreProvider.overrideWithValue(core),
      apiClientProvider.overrideWithValue(apiClientFor(backend, core)),
      if (now != null) clockProvider.overrideWithValue(now),
    ],
  );
}

/// A launch, finished: the stored record read and the stored member's
/// account confirmed by `/api/me`. For a plain test, on real time; a widget
/// test uses [launchPumped].
Future<void> launch(ProviderContainer container) async {
  container.read(sessionProvider);
  await container.read(sessionCoreProvider).load();
  await container.read(sessionProvider.notifier).refreshAccount();
}

/// [launch] under a widget test's fake clock, before the first frame.
///
/// Not `tester.runAsync`: the core's queue would then end on a future of the
/// real event loop, and the next write the test makes on the fake clock would
/// wait on it for real time.
Future<void> launchPumped(WidgetTester tester, ProviderContainer container) =>
    _pumped(tester, launch(container));

Future<void> _pumped(WidgetTester tester, Future<void> work) async {
  var done = false;
  final watched = work.whenComplete(() => done = true);
  for (var i = 0; i < 100 && !done; i++) {
    await tester.pump(const Duration(milliseconds: 10));
  }
  await watched;
}

/// The real [ApiClient] of [session] (by default the backend's), talking to
/// [backend].
///
/// Exposed for a test that needs to build its own container — one standing in
/// for a camera, say. `Override` is not nameable from Riverpod 3's public API,
/// so the override list has to be written as a literal at the call site rather
/// than passed in here: `sessionCoreProvider` with `backend.session`, then
/// `apiClientProvider` with this.
ApiClient apiClientFor(FakeBackend backend, [SessionCore? session]) =>
    ApiClient(
      session: session ?? backend.session,
      dio: Dio()..httpClientAdapter = _FakeAdapter(backend),
    );

// ---------------------------------------------------------------------------
// Fixtures, shaped from the real Phase 6C responses
// ---------------------------------------------------------------------------

/// `GET /api/me`.
///
/// [preferredLanguage] is passed through verbatim, including `null` and `''`,
/// so a test can reproduce a legacy row exactly as an older deployment would
/// serialise it rather than as the client wishes it looked.
Map<String, dynamic> meFixture({
  Object? preferredLanguage = 'en',
  int id = 42,
}) => {
  'id': id,
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
  int freeWeightKg = 8,
  Map<String, dynamic>? price,
}) => {
  'journey_id': id,
  'traveler': discoveryPersonFields(
    name: name,
    rating: {'state': 'rated', 'average': 4.8, 'count': 24},
    deliveries: 3,
  ),
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
  'free_weight_kg': freeWeightKg,
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
