/// S1-A: the phone's session record and core (plan rules S-1, S-2, S-3, S-5
/// and S-6, brief section 6).
///
/// The storage is in memory and can refuse a read or a write; the server is
/// the fake under the real client. Everything between is production code.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/domain/communication_language.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

final _refused = StateError('the keystore refused');

DioException _network(RecordedRequest r, [DioExceptionType? type]) =>
    DioException(
      requestOptions: RequestOptions(path: r.path),
      type: type ?? DioExceptionType.connectionError,
    );

/// A phone on which [meFixture] is signed in as `sid-a`, with [ended] still
/// to be confirmed.
MemoryStorage _phone({List<EndedSignIn> ended = const []}) =>
    MemoryStorage({SessionCore.recordKey: signedInRecord(ended: ended)});

/// The same phone after a restart: a new core over the same storage.
Future<SessionCore> _restart(FakeBackend backend, MemoryStorage storage) async {
  final core = coreFor(backend, storage: storage);
  await core.load();
  return core;
}

/// The session over [storage]: [backend] answers, and its core is the app's.
ProviderContainer _app(FakeBackend backend, MemoryStorage storage) {
  backend.session = coreFor(backend, storage: storage);
  final container = containerFor(backend);
  addTearDown(container.dispose);
  return container;
}

/// Advances the fake clock by [span], then lets queued work finish.
Future<void> _settle(
  WidgetTester tester, [
  Duration span = Duration.zero,
]) async {
  await tester.pump(span);
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 10));
  }
}

/// The app started: the record read and the launch read of `/api/me` sent.
Future<void> _started(ProviderContainer container) async {
  container.read(sessionProvider);
  await container.read(sessionCoreProvider).load();
}

