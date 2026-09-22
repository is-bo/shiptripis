/// K5: the launch snapshot of the signed-in profile.
///
/// A cold start with a snapshot enters the app at once and lets `/api/me`
/// confirm it in the background. These tests hold the rest of the contract:
/// the server still decides who is signed in, the snapshot never outlives the
/// credentials it was read under, and it carries presentation fields only.
///
/// The keystore here is the real [TokenStore] over in-memory storage, so what
/// is asserted about keys is what the device would hold. Widget tests, not
/// plain tests, for the fake clock: the revalidation timer runs in seconds.
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/token_store.dart';
import 'package:shiptrip/domain/account.dart';

import 'support/fake_api.dart';

const _kAccess = 'auth.access';
const _kRefresh = 'auth.refresh';
const _kSnapshot = 'auth.account_snapshot';

/// Exactly what [Account.fromJson] reads, and nothing else.
const _presentationKeys = {
  'id',
  'email',
  'full_name',
  'phone',
  'wilaya',
  'role',
  'preferred_language',
  'is_email_verified',
  'is_phone_verified',
  'is_kyc_verified',
  'kyc_status',
  'kyc_rejection_reason',
  'date_joined',
};

class _MemoryStorage extends FlutterSecureStorage {
  _MemoryStorage();

  final values = <String, String>{};

  @override
  Future<String?> read({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async => values[key];

  @override
  Future<void> write({
    required String key,
    required String? value,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    if (value == null) {
      values.remove(key);
    } else {
      values[key] = value;
    }
  }

  @override
  Future<void> delete({
    required String key,
    AndroidOptions? aOptions,
    IOSOptions? iOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    values.remove(key);
  }
}

String _snapshotOf(Map<String, dynamic> me) =>
    jsonEncode(Account.fromJson(me).toSnapshotJson());

/// A device that signed in before: tokens, and optionally a snapshot.
_MemoryStorage _device({String? snapshot}) => _MemoryStorage()
  ..values[_kAccess] = 'old-access'
  ..values[_kRefresh] = 'old-refresh'
  ..values.addAll({_kSnapshot: ?snapshot});

final _cachedMe = {...meFixture(), 'full_name': 'Cached Name'};

/// The session over [backend] and [tokens], with the terminal-refresh path
/// wired exactly as `apiClientProvider` wires it in the app.
ProviderContainer _container(FakeBackend backend, TokenStore tokens) =>
    ProviderContainer(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWith((ref) {
          final client = apiClientFor(
            backend,
            tokens,
            onSessionExpired: () =>
                ref.read(sessionProvider.notifier).handleSessionExpired(),
          );
          ref.onDispose(() => client.raw.close(force: true));
          return client;
        }),
      ],
    );

Never _offline(RecordedRequest r) => throw DioException(
  requestOptions: RequestOptions(path: r.path),
  type: DioExceptionType.connectionError,
);

/// Lets queued storage and HTTP work finish under the fake clock.
Future<void> _flush(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 10));
  }
}

/// Awaits [work] while the fake clock runs.
Future<T> _drive<T>(WidgetTester tester, Future<T> work) async {
  await _flush(tester);
  return work;
}

Map<String, dynamic>? _stored(_MemoryStorage storage) {
  final raw = storage.values[_kSnapshot];
  return raw == null ? null : jsonDecode(raw) as Map<String, dynamic>;
}

