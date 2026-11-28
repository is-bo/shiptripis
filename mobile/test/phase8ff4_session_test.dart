import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';

import 'support/fake_api.dart';

/// Ends sign-in `sid-a` and signs in `sid-b` of account 99: the only way
/// from one sign-in to the next.
Future<void> _signOutThenIn(SessionCore core) async {
  await core.end('sid-a', EndReason.signedOut);
  await core.signedIn(
    core.reserve()!,
    signInFor(sid: 'sid-b', account: {...meFixture(), 'id': 99}),
  );
}

Matcher get _cancelled => throwsA(
  isA<ApiException>().having(
    (error) => error.kind,
    'kind',
    ApiFailureKind.cancelled,
  ),
);

void main() {
  test(
    'a delayed profile refresh cannot revive the previous account',
    () async {
      final delayedProfile = Completer<FakeResponse>();
      var meReads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          meReads++;
          if (meReads == 1) return FakeResponse(200, meFixture());
          return delayedProfile.future;
        })
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..on(
          'POST',
          '/api/auth/sign-in',
          signInAnswer(user: {...meFixture(), 'id': 99, 'email': 'n@x.com'}),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);
      container.read(sessionProvider);
      await backend.session.load();
      await _waitFor(() => meReads == 1);

      final refresh = container.read(sessionProvider.notifier).refreshAccount();
      await _waitFor(() => meReads == 2);
      await container.read(sessionProvider.notifier).signOut();
      await container
          .read(sessionProvider.notifier)
          .signIn(email: 'n@x.com', password: 'correct horse');
      delayedProfile.complete(FakeResponse(200, meFixture()));
      await refresh;

      final session = container.read(sessionProvider);
      expect(session, isA<SessionSignedIn>());
      expect((session as SessionSignedIn).account.id, 99);
    },
  );

  test('reconnect probe uses the existing single-flight HTTP flow', () async {
    var meReads = 0;
    final backend = FakeBackend()
      ..handle('GET', '/api/me', (_) {
        meReads++;
        return meReads <= 2
            ? const FakeResponse(401)
            : FakeResponse(200, meFixture());
      })
      ..on(
        'POST',
        '/api/auth/refresh',
        FakeResponse(200, {'access': fakeToken('sid-a', 'rotated')}),
      );
    await backend.session.load();
    final api = apiClientFor(backend);
    addTearDown(() => api.raw.close(force: true));

    final results = await Future.wait([
      api.getObject('/api/me'),
      api.getObject('/api/me'),
    ]);

    expect(results, everyElement(meFixture()));
    expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
  });

  test('an old 401 is never replayed with the next sign-in\'s token', () async {
    final staleResponse = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..handle('GET', '/api/protected', (_) => staleResponse.future)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final core = backend.session;
    await core.load();
    final api = apiClientFor(backend);
    addTearDown(() => api.raw.close(force: true));

    final oldRead = api.getObject('/api/protected');
    await _waitFor(() => backend.to('GET', '/api/protected').isNotEmpty);
    await _signOutThenIn(core);
    staleResponse.complete(const FakeResponse(401));

    await expectLater(oldRead, throwsA(isA<Object>()));
    expect(backend.to('GET', '/api/protected'), hasLength(1));
    expect(backend.to('POST', '/api/auth/refresh'), isEmpty);
    expect(core.accessFor('sid-b'), fakeToken('sid-b', 'access'));
  });

  test(
    'a successful read of the previous sign-in is discarded after it ends',
    () async {
      final staleResponse = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..handle('GET', '/api/protected', (_) => staleResponse.future)
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final core = backend.session;
      await core.load();
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      final oldRead = api.getObject('/api/protected');
      await _waitFor(() => backend.to('GET', '/api/protected').isNotEmpty);
      await _signOutThenIn(core);
      staleResponse.complete(const FakeResponse(200, {'private': 'old-data'}));

      await expectLater(oldRead, _cancelled);
    },
  );

  test('an in-flight refresh cannot overwrite a sign-out and a new sign-in, '
      'and its request is refused, not replayed', () async {
    final oldRefresh = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/protected', const FakeResponse(401))
      ..handle('POST', '/api/auth/refresh', (_) => oldRefresh.future)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final core = backend.session;
    await core.load();
    final api = apiClientFor(backend);
    addTearDown(() => api.raw.close(force: true));

    final oldRead = api.getObject('/api/protected');
    await _waitFor(() => backend.to('POST', '/api/auth/refresh').isNotEmpty);
    await _signOutThenIn(core);
    oldRefresh.complete(
      FakeResponse(200, {
        'access': fakeToken('sid-a', 'stale-rotated'),
        'refresh': fakeToken('sid-a', 'stale-rotated-refresh'),
      }),
    );

    await expectLater(oldRead, _cancelled);
    expect(core.current?.sid, 'sid-b');
    expect(core.current?.access, fakeToken('sid-b', 'access'));
    expect(core.current?.refresh, fakeToken('sid-b'));
    expect(backend.to('GET', '/api/protected'), hasLength(1));
  });

  // The bearer is read from the core's memory in the same step that sends the
  // request, so the windows the earlier token reads opened are gone. What
  // stays is the rule: a request of a sign-in that ended is refused before it
  // leaves, never sent with the next one's bearer.
  test('a request of an ended sign-in is refused before it is sent', () async {
    final backend = FakeBackend()
      ..on('GET', '/api/protected', const FakeResponse(200, {'ok': true}))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final core = backend.session;
    await core.load();
    final api = apiClientFor(backend);
    addTearDown(() => api.raw.close(force: true));
    await _signOutThenIn(core);

    await expectLater(
      api.raw.get<dynamic>(
        '/api/protected',
        options: Options(extra: {'st.sid': 'sid-a'}),
      ),
      throwsA(isA<DioException>()),
    );
    expect(backend.to('GET', '/api/protected'), isEmpty);
  });

  test('a second sign-in while the first is answered starts nothing', () async {
    final first = Completer<FakeResponse>();
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('POST', '/api/auth/sign-in', (_) => first.future);
    backend.session = coreFor(backend, signedIn: false);
    final container = containerFor(backend);
    addTearDown(container.dispose);
    await launch(container);

    final session = container.read(sessionProvider.notifier);
    final firstLogin = session.signIn(email: 'first@x.com', password: 's');
    expect(await session.signIn(email: 'second@x.com', password: 's'), isFalse);
    first.complete(
      signInAnswer(user: {...meFixture(), 'id': 101, 'email': 'first@x.com'}),
    );
    expect(await firstLogin, isTrue);

    expect(backend.to('POST', '/api/auth/sign-in'), hasLength(1));
    final signedIn = container.read(sessionProvider) as SessionSignedIn;
    expect(signedIn.account.id, 101);
  });

  // N1 round 5. A sign-in the app lets go of because renewing it failed may
  // still be live on the server, with this phone's notifications switched on
  // (its refresh token expired while the app went unopened, or a rotation's
  // answer was lost). The app ends it there too, by that refresh token alone.
  group('a session the app lets go of', () {
    FakeBackend refusingRenewal() => FakeBackend()
      ..on('GET', '/api/protected', const FakeResponse(401))
      ..on('POST', '/api/auth/refresh', const FakeResponse(401))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));

    test('is ended on the server by its refresh token alone', () async {
      final backend = refusingRenewal();
      final storage = MemoryStorage({SessionCore.recordKey: signedInRecord()});
      final core = backend.session = coreFor(backend, storage: storage);
      await core.load();
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      await expectLater(
        api.getObject('/api/protected'),
        throwsA(isA<Object>()),
      );
      await _waitFor(() => storage.record!.ended.isEmpty);

      final signOut = backend.to('POST', '/api/auth/sign-out').single;
      expect(signOut.body, {'refresh': fakeToken('sid-a')});
      expect(signOut.headers, isNot(contains('Authorization')));
      expect(core.current, isNull);
      expect(core.notice, EndReason.refused);
    });

    test('never lends it the bearer of a sign-in made meanwhile', () async {
      final backend = refusingRenewal();
      final core = backend.session;
      await core.load();
      // Someone signs in the moment the session ends, before its sign-out
      // has left the phone.
      core.addListener(() {
        final attempt = core.reserve();
        if (attempt != null) {
          unawaited(core.signedIn(attempt, signInFor(sid: 'sid-b')));
        }
      });
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      await expectLater(
        api.getObject('/api/protected'),
        throwsA(isA<Object>()),
      );
      await _waitFor(() => backend.to('POST', '/api/auth/sign-out').isNotEmpty);

      final signOut = backend.to('POST', '/api/auth/sign-out').single;
      expect(signOut.body, {'refresh': fakeToken('sid-a')});
      expect(signOut.headers, isNot(contains('Authorization')));
      await _waitFor(() => core.current != null);
      expect(core.current?.sid, 'sid-b');
    });

    test('is still signed out when that sign-out fails, and is sent again '
        'later', () async {
      final backend = refusingRenewal()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(503));
      final storage = MemoryStorage({SessionCore.recordKey: signedInRecord()});
      final core = backend.session = coreFor(backend, storage: storage);
      await core.load();
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      await expectLater(
        api.getObject('/api/protected'),
        throwsA(isA<Object>()),
      );
      await _waitFor(() => backend.to('POST', '/api/auth/sign-out').isNotEmpty);

      expect(core.current, isNull);
      expect(storage.record!.current, isNull);
      expect(storage.record!.ended.single.sid, 'sid-a');
      expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
    });
  });
}

Future<void> _waitFor(bool Function() condition) async {
  for (var attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  throw TimeoutException('Condition was not reached.');
}
