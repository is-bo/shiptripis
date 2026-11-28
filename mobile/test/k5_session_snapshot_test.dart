/// K5: the launch snapshot of the signed-in profile.
///
/// A cold start with a stored sign-in enters the app at once, from the
/// account stored with it, and lets `/api/me` confirm it in the background.
/// These tests hold the rest of the contract: the server still decides who is
/// signed in, the account never outlives the sign-in it was read under, and it
/// carries presentation fields only.
///
/// The keystore here is the real [SessionCore] over in-memory storage, so what
/// is asserted about the record is what the device would hold. Widget tests,
/// not plain tests, for the fake clock: the revalidation timer runs in
/// seconds.
library;

import 'dart:async';
import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/core/session/token_store.dart';

import 'support/fake_api.dart';

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

final _cachedMe = {...meFixture(), 'full_name': 'Cached Name'};

/// A phone on which [meFixture] signed in before, shown as [_cachedMe].
MemoryStorage _device() =>
    MemoryStorage({SessionCore.recordKey: signedInRecord(account: _cachedMe)});

/// The session over [backend] and the record in [storage].
ProviderContainer _container(FakeBackend backend, MemoryStorage storage) {
  backend.session = coreFor(backend, storage: storage);
  return containerFor(backend);
}

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

/// The account stored with the current sign-in, as JSON.
Map<String, dynamic>? _stored(MemoryStorage storage) {
  final current =
      (jsonDecode(storage.values[SessionCore.recordKey]!) as Map)['current'];
  return current == null ? null : current['account'] as Map<String, dynamic>;
}