Future<void> _waitFor(bool Function() condition) async {
  for (var i = 0; i < 200 && !condition(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  expect(condition(), isTrue);
}

String _lib(String path) => File('lib/$path').readAsStringSync();

Iterable<File> _libFiles() => Directory('lib')
    .listSync(recursive: true)
    .whereType<File>()
    .where((f) => f.path.endsWith('.dart'));

void main() {
  // -------------------------------------------------------------------------
  group('S-1: one record, one writer', () {
    test('a sign-in the phone cannot store did not happen', () async {
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final storage = MemoryStorage();
      final core = coreFor(backend, storage: storage);
      await core.load();

      storage.writeError = _refused;
      await expectLater(
        core.signedIn(core.reserve()!, signInFor(sid: 'sid-b')),
        throwsA(isA<SessionNotSaved>()),
      );
      expect(core.current, isNull);
      expect(core.busy, isFalse);

      storage.writeError = null;
      expect((await _restart(backend, storage)).current, isNull);
    });

    test('new tokens the phone cannot store leave the old ones', () async {
      final storage = _phone();
      final backend = FakeBackend();
      final core = coreFor(backend, storage: storage);
      await core.load();

      storage.writeError = _refused;
      await expectLater(
        core.replaceTokens(
          'sid-a',
          sentRefresh: fakeToken('sid-a'),
          access: fakeToken('sid-a', 'access-2'),
          refresh: fakeToken('sid-a', 'refresh-2'),
        ),
        throwsA(_refused),
      );
      expect(core.accessFor('sid-a'), fakeToken('sid-a', 'access'));
      expect(core.current?.refresh, fakeToken('sid-a'));

      storage.writeError = null;
      final again = await _restart(backend, storage);
      expect(again.current?.refresh, fakeToken('sid-a'));
    });

    test('an account the phone cannot store leaves the one shown', () async {
      final storage = _phone();
      final backend = FakeBackend();
      final core = coreFor(backend, storage: storage);
      await core.load();

      storage.writeError = _refused;
      await expectLater(
        core.updateAccount(
          'sid-a',
          signInFor(account: {...meFixture(), 'full_name': 'New'}).account,
        ),
        throwsA(_refused),
      );
      expect(core.current?.account.fullName, 'Amina Bouzid');

      storage.writeError = null;
      final again = await _restart(backend, storage);
      expect(again.current?.account.fullName, 'Amina Bouzid');
    });

    test('a sign-out the phone cannot store keeps the member signed in, and '
        'says so', () async {
      final storage = _phone();
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final core = coreFor(backend, storage: storage);
      await core.load();

      storage.writeError = _refused;
      await expectLater(
        core.end('sid-a', EndReason.signedOut),
        throwsA(isA<SessionNotSaved>()),
      );
      expect(core.current?.sid, 'sid-a');
      expect(backend.to('POST', '/api/auth/sign-out'), isEmpty);

      storage.writeError = null;
      expect((await _restart(backend, storage)).current?.sid, 'sid-a');
    });

    test('a refusal the phone cannot store ends the sign-in in memory; the '
        'next launch keeps the record as it was', () async {
      final storage = _phone();
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final core = coreFor(backend, storage: storage);
      await core.load();

      storage.writeError = _refused;
      await core.end('sid-a', EndReason.refused);
      expect(core.current, isNull);
      expect(core.notice, EndReason.refused);

      storage.writeError = null;
      expect(
        (await _restart(backend, storage)).current?.sid,
        'sid-a',
        reason: 'it meets the same refusal and ends again',
      );
    });

    test('a confirmation the phone cannot store keeps the entry', () async {
      final storage = _phone(ended: [EndedSignIn('sid-z', fakeToken('sid-z'))]);
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      storage.writeError = _refused;
      final core = coreFor(backend, storage: storage);
      await core.load();
      await _waitFor(() => backend.to('POST', '/api/auth/sign-out').isNotEmpty);
      await pumpEventQueue();

      storage.writeError = null;
      expect(storage.record!.ended.single.sid, 'sid-z');
      final again = await _restart(backend, storage);
      await _waitFor(() => storage.record!.ended.isEmpty);
      expect(again.current?.sid, 'sid-a');
    });

    test('a server confirmation and an account write queued together: '
        'neither is lost', () async {
      final confirmation = Completer<FakeResponse>();
      final storage = _phone(ended: [EndedSignIn('sid-z', fakeToken('sid-z'))]);
      final backend = FakeBackend()
        ..handle('POST', '/api/auth/sign-out', (_) => confirmation.future);
      final core = coreFor(backend, storage: storage);
      await core.load();
      await _waitFor(() => backend.to('POST', '/api/auth/sign-out').isNotEmpty);

      confirmation.complete(const FakeResponse(205));
      final renamed = core.updateAccount(
        'sid-a',
        signInFor(account: {...meFixture(), 'full_name': 'Renamed'}).account,
      );
      await renamed;
      await _waitFor(() => storage.record!.ended.isEmpty);

      expect(storage.record!.current?.account.fullName, 'Renamed');
      final again = await _restart(backend, storage);
      expect(again.current?.account.fullName, 'Renamed');
    });

    test('two task launches share one engine: the activity is singleTask', () {
      final manifest = File(
        'android/app/src/main/AndroidManifest.xml',
      ).readAsStringSync();
      final activity = RegExp(
        r'<activity\b[^>]*android:name="\.MainActivity"[^>]*>',
      ).firstMatch(manifest)![0]!;
      expect(activity, contains('android:launchMode="singleTask"'));
    });
  });

  // -------------------------------------------------------------------------
  group('S-2: one transition at a time', () {
    FakeBackend signedOutServer(Future<FakeResponse> Function() answer) {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..handle('POST', '/api/auth/sign-in', (_) => answer());
      return backend;
    }

    test('password and Google tapped in one frame start one attempt', () async {
      final answer = Completer<FakeResponse>();
      final backend = signedOutServer(() => answer.future);
      final container = _app(backend, MemoryStorage());
      await launch(container);
      final session = container.read(sessionProvider.notifier);

      var googleOpened = false;
      final password = session.signIn(email: 'a@x.com', password: 's');
      final google = session.signInWith(() async {
        googleOpened = true;
        return null;
      });
      expect(backend.session.busy, isTrue);
      expect(await google, isFalse);
      expect(googleOpened, isFalse, reason: 'no provider sheet opened');

      answer.complete(signInAnswer(sid: 'sid-b'));
      expect(await password, isTrue);
      expect(backend.session.busy, isFalse);
      expect(backend.to('POST', '/api/auth/sign-in'), hasLength(1));
    });

    test('a second attempt while the first waits starts nothing, and the '
        'first can be tried again after its refusal', () async {
      var answers = <Completer<FakeResponse>>[];
      final backend = signedOutServer(() {
        final reply = Completer<FakeResponse>();
        answers.add(reply);
        return reply.future;
      });
      final container = _app(backend, MemoryStorage());
      await launch(container);
      final session = container.read(sessionProvider.notifier);

      final first = session.signIn(email: 'a@x.com', password: 'wrong');
      expect(await session.signIn(email: 'a@x.com', password: 's'), isFalse);
      await _waitFor(() => answers.length == 1);
      answers.single.complete(
        const FakeResponse(400, {'code': 'invalid_credentials'}),
      );
      await expectLater(first, throwsA(isA<Object>()));
      expect(backend.session.busy, isFalse);

      answers = [];
      final retry = session.signIn(email: 'a@x.com', password: 's');
      await _waitFor(() => answers.length == 1);
      answers.single.complete(signInAnswer(sid: 'sid-b'));
      expect(await retry, isTrue);
    });

    testWidgets('tokens issued and not stored: that sign-in is ended on the '
        'server, once, and the screen gets a translated error', (tester) async {
      final storage = MemoryStorage();
      final backend = signedOutServer(() async => signInAnswer(sid: 'sid-b'));
      final container = _app(backend, storage);
      await tester.runAsync(() => launch(container));

      storage.writeError = _refused;
      Object? failure;
      await tester.runAsync(() async {
        try {
          await container
              .read(sessionProvider.notifier)
              .signIn(email: 'a@x.com', password: 's');
        } on Object catch (error) {
          failure = error;
        }
        await _waitFor(
          () => backend.to('POST', '/api/auth/sign-out').isNotEmpty,
        );
      });

      expect(failure, isA<SessionNotSaved>());
      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      expect(backend.to('POST', '/api/auth/sign-out').single.body, {
        'refresh': fakeToken('sid-b'),
      });

      for (final (locale, title) in [
        (const Locale('en'), "This phone couldn't save that"),
        (const Locale('fr'), 'Ce téléphone n’a pas pu l’enregistrer'),
        (const Locale('ar'), 'تعذّر على هذا الهاتف حفظ ذلك'),
      ]) {
        await pumpApp(
          tester,
          Builder(
            builder: (context) => Text(describeFailure(context, failure).title),
          ),
          locale: locale,
        );
        expect(find.text(title), findsOneWidget);
      }
    });

    test('two refresh triggers make one request', () async {
      var reads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/one', (_) {
          reads++;
          return reads <= 2
              ? const FakeResponse(401)
              : const FakeResponse(200, {'ok': true});
        })
        ..on(
          'POST',
          '/api/auth/refresh',
          FakeResponse(200, {
            'access': fakeToken('sid-a', 'access-2'),
            'refresh': fakeToken('sid-a', 'refresh-2'),
          }),
        );
      await backend.session.load();
      final api = apiClientFor(backend);

      await Future.wait([api.getObject('/api/one'), api.getObject('/api/one')]);

      expect(backend.to('POST', '/api/auth/refresh'), hasLength(1));
      expect(backend.session.current?.refresh, fakeToken('sid-a', 'refresh-2'));
    });

    test('a refresh refusal that arrives after another refresh rotated the '
        'token is ignored', () async {
      final refusal = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..on('GET', '/api/one', const FakeResponse(401))
        ..handle('POST', '/api/auth/refresh', (_) => refusal.future)
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final core = backend.session;
      await core.load();
      final api = apiClientFor(backend);

      final read = api.getObject('/api/one');
      await _waitFor(() => backend.to('POST', '/api/auth/refresh').isNotEmpty);
      // Meanwhile the token was rotated: its refusal says nothing now.
      await core.replaceTokens(
        'sid-a',
        sentRefresh: fakeToken('sid-a'),
        access: fakeToken('sid-a', 'access-2'),
        refresh: fakeToken('sid-a', 'refresh-2'),
      );
      refusal.complete(const FakeResponse(401));
      await expectLater(read, throwsA(isA<Object>()));

      expect(core.current?.sid, 'sid-a');
      expect(core.current?.refresh, fakeToken('sid-a', 'refresh-2'));
      expect(backend.to('POST', '/api/auth/sign-out'), isEmpty);
    });

    test('the same account signs out and in again: the first sign-in\'s late '
        'answers touch nothing', () async {
      final lateMe = Completer<FakeResponse>();
      final lateRefresh = Completer<FakeResponse>();
      var meReads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          meReads++;
          return meReads == 1 ? FakeResponse(200, meFixture()) : lateMe.future;
        })
        ..on('GET', '/api/one', const FakeResponse(401))
        ..handle('POST', '/api/auth/refresh', (_) => lateRefresh.future)
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..on('POST', '/api/auth/sign-in', signInAnswer(sid: 'sid-a2'));
      final container = _app(backend, _phone());
      await _started(container);
      await _waitFor(() => meReads == 1);
      final session = container.read(sessionProvider.notifier);

      final read = session.refreshAccount();
      final request = container.read(apiClientProvider).getObject('/api/one');
      await _waitFor(
        () =>
            meReads == 2 && backend.to('POST', '/api/auth/refresh').isNotEmpty,
      );
      await session.signOut();
      expect(
        await session.signIn(email: 'sender@example.com', password: 's'),
        isTrue,
      );

      lateMe.complete(
        FakeResponse(200, {...meFixture(), 'full_name': 'Late answer'}),
      );
      lateRefresh.complete(const FakeResponse(401));
      await read;
      await expectLater(request, throwsA(isA<Object>()));
      await pumpEventQueue();

      final state = container.read(sessionProvider) as SessionSignedIn;
      expect(state.sid, 'sid-a2');
      expect(state.account.fullName, 'Amina Bouzid');
      expect(backend.session.notice, isNull);
      expect(backend.session.current?.refresh, fakeToken('sid-a2'));
    });
  });

  // -------------------------------------------------------------------------
  group('S-3: one exit, for a named sign-in', () {
    final keeps = <String, (FakeHandler, FakeHandler)>{
      '401, then no network on the refresh': (
        (_) => const FakeResponse(401),
        (r) => throw _network(r),
      ),
      '403': ((_) => const FakeResponse(403, {'code': 'forbidden'}), _refuse),
      '404': ((_) => const FakeResponse(404), _refuse),
      '429 with Retry-After': (
        (_) => const FakeResponse.withHeaders(429, {}, {
          'retry-after': ['30'],
        }),
        _refuse,
      ),
      '500': ((_) => const FakeResponse(500), _refuse),
      'timeout': (
        (r) => throw _network(r, DioExceptionType.receiveTimeout),
        _refuse,
      ),
      'offline': ((r) => throw _network(r), _refuse),
    };

    for (final MapEntry(key: name, value: (answer, refresh)) in keeps.entries) {
      testWidgets('$name on /api/me at launch keeps the member signed in', (
        tester,
      ) async {
        final storage = _phone();
        final before = storage.values[SessionCore.recordKey];
        final backend = FakeBackend()
          ..handle('GET', '/api/me', answer)
          ..handle('POST', '/api/auth/refresh', refresh);
        final container = _app(backend, storage);

        container.read(sessionProvider);
        await _settle(tester, const Duration(seconds: 3));

        expect(container.read(sessionProvider), isA<SessionSignedIn>());
        expect(storage.values[SessionCore.recordKey], before);
        container.dispose();
      });

      testWidgets('$name on an ordinary request keeps the member signed in', (
        tester,
      ) async {
        final storage = _phone();
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..handle('GET', '/api/one', answer)
          ..handle('POST', '/api/auth/refresh', refresh);
        final container = _app(backend, storage);
        container.read(sessionProvider);
        await _settle(tester);
        final settled = storage.values[SessionCore.recordKey];

        Object? failure;
        unawaited(
          container
              .read(apiClientProvider)
              .getObject('/api/one')
              .then<void>((_) {}, onError: (Object error) => failure = error),
        );
        await _settle(tester, const Duration(seconds: 3));

        expect(failure, isNotNull);
        expect(container.read(sessionProvider), isA<SessionSignedIn>());
        expect(storage.values[SessionCore.recordKey], settled);
        expect(storage.record!.current?.refresh, fakeToken('sid-a'));
        container.dispose();
      });
    }

    for (final where in ['/api/me at launch', 'an ordinary request']) {
      testWidgets('401, then a refused refresh, on $where ends the sign-in', (
        tester,
      ) async {
        final storage = _phone();
        final backend = FakeBackend()
          ..on(
            'GET',
            '/api/me',
            where == 'an ordinary request'
                ? FakeResponse(200, meFixture())
                : const FakeResponse(401),
          )
          ..on('GET', '/api/one', const FakeResponse(401))
          ..handle('POST', '/api/auth/refresh', _refuse)
          ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
        final container = _app(backend, storage);
        container.read(sessionProvider);
        await _settle(tester);
        if (where == 'an ordinary request') {
          unawaited(
            container
                .read(apiClientProvider)
                .getObject('/api/one')
                .then<void>((_) {}, onError: (Object _) {}),
          );
          await _settle(tester);
        }

        final state = container.read(sessionProvider);
        expect(state, isA<SessionSignedOut>());
        expect((state as SessionSignedOut).becauseExpired, isTrue);
        expect(storage.record!.current, isNull);
        expect(backend.to('POST', '/api/auth/sign-out').single.body, {
          'refresh': fakeToken('sid-a'),
        });
        container.dispose();
      });
    }

    testWidgets('a 429 at launch waits for its Retry-After', (tester) async {
      var reads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          reads++;
          return reads == 1
              ? const FakeResponse.withHeaders(429, {}, {
                  'retry-after': ['20'],
                })
              : FakeResponse(200, {...meFixture(), 'full_name': 'Confirmed'});
        });
      final container = _app(backend, _phone());
      container.read(sessionProvider);
      await _settle(tester);
      expect(reads, 1);

      await tester.pump(const Duration(seconds: 15));
      expect(reads, 1, reason: 'not before the server said');
      await _settle(tester, const Duration(seconds: 6));
      expect(reads, 2);
      final state = container.read(sessionProvider) as SessionSignedIn;
      expect(state.account.fullName, 'Confirmed');
      container.dispose();
    });

    testWidgets('a record that cannot be read in the background waits, and '
        'is read in the foreground: still signed in, nothing written', (
      tester,
    ) async {
      final storage = _phone()..readError = _refused;
      var pushTokenDeleted = 0;
      final core = coreFor(
        FakeBackend(),
        storage: storage,
        deletePushToken: () async => pushTokenDeleted++,
      );
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      addTearDown(
        () => tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        ),
      );

      await core.load();
      expect(core.loaded, isFalse, reason: 'the start screen, nothing else');
      expect(core.reserve(), isNull, reason: 'no sign-in either');

      storage.readError = null;
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      core.resumed();
      await tester.pump();

      expect(core.current?.sid, 'sid-a');
      expect(storage.writes, 0);
      expect(pushTokenDeleted, 0);
    });

    for (final (name, broken) in [
      (
        'cannot be read in the foreground',
        (MemoryStorage s) {
          s.readError = _refused;
        },
      ),
      (
        'cannot be parsed',
        (MemoryStorage s) {
          s.values[SessionCore.recordKey] = '{not json';
        },
      ),
    ]) {
      testWidgets('a record that $name is lost: signed out, an empty record, '
          'and the push token deleted until that succeeds', (tester) async {
        final storage = _phone();
        broken(storage);
        var attempts = 0;
        final core = coreFor(
          FakeBackend(),
          storage: storage,
          deletePushToken: () async {
            if (++attempts < 3) throw _refused;
          },
        );
        tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        );

        await core.load();
        storage.readError = null;
        expect(core.loaded, isTrue);
        expect(core.current, isNull);
        expect(storage.record!.current, isNull);
        expect(storage.record!.ended, isEmpty);

        await tester.pump(const Duration(seconds: 2));
        await tester.pump(const Duration(seconds: 4));
        await tester.pump(const Duration(seconds: 8));
        expect(attempts, 3);
      });
    }
  });

  // -------------------------------------------------------------------------
  group('S-5: the server hears about every ended sign-in', () {
    MemoryStorage ended(List<String> sids, {String? current}) => MemoryStorage({
      SessionCore.recordKey: SessionRecord(
        current: current == null ? null : signInFor(sid: current),
        ended: [for (final sid in sids) EndedSignIn(sid, fakeToken(sid))],
      ).encode(),
    });

    test('205 removes the entry: an expired proof, a rotated proof, a deleted '
        'account all answer it; so does 400 sign_out_proof_invalid', () async {
      final storage = ended(['expired', 'rotated', 'deleted', 'unverifiable']);
      final backend = FakeBackend()
        ..handle(
          'POST',
          '/api/auth/sign-out',
          (r) => r.body['refresh'] == fakeToken('unverifiable')
              ? const FakeResponse(400, {'code': 'sign_out_proof_invalid'})
              : const FakeResponse(205),
        );
      await coreFor(backend, storage: storage).load();
      await _waitFor(() => storage.record!.ended.isEmpty);
      expect(backend.to('POST', '/api/auth/sign-out'), hasLength(4));
    });

    for (final (status, body) in [
      (401, const <String, dynamic>{}),
      (403, const <String, dynamic>{}),
      (404, const <String, dynamic>{}),
      (429, const <String, dynamic>{}),
      (500, const <String, dynamic>{}),
      (400, const <String, dynamic>{'code': 'validation_error'}),
    ]) {
      test('$status ${body['code'] ?? ''} keeps the entry', () async {
        final storage = ended(['sid-z']);
        final backend = FakeBackend()
          ..on('POST', '/api/auth/sign-out', FakeResponse(status, body));
        final core = coreFor(backend, storage: storage);
        await core.load();
        await _waitFor(
          () => backend.to('POST', '/api/auth/sign-out').isNotEmpty,
        );
        await pumpEventQueue();
        expect(storage.record!.ended.single.sid, 'sid-z');
      });
    }

    test('a lost 205, then the repeat', () async {
      var lost = true;
      final storage = ended(['sid-z']);
      final backend = FakeBackend()
        ..handle('POST', '/api/auth/sign-out', (r) {
          if (lost) throw _network(r); // the server ended it; the answer died
          return const FakeResponse(205);
        });
      final core = coreFor(backend, storage: storage);
      await core.load();
      await _waitFor(() => backend.to('POST', '/api/auth/sign-out').isNotEmpty);
      await pumpEventQueue();
      expect(storage.record!.ended, hasLength(1));

      lost = false;
      core.resumed();
      await _waitFor(() => storage.record!.ended.isEmpty);
      expect(
        backend.to('POST', '/api/auth/sign-out').map((r) => r.body['refresh']),
        [fakeToken('sid-z'), fakeToken('sid-z')],
      );
    });

    test('nine sign-outs while the endpoint fails: nine entries, all sent '
        'later', () async {
      var failing = true;
      final storage = MemoryStorage();
      final backend = FakeBackend()
        ..handle(
          'POST',
          '/api/auth/sign-out',
          (_) => FakeResponse(failing ? 503 : 205),
        );
      final core = coreFor(backend, storage: storage);
      await core.load();
      for (var i = 1; i <= 9; i++) {
        await core.signedIn(core.reserve()!, signInFor(sid: 'sid-$i'));
        await core.end('sid-$i', EndReason.signedOut);
      }
      await pumpEventQueue();
      expect(storage.record!.ended, hasLength(9));

      failing = false;
      final before = backend.to('POST', '/api/auth/sign-out').length;
      core.resumed();
      await _waitFor(() => storage.record!.ended.isEmpty);
      expect(
        backend
            .to('POST', '/api/auth/sign-out')
            .skip(before)
            .map((r) => r.body['refresh'])
            .toSet(),
        {for (var i = 1; i <= 9; i++) fakeToken('sid-$i')},
      );
    });

    test('the app closed before the send: the next launch sends it', () async {
      final storage = _phone();
      final first = FakeBackend()
        ..handle(
          'POST',
          '/api/auth/sign-out',
          (_) => Completer<FakeResponse>().future, // the app is gone
        );
      final core = coreFor(first, storage: storage);
      await core.load();
      await core.end('sid-a', EndReason.signedOut);

      final next = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      await _restart(next, storage);
      await _waitFor(() => storage.record!.ended.isEmpty);
      expect(next.to('POST', '/api/auth/sign-out').single.body, {
        'refresh': fakeToken('sid-a'),
      });
    });

    test('no request carries another sign-in\'s credentials', () async {
      final storage = ended(['sid-x', 'sid-y'], current: 'sid-c');
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      await coreFor(backend, storage: storage).load();
      await _waitFor(() => storage.record!.ended.isEmpty);

      final sent = backend.to('POST', '/api/auth/sign-out');
      expect(sent.map((r) => r.body), [
        {'refresh': fakeToken('sid-x')},
        {'refresh': fakeToken('sid-y')},
      ]);
      for (final request in sent) {
        expect(request.headers, isNot(contains('Authorization')));
        expect(jsonEncode(request.body), isNot(contains(fakeToken('sid-c'))));
      }
      expect(storage.record!.current?.sid, 'sid-c');
    });
  });

  // -------------------------------------------------------------------------
  group('S-6: newer truth wins', () {
    /// `/api/me` answered by the test, one read at a time.
    (FakeBackend, List<Completer<FakeResponse>>) heldReads() {
      final reads = <Completer<FakeResponse>>[];
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          final reply = Completer<FakeResponse>();
          reads.add(reply);
          return reply.future;
        });
      return (backend, reads);
    }

    FakeResponse named(String name, [String language = 'en']) => FakeResponse(
      200,
      {...meFixture(), 'full_name': name, 'preferred_language': language},
    );

    // The brief's guess was that a rebuilt provider drops its earlier
    // answer. The owner is a Notifier that is not rebuilt between reads, so
    // nothing drops it: without the owner's request counter this test fails.
    test('two reads answered in reverse order show the newer one, and so '
        'does a restart', () async {
      final (backend, reads) = heldReads();
      final storage = _phone();
      final container = _app(backend, storage);
      await _started(container);
      await _waitFor(() => reads.length == 1);
      reads.single.complete(named('Launch'));

      final session = container.read(sessionProvider.notifier);
      final older = session.refreshAccount();
      final newer = session.refreshAccount();
      await _waitFor(() => reads.length == 3);
      reads[2].complete(named('Newer'));
      await newer;
      reads[1].complete(named('Older'));
      await older;

      expect(container.read(accountProvider)?.fullName, 'Newer');
      final again = await _restart(backend, storage);
      expect(again.current?.account.fullName, 'Newer');
    });

    test('a write answered after a newer read: only the read after the write '
        'is shown, and so after a restart', () async {
      final (backend, reads) = heldReads();
      final write = Completer<FakeResponse>();
      backend.handle('PATCH', '/api/me', (_) => write.future);
      final storage = _phone();
      final container = _app(backend, storage);
      final shown = <String?>[];
      container.listen(accountProvider, (_, next) => shown.add(next?.fullName));
      await _started(container);
      await _waitFor(() => reads.length == 1);
      reads.single.complete(named('Launch'));
      await pumpEventQueue();

      final session = container.read(sessionProvider.notifier);
      final saving = session.updatePreferredLanguage(
        CommunicationLanguage.french,
      );
      final read = session.refreshAccount();
      await _waitFor(() => reads.length == 2);
      reads[1].complete(named('Read meanwhile'));
      await read;
      write.complete(named('The write\'s own answer', 'fr'));
      await _waitFor(() => reads.length == 3);
      reads[2].complete(named('After the write', 'fr'));
      await saving;

      expect(shown, isNot(contains('The write\'s own answer')));
      expect(container.read(accountProvider)?.fullName, 'After the write');
      final again = await _restart(backend, storage);
      expect(again.current?.account.fullName, 'After the write');
    });
  });

  // -------------------------------------------------------------------------
  group('mechanical checks', () {
    test('one place writes the record key', () {
      final writes = [
        for (final file in _libFiles())
          ...RegExp(
            r'\.write\(\s*key:\s*(?:SessionCore\.)?recordKey',
          ).allMatches(file.readAsStringSync()).map((_) => file.path),
      ];
      expect(writes, ['lib/core/session/session_core.dart']);
      final core = _lib('core/session/session_core.dart');
      final commit = core.substring(core.indexOf('Future<void> _commit('));
      expect(
        commit.substring(0, commit.indexOf('\n  }\n')),
        contains('.write(key: recordKey'),
      );
    });

    test('one function empties the current slot', () {
      final core = _lib('core/session/session_core.dart');
      // Every record built in the core names its current sign-in, except one.
      final firstArguments = RegExp(
        r'SessionRecord\(\s*(\w+):',
      ).allMatches(core).map((m) => m[1]).toList();
      expect(firstArguments.where((a) => a != 'current'), ['ended']);
      final end = core.substring(
        core.indexOf('Future<void> end('),
        core.indexOf('void dismissNotice()'),
      );
      expect(end, contains('SessionRecord(\n          ended:'));
      // The empty record is stored only for a record that was never read.
      final load = core.substring(
        core.indexOf('Future<void> load()'),
        core.indexOf('Future<void> _erasePushToken()'),
      );
      expect(
        RegExp(r'SessionRecord\.empty').allMatches(core).length,
        RegExp(r'SessionRecord\.empty').allMatches(load).length,
        reason: 'only where the record is read, or lost',
      );
      for (final file in _libFiles()) {
        if (file.path.endsWith('session_core.dart')) continue;
        expect(
          file.readAsStringSync(),
          isNot(contains('SessionRecord(')),
          reason: '${file.path} builds a record',
        );
      }
    });

    test('no read of an access token outside the core', () {
      final readers = <String>{};
      for (final file in _libFiles()) {
        if (file.path.endsWith('session_core.dart')) continue;
        final source = file.readAsStringSync();
        expect(
          source,
          isNot(matches(RegExp(r'\.access\b(?!\s*:)|readAccess'))),
          reason: '${file.path} reads an access token itself',
        );
        if (source.contains('accessFor(')) readers.add(file.path);
      }
      // The bearer of a request, and the socket's sign-in.
      expect(readers, {
        'lib/core/api/api_client.dart',
        'lib/core/push/push_coordinator.dart',
      });
    });
  });
}

FakeResponse _refuse(RecordedRequest _) => const FakeResponse(401);