void main() {
  testWidgets('a snapshot signs in before /api/me answers', (tester) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()..handle('GET', '/api/me', (_) => me.future);
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));

    container.read(sessionProvider);
    await _flush(tester);

    final early = container.read(sessionProvider);
    expect(early, isA<SessionSignedIn>());
    expect((early as SessionSignedIn).account.fullName, 'Cached Name');
    expect(backend.to('GET', '/api/me'), hasLength(1), reason: 'in flight');

    me.complete(FakeResponse(200, meFixture()));
    await _flush(tester);

    final confirmed = container.read(sessionProvider) as SessionSignedIn;
    expect(confirmed.account.fullName, 'Amina Bouzid');
    expect(confirmed.generation, early.generation, reason: 'same account');
    expect(_stored(storage)?['full_name'], 'Amina Bouzid');

    container.dispose();
  });

  testWidgets('a malformed snapshot is no snapshot', (tester) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()..handle('GET', '/api/me', (_) => me.future);
    final container = _container(
      backend,
      TokenStore(_device(snapshot: '{not json')),
    );

    container.read(sessionProvider);
    await _flush(tester);
    expect(container.read(sessionProvider), isA<SessionRestoring>());

    me.complete(FakeResponse(200, meFixture()));
    await _flush(tester);
    expect(container.read(sessionProvider), isA<SessionSignedIn>());
    container.dispose();
  });

  testWidgets('offline with a snapshot stays in, then revalidates on a timer', (
    tester,
  ) async {
    var offline = true;
    final backend = FakeBackend()
      ..handle(
        'GET',
        '/api/me',
        (r) => offline ? _offline(r) : FakeResponse(200, meFixture()),
      );
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));
    final states = <SessionState>[];
    container.listen(sessionProvider, (_, next) => states.add(next));

    container.read(sessionProvider);
    // The first confirmation, including the client's own two retries.
    await tester.pump(const Duration(seconds: 2));
    final afterLaunch = backend.to('GET', '/api/me').length;
    expect(afterLaunch, greaterThan(0));
    expect(
      (container.read(sessionProvider) as SessionSignedIn).account.fullName,
      'Cached Name',
    );

    // Nothing until the first revalidation is due, ten seconds on.
    await tester.pump(const Duration(seconds: 7));
    expect(backend.to('GET', '/api/me'), hasLength(afterLaunch));

    offline = false;
    await tester.pump(const Duration(seconds: 3));
    await _flush(tester);
    expect(backend.to('GET', '/api/me').length, greaterThan(afterLaunch));
    expect(
      (container.read(sessionProvider) as SessionSignedIn).account.fullName,
      'Amina Bouzid',
    );
    expect(states.whereType<SessionSignedOut>(), isEmpty);
    expect(
      states
          .skipWhile((s) => s is! SessionSignedIn)
          .whereType<SessionRestoring>(),
      isEmpty,
      reason: 'never back to the splash once in',
    );
    expect(storage.values[_kRefresh], 'old-refresh');

    container.dispose();
  });

  testWidgets('offline without a snapshot holds the splash, as before', (
    tester,
  ) async {
    final backend = FakeBackend()..handle('GET', '/api/me', _offline);
    final storage = _device();
    final container = _container(backend, TokenStore(storage));

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 2));
    final calls = backend.to('GET', '/api/me').length;
    expect(container.read(sessionProvider), isA<SessionRestoring>());

    // No revalidation timer on this path: the splash's retry owns it.
    await tester.pump(const Duration(seconds: 200));
    expect(backend.to('GET', '/api/me'), hasLength(calls));
    expect(container.read(sessionProvider), isA<SessionRestoring>());
    expect(storage.values[_kRefresh], 'old-refresh');

    container.dispose();
  });

  testWidgets('a rejected credential signs out and clears the snapshot', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', const FakeResponse(401))
      ..on('POST', '/api/auth/refresh', const FakeResponse(401));
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 1));
    await _flush(tester);

    expect(container.read(sessionProvider), isA<SessionSignedOut>());
    expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
    expect(storage.values.keys, isNot(contains(_kSnapshot)));
    expect(storage.values.keys, isNot(contains(_kAccess)));
    expect(storage.values.keys, isNot(contains(_kRefresh)));

    container.dispose();
  });

  testWidgets('another account from /api/me replaces the snapshot account', (
    tester,
  ) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()..handle('GET', '/api/me', (_) => me.future);
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));

    container.read(sessionProvider);
    await _flush(tester);
    final cached = container.read(accountSessionProvider);
    expect(cached?.accountId, 42);

    me.complete(
      FakeResponse(200, {...meFixture(), 'id': 99, 'email': 'b@example.com'}),
    );
    await _flush(tester);

    final session = container.read(accountSessionProvider);
    expect(session?.accountId, 99);
    expect(
      session?.generation,
      isNot(cached?.generation),
      reason: 'every account-scoped read moves to a fresh generation',
    );
    expect(_stored(storage)?['id'], 99);

    container.dispose();
  });

  testWidgets('sign-out deletes the snapshot before its network call', (
    tester,
  ) async {
    final signOut = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('POST', '/api/auth/sign-out', (_) => signOut.future);
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));
    container.read(sessionProvider);
    await _flush(tester);
    expect(storage.values.keys, contains(_kSnapshot));

    final leaving = container.read(sessionProvider.notifier).signOut();
    await _flush(tester);
    expect(backend.to('POST', '/api/auth/sign-out'), hasLength(1));
    expect(storage.values.keys, isNot(contains(_kSnapshot)));

    signOut.complete(const FakeResponse(205));
    await _drive(tester, leaving);
    expect(storage.values.keys, isNot(contains(_kRefresh)));

    container.dispose();
  });

  testWidgets('a confirmation landing after sign-out writes nothing', (
    tester,
  ) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..handle('GET', '/api/me', (_) => me.future)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));
    container.read(sessionProvider);
    await _flush(tester);

    await _drive(tester, container.read(sessionProvider.notifier).signOut());
    me.complete(FakeResponse(200, meFixture()));
    await _flush(tester);

    expect(container.read(sessionProvider), isA<SessionSignedOut>());
    expect(storage.values.keys, isNot(contains(_kSnapshot)));

    container.dispose();
  });

  testWidgets('signing in as another account replaces the snapshot', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
      ..on(
        'POST',
        '/api/auth/sign-in',
        FakeResponse(200, {
          'access': 'b-access',
          'refresh': 'b-refresh',
          'user': {...meFixture(), 'id': 99, 'email': 'b@example.com'},
        }),
      );
    final storage = _device(snapshot: _snapshotOf(_cachedMe));
    final container = _container(backend, TokenStore(storage));
    container.read(sessionProvider);
    await _flush(tester);
    expect(_stored(storage)?['id'], 42);

    // Straight from one account to the next, without a sign-out between.
    await _drive(
      tester,
      container
          .read(sessionProvider.notifier)
          .signIn(email: 'b@example.com', password: 'secret'),
    );
    await _flush(tester);

    expect(_stored(storage)?['id'], 99);
    expect(storage.values[_kRefresh], 'b-refresh');

    container.dispose();
  });

  testWidgets('the revalidation timer dies with sign-out', (tester) async {
    final backend = FakeBackend()
      ..handle('GET', '/api/me', _offline)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final container = _container(
      backend,
      TokenStore(_device(snapshot: _snapshotOf(_cachedMe))),
    );
    final states = <SessionState>[];
    container.listen(sessionProvider, (_, next) => states.add(next));

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 2));
    expect(container.read(sessionProvider), isA<SessionSignedIn>());

    await _drive(tester, container.read(sessionProvider.notifier).signOut());
    final calls = backend.to('GET', '/api/me').length;
    final settled = states.length;
    await tester.pump(const Duration(seconds: 200));

    expect(backend.to('GET', '/api/me'), hasLength(calls));
    expect(states, hasLength(settled), reason: 'no late state change');
    expect(container.read(sessionProvider), isA<SessionSignedOut>());

    container.dispose();
  });

  testWidgets('the revalidation timer dies with the container', (tester) async {
    final backend = FakeBackend()..handle('GET', '/api/me', _offline);
    final container = _container(
      backend,
      TokenStore(_device(snapshot: _snapshotOf(_cachedMe))),
    );

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 2));
    final calls = backend.to('GET', '/api/me').length;

    container.dispose();
    await tester.pump(const Duration(seconds: 200));
    expect(backend.to('GET', '/api/me'), hasLength(calls));
  });

  testWidgets('the snapshot holds presentation fields only', (tester) async {
    final backend = FakeBackend()
      ..on(
        'POST',
        '/api/auth/sign-in',
        FakeResponse(200, {
          'access': 'secret-access-token',
          'refresh': 'secret-refresh-token',
          'user': {
            ...meFixture(),
            // What a richer profile might one day carry. None of it belongs
            // on the device.
            'iban': 'DZ5800020000000000000000',
            'payout_methods': [
              {'id': 1, 'account_number': '0002000000000'},
            ],
            'kyc_documents': [
              {'id': 3, 'url': 'https://files/passport.jpg'},
            ],
            'access': 'secret-access-token',
          },
        }),
      );
    final storage = _MemoryStorage();
    final container = _container(backend, TokenStore(storage));
    container.read(sessionProvider);
    await _flush(tester);
    expect(container.read(sessionProvider), isA<SessionSignedOut>());

    await _drive(
      tester,
      container
          .read(sessionProvider.notifier)
          .signIn(email: 'sender@example.com', password: 'secret'),
    );
    await _flush(tester);

    final raw = storage.values[_kSnapshot]!;
    expect((jsonDecode(raw) as Map).keys.toSet(), _presentationKeys);
    for (final secret in [
      'secret-access-token',
      'secret-refresh-token',
      'DZ58',
      '0002000000000',
      'passport',
    ]) {
      expect(raw, isNot(contains(secret)));
    }

    container.dispose();
  });

  group('TokenStore snapshot', () {
    (TokenStore, _MemoryStorage) seeded() {
      final storage = _device(snapshot: _snapshotOf(meFixture()));
      return (TokenStore(storage), storage);
    }

    test('a new sign-in deletes it', () async {
      final (tokens, storage) = seeded();
      final saved = await tokens.saveAuthenticationIfCurrent(
        expectedIdentityGeneration: tokens.invalidateIdentity(),
        access: 'b-access',
        refresh: 'b-refresh',
      );
      expect(saved, isTrue);
      expect(storage.values.keys, isNot(contains(_kSnapshot)));
    });

    test('saving credentials deletes it', () async {
      final (tokens, storage) = seeded();
      await tokens.save(access: 'b-access', refresh: 'b-refresh');
      expect(storage.values.keys, isNot(contains(_kSnapshot)));
    });

    test('a terminal clear deletes it', () async {
      final (tokens, storage) = seeded();
      expect(
        await tokens.clearIfIdentityCurrent(tokens.identityGeneration),
        isTrue,
      );
      expect(storage.values.keys, isNot(contains(_kSnapshot)));
    });

    test('a plain clear deletes it', () async {
      final (tokens, storage) = seeded();
      await tokens.clear();
      expect(storage.values.keys, isNot(contains(_kSnapshot)));
    });

    test('a write from an older identity is refused', () async {
      final storage = _device();
      final tokens = TokenStore(storage);
      final identity = tokens.identityGeneration;
      tokens.invalidateIdentity();

      final written = await tokens.writeAccountSnapshotIfCurrent(
        expectedIdentityGeneration: identity,
        json: _snapshotOf(meFixture()),
      );

      expect(written, isFalse);
      expect(storage.values.keys, isNot(contains(_kSnapshot)));
      expect(await tokens.readAccountSnapshot(), isNull);
    });

    test('a current write is kept and read back', () async {
      final tokens = TokenStore(_device());
      final json = _snapshotOf(meFixture());
      expect(
        await tokens.writeAccountSnapshotIfCurrent(
          expectedIdentityGeneration: tokens.identityGeneration,
          json: json,
        ),
        isTrue,
      );
      expect(await tokens.readAccountSnapshot(), json);
    });
  });
}