void main() {
  testWidgets('a stored sign-in shows before /api/me answers', (tester) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()..handle('GET', '/api/me', (_) => me.future);
    final storage = _device();
    final container = _container(backend, storage);

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
    expect(confirmed.sid, early.sid, reason: 'the same sign-in');
    expect(_stored(storage)?['full_name'], 'Amina Bouzid');

    container.dispose();
  });

  testWidgets('offline with a stored sign-in stays in, then revalidates on a '
      'timer', (tester) async {
    var offline = true;
    final backend = FakeBackend()
      ..handle(
        'GET',
        '/api/me',
        (r) => offline ? _offline(r) : FakeResponse(200, meFixture()),
      );
    final storage = _device();
    final container = _container(backend, storage);
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
    expect(storage.record!.current?.refresh, fakeToken('sid-a'));

    container.dispose();
  });

  testWidgets('a refused refresh token signs out and leaves no account on the '
      'phone', (tester) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', const FakeResponse(401))
      ..on('POST', '/api/auth/refresh', const FakeResponse(401))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final storage = _device();
    final container = _container(backend, storage);

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 1));
    await _flush(tester);

    final state = container.read(sessionProvider);
    expect(state, isA<SessionSignedOut>());
    expect((state as SessionSignedOut).becauseExpired, isTrue);
    expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
    expect(storage.record!.current, isNull);
    expect(storage.values[SessionCore.recordKey], isNot(contains('Cached')));

    container.dispose();
  });

  testWidgets('sign-out stores the end before its network call', (
    tester,
  ) async {
    final signOut = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('POST', '/api/auth/sign-out', (_) => signOut.future);
    final storage = _device();
    final container = _container(backend, storage);
    container.read(sessionProvider);
    await _flush(tester);
    expect(_stored(storage), isNotNull);

    await _drive(tester, container.read(sessionProvider.notifier).signOut());
    expect(backend.to('POST', '/api/auth/sign-out'), hasLength(1));
    expect(_stored(storage), isNull);
    expect(storage.record!.ended.single.sid, 'sid-a');

    signOut.complete(const FakeResponse(205));
    await _flush(tester);
    expect(storage.record!.ended, isEmpty);

    container.dispose();
  });

  testWidgets('an account write queued before sign-out lands before it, and '
      'one queued after it writes nothing', (tester) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final storage = _device();
    final container = _container(backend, storage);
    container.read(sessionProvider);
    await _flush(tester);
    final core = container.read(sessionCoreProvider);
    final renamed = {...meFixture(), 'full_name': 'Renamed'};
    final writes = storage.writes;

    // A profile read's account write, still queued when the member taps.
    final before = core.updateAccount(
      'sid-a',
      signInFor(account: renamed).account,
    );
    final leaving = container.read(sessionProvider.notifier).signOut();
    final after = core.updateAccount(
      'sid-a',
      signInFor(account: renamed).account,
    );
    await _drive(tester, Future.wait([before, leaving, after]));

    expect(container.read(sessionProvider), isA<SessionSignedOut>());
    expect(_stored(storage), isNull);
    expect(
      storage.writes,
      writes + 3,
      reason: 'the account, the end, the server\'s confirmation: no more',
    );

    container.dispose();
  });

  for (final (name, answer)
      in <(String, FakeResponse Function(RecordedRequest))>[
        (
          'is cancelled',
          (r) => throw DioException(
            requestOptions: RequestOptions(path: r.path),
            type: DioExceptionType.cancel,
          ),
        ),
        ('is a stale 401', (_) => const FakeResponse(401)),
      ]) {
    testWidgets('a launch confirmation that $name after another request ended '
        'the session keeps the expiry message', (tester) async {
      final storage = _device();
      late final SessionCore core;
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..handle('GET', '/api/me', (r) async {
          // Another request's refused refresh ends the sign-in first.
          await core.end('sid-a', EndReason.refused);
          return answer(r);
        });
      final container = _container(backend, storage);
      core = backend.session;

      container.read(sessionProvider);
      await _flush(tester);

      final state = container.read(sessionProvider);
      expect(state, isA<SessionSignedOut>());
      expect((state as SessionSignedOut).becauseExpired, isTrue);
      expect(storage.record!.current, isNull);

      container.dispose();
    });
  }

  testWidgets('a confirmation landing after sign-out writes nothing', (
    tester,
  ) async {
    final me = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..handle('GET', '/api/me', (_) => me.future)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final storage = _device();
    final container = _container(backend, storage);
    container.read(sessionProvider);
    await _flush(tester);

    await _drive(tester, container.read(sessionProvider.notifier).signOut());
    final writes = storage.writes;
    me.complete(FakeResponse(200, meFixture()));
    await _flush(tester);

    expect(container.read(sessionProvider), isA<SessionSignedOut>());
    expect(_stored(storage), isNull);
    expect(storage.writes, writes);

    container.dispose();
  });

  testWidgets('another account starts from signed out: a sign-in while one is '
      'current starts nothing', (tester) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
      ..on(
        'POST',
        '/api/auth/sign-in',
        signInAnswer(user: {...meFixture(), 'id': 99, 'email': 'b@x.com'}),
      );
    final storage = _device();
    final container = _container(backend, storage);
    container.read(sessionProvider);
    await _flush(tester);
    expect(_stored(storage)?['id'], 42);

    final session = container.read(sessionProvider.notifier);
    expect(
      await _drive(tester, session.signIn(email: 'b@x.com', password: 's')),
      isFalse,
    );
    expect(backend.to('POST', '/api/auth/sign-in'), isEmpty);
    expect(_stored(storage)?['id'], 42);

    await _drive(tester, session.signOut());
    expect(
      await _drive(tester, session.signIn(email: 'b@x.com', password: 's')),
      isTrue,
    );
    expect(_stored(storage)?['id'], 99);
    expect(storage.record!.current?.refresh, fakeToken('sid-b'));

    container.dispose();
  });

  testWidgets('the revalidation timer dies with sign-out', (tester) async {
    final backend = FakeBackend()
      ..handle('GET', '/api/me', _offline)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final container = _container(backend, _device());
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
    final container = _container(backend, _device());

    container.read(sessionProvider);
    await tester.pump(const Duration(seconds: 2));
    final calls = backend.to('GET', '/api/me').length;

    container.dispose();
    await tester.pump(const Duration(seconds: 200));
    expect(backend.to('GET', '/api/me'), hasLength(calls));
  });

  testWidgets('the stored account holds presentation fields only', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on(
        'POST',
        '/api/auth/sign-in',
        signInAnswer(
          sid: 'sid-b',
          user: {
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
        ),
      );
    final storage = MemoryStorage();
    final container = _container(backend, storage);
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

    final account = _stored(storage)!;
    expect(account.keys.toSet(), _presentationKeys);
    final raw = jsonEncode(account);
    for (final secret in [
      'secret-access-token',
      fakeToken('sid-b', 'access'),
      fakeToken('sid-b'),
      'DZ58',
      '0002000000000',
      'passport',
    ]) {
      expect(raw, isNot(contains(secret)));
    }

    container.dispose();
  });

  // The phone's own keys sit beside the record and outlive every sign-in.
  group('the phone\'s own keys', () {
    /// One keystore holding both, and a sign-out through the core.
    Future<TokenStore> afterSignOut(
      MemoryStorage storage,
      Future<void> Function(TokenStore) before,
    ) async {
      final tokens = TokenStore(storage);
      await before(tokens);
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final core = coreFor(backend, storage: storage);
      await core.load();
      await core.end('sid-a', EndReason.signedOut);
      return tokens;
    }

    test(
      'the notification request count belongs to the phone, not the account',
      () async {
        final storage = MemoryStorage({
          SessionCore.recordKey: signedInRecord(),
        });
        final tokens = await afterSignOut(storage, (tokens) async {
          expect(await tokens.readPushPermissionRequests(), 0);
          expect(await tokens.recordPushPermissionRequest(), 1);
        });
        expect(storage.record!.current, isNull);
        expect(await tokens.readPushPermissionRequests(), 1);
        expect(await tokens.recordPushPermissionRequest(), 2);
      },
    );

    test(
      'push registrations are numbered one after another, for good',
      () async {
        final storage = MemoryStorage({
          SessionCore.recordKey: signedInRecord(),
        });
        final tokens = await afterSignOut(storage, (tokens) async {
          final numbers = await Future.wait([
            tokens.nextPushBindingSequence(),
            tokens.nextPushBindingSequence(),
            tokens.nextPushBindingSequence(),
          ]);
          expect(numbers..sort(), [1, 2, 3], reason: 'no two share one');
        });
        expect(
          await tokens.nextPushBindingSequence(),
          4,
          reason: 'sign-out keeps it',
        );

        await tokens.raisePushBindingSequence(40);
        expect(await tokens.nextPushBindingSequence(), 41);
        await tokens.raisePushBindingSequence(7);
        expect(
          await tokens.nextPushBindingSequence(),
          42,
          reason: 'never lowered',
        );
      },
    );

    test('a request count taken back never goes below nothing', () async {
      final tokens = TokenStore(MemoryStorage());
      expect(await tokens.releasePushPermissionRequest(), 0);
      expect(await tokens.recordPushPermissionRequest(), 1);
      expect(await tokens.releasePushPermissionRequest(), 0);
      expect(await tokens.readPushPermissionRequests(), 0);
    });
  });
}
