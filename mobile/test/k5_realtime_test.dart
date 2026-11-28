/// K5 (13.16, 13.17): the realtime sockets and the bell badge.
///
/// The app keeps two sockets — `/ws/notifications` and `/ws/chat` — owned by
/// one [NotificationSocket] that the push coordinator starts and stops. These
/// tests drive the real coordinator and the real socket class over a fake
/// connector and count every connection it opens and closes across the
/// lifecycle a phone delivers: sign-in, an `inactive` flicker, a real trip to
/// the background, rapid switching, an account switch and sign-out. Then the
/// reconnect backoff under a server that accepts and drops at once, and the
/// badge reads.
library;

import 'dart:async';
import 'dart:math';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/domain/account.dart';

import 'support/fake_api.dart';

class _Connection implements NotificationSocketConnection {
  _Connection(this.path);

  final String path;
  final _events = StreamController<dynamic>();
  bool closed = false;

  @override
  Stream<dynamic> get stream => _events.stream;

  /// The server ending the connection.
  void drop() => unawaited(_events.close());

  @override
  Future<void> close() async {
    if (closed) return;
    closed = true;
    if (!_events.isClosed) unawaited(_events.close());
  }
}

/// Every connection the socket class ever asked for.
class _Dialer {
  final all = <_Connection>[];

  /// Endpoints whose handshake currently fails: no network.
  final refused = <String>{};
  int refusals = 0;

  Iterable<_Connection> get open => all.where((c) => !c.closed);

  Future<NotificationSocketConnection> connect(
    Uri uri,
    Map<String, String> headers,
  ) async {
    if (refused.contains(uri.path)) {
      refusals++;
      throw StateError('unreachable');
    }
    final connection = _Connection(uri.path);
    all.add(connection);
    return connection;
  }
}

/// The session shown, moved by the test; the core beside it holds the same
/// sign-in, so the sockets find its token.
class _Session extends SessionController {
  _Session(this.account);

  Account account;
  String sid = 'sid-a';

  SessionCore get _core => ref.read(sessionCoreProvider);

  @override
  SessionState build() => SessionSignedIn(account, sid: sid);

  /// Another account takes the phone: this sign-in ends, then the next one
  /// starts from signed out.
  Future<void> switchTo(Account next) async {
    await signOutLocally();
    account = next;
    sid = 'sid-${next.id}';
    await _core.signedIn(
      _core.reserve()!,
      SignIn(
        sid: sid,
        account: next,
        access: fakeToken(sid, 'access'),
        refresh: fakeToken(sid),
      ),
    );
    state = SessionSignedIn(next, sid: sid);
  }

  Future<void> signOutLocally() async {
    await _core.end(sid, EndReason.signedOut);
    state = const SessionSignedOut();
  }
}

/// Records profile refreshes, with a chosen age for the last account read.
class _ResumeSession extends SessionController {
  _ResumeSession({required this.readRecently});

  final bool readRecently;
  int refreshes = 0;

  @override
  SessionState build() =>
      SessionSignedIn(Account.fromJson(meFixture()), sid: 'sid-a');

  @override
  bool accountReadWithin(Duration window) => readRecently;

  @override
  Future<bool> refreshAccount() async {
    refreshes++;
    return true;
  }
}

void _leave(WidgetTester tester) {
  for (final state in [
    AppLifecycleState.inactive,
    AppLifecycleState.hidden,
    AppLifecycleState.paused,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

void _return(WidgetTester tester) {
  for (final state in [
    AppLifecycleState.hidden,
    AppLifecycleState.inactive,
    AppLifecycleState.resumed,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

Future<void> _flush(WidgetTester tester) async {
  for (var i = 0; i < 5; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Stops [socket] under the test clock: closing a live connection completes
/// through the stream machinery, which only a pump drives here.
Future<void> _stop(WidgetTester tester, NotificationSocket socket) async {
  unawaited(socket.stop());
  await tester.pump();
}

Map<String, int> _openPerPath(_Dialer dialer) {
  final counts = <String, int>{};
  for (final connection in dialer.open) {
    counts[connection.path] = (counts[connection.path] ?? 0) + 1;
  }
  return counts;
}

/// Mounts the real coordinator over [dialer]. Returns the container and a
/// counter of catch-up passes (a mounted collection being reconciled).
Future<(ProviderContainer, _Session, int Function())> _mount(
  WidgetTester tester,
  _Dialer dialer,
) async {
  final router = GoRouter(
    initialLocation: '/home',
    routes: [
      GoRoute(path: '/home', builder: (_, _) => const SizedBox.shrink()),
    ],
  );
  final session = _Session(Account.fromJson(meFixture()));
  final tokens = FakeTokenStore();
  // A refused handshake re-reads `/api/me` to refresh the token.
  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
  await backend.session.load();
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      sessionCoreProvider.overrideWithValue(backend.session),
      apiClientProvider.overrideWithValue(apiClientFor(backend)),
      sessionProvider.overrideWith(() => session),
      routerProvider.overrideWithValue(router),
      notificationSocketProvider.overrideWithValue(
        NotificationSocket(connector: dialer.connect, random: Random(7)),
      ),
      pushMessagingProvider.overrideWithValue(const DisabledPushMessaging()),
      // No settle window: every catch-up that is asked for is counted, so a
      // redundant one cannot hide behind the dedup.
      liveUpdatesProvider.overrideWith((ref) {
        final live = LiveUpdates(
          coalesceFor: const Duration(milliseconds: 5),
          reconcileSettlesFor: Duration.zero,
        );
        ref.onDispose(live.dispose);
        return live;
      }),
    ],
  );
  addTearDown(() {
    container.dispose();
    router.dispose();
  });
  var catchUps = 0;
  container
      .read(liveUpdatesProvider)
      .register(const LiveResource.deals(), () => catchUps++);

  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(
        routerConfig: router,
        builder: (context, child) => Consumer(
          builder: (context, ref, _) {
            ref.watch(pushCoordinatorProvider);
            return child ?? const SizedBox.shrink();
          },
        ),
      ),
    ),
  );
  await _flush(tester);
  return (container, session, () => catchUps);
}

void main() {
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized()
        .handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  });

  group('socket lifecycle', () {
    testWidgets('sign-in opens one socket per endpoint; an inactive flicker '
        'keeps them and asks for nothing', (tester) async {
      final dialer = _Dialer();
      final (_, _, catchUps) = await _mount(tester, dialer);
      expect(_openPerPath(dialer), {'/ws/notifications': 1, '/ws/chat': 1});
      final opened = List.of(dialer.all);
      final before = catchUps();

      // The notification shade, the app switcher, a system dialog.
      for (var i = 0; i < 3; i++) {
        tester.binding
          ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
          ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
        await _flush(tester);
      }

      expect(dialer.all, opened, reason: 'no redial for a flicker');
      expect(opened.every((c) => !c.closed), isTrue);
      expect(catchUps(), before, reason: 'nothing was missed, nothing re-read');
    });

    testWidgets('an inactive return redials an endpoint stuck in backoff at '
        'once, and leaves a live one alone', (tester) async {
      final dialer = _Dialer();
      await _mount(tester, dialer);
      final notifications = dialer.open.singleWhere(
        (c) => c.path == '/ws/notifications',
      );
      final chat = dialer.open.singleWhere((c) => c.path == '/ws/chat');

      // Wi-Fi drops under the chat socket and stays down long enough for its
      // backoff to reach tens of seconds.
      dialer.refused.add('/ws/chat');
      chat.drop();
      for (var i = 0; i < 60; i++) {
        await tester.pump(const Duration(seconds: 1));
      }
      expect(dialer.refusals, greaterThanOrEqualTo(4));
      expect(dialer.open.where((c) => c.path == '/ws/chat'), isEmpty);

      // The user fixes it from the shade and comes back.
      dialer.refused.clear();
      final dialled = dialer.all.length;
      tester.binding
        ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
        ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump(const Duration(milliseconds: 100));

      expect(_openPerPath(dialer), {'/ws/notifications': 1, '/ws/chat': 1});
      expect(dialer.all, hasLength(dialled + 1), reason: 'only chat redials');
      expect(dialer.open, contains(notifications));
      expect(notifications.closed, isFalse);

      // And its streak starts over: the next drop retries within a second.
      final revived = dialer.open.singleWhere((c) => c.path == '/ws/chat');
      revived.drop();
      await tester.pump(const Duration(milliseconds: 1100));
      expect(dialer.open.where((c) => c.path == '/ws/chat'), hasLength(1));
    });

    testWidgets('the background closes both; the return reconnects each once '
        'and catches up', (tester) async {
      final dialer = _Dialer();
      final (_, _, catchUps) = await _mount(tester, dialer);
      final first = List.of(dialer.all);
      final before = catchUps();

      _leave(tester);
      await _flush(tester);
      expect(first.every((c) => c.closed), isTrue);
      expect(dialer.open, isEmpty);

      // Minutes away: no reconnect attempts while off screen.
      await tester.pump(const Duration(minutes: 5));
      expect(dialer.all, hasLength(2));

      _return(tester);
      await _flush(tester);
      expect(_openPerPath(dialer), {'/ws/notifications': 1, '/ws/chat': 1});
      expect(dialer.all, hasLength(4));
      expect(catchUps(), greaterThan(before));
    });

    testWidgets('rapid switching ends with exactly one socket per endpoint', (
      tester,
    ) async {
      final dialer = _Dialer();
      await _mount(tester, dialer);

      for (var i = 0; i < 6; i++) {
        _leave(tester);
        _return(tester);
        await tester.pump();
      }
      await _flush(tester);

      expect(_openPerPath(dialer), {'/ws/notifications': 1, '/ws/chat': 1});
      final settled = dialer.all.length;
      await tester.pump(const Duration(minutes: 2));
      expect(dialer.all, hasLength(settled), reason: 'no stray retry timers');
    });

    testWidgets('an account switch closes the previous account\'s sockets', (
      tester,
    ) async {
      final dialer = _Dialer();
      final (_, session, _) = await _mount(tester, dialer);
      final first = List.of(dialer.all);

      unawaited(
        session.switchTo(
          Account.fromJson({
            ...meFixture(),
            'id': 99,
            'email': 'b@example.com',
          }),
        ),
      );
      await _flush(tester);

      expect(first.every((c) => c.closed), isTrue);
      expect(_openPerPath(dialer), {'/ws/notifications': 1, '/ws/chat': 1});
      expect(dialer.all, hasLength(4));
    });

    testWidgets('sign-out closes everything and never redials', (tester) async {
      final dialer = _Dialer();
      final (_, session, _) = await _mount(tester, dialer);

      unawaited(session.signOutLocally());
      await _flush(tester);
      expect(dialer.open, isEmpty);

      // Nor does coming back to the app signed out.
      _leave(tester);
      _return(tester);
      await tester.pump(const Duration(minutes: 5));
      expect(dialer.all, hasLength(2));
      expect(dialer.open, isEmpty);
    });
  });

  group('resume profile read', () {
    Future<_ResumeSession> mountLaunchedUnknown(
      WidgetTester tester, {
      required bool readRecently,
    }) async {
      // What an iOS background launch reports: no lifecycle state at all.
      tester.binding.resetInternalState();
      expect(tester.binding.lifecycleState, isNull);
      final session = _ResumeSession(readRecently: readRecently);
      final container = ProviderContainer(
        overrides: [sessionProvider.overrideWith(() => session)],
      );
      addTearDown(container.dispose);
      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: const ResumeRefresher(child: SizedBox.shrink()),
        ),
      );
      return session;
    }

    testWidgets('the first open after a background launch reads the profile '
        'when the launch read is old; later flickers never do', (tester) async {
      final session = await mountLaunchedUnknown(tester, readRecently: false);
      tester.binding
        ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
        ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(session.refreshes, 1);

      tester.binding
        ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
        ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(session.refreshes, 1);
    });

    testWidgets('a foreground launch whose restore just read the profile does '
        'not read it again', (tester) async {
      final session = await mountLaunchedUnknown(tester, readRecently: true);
      tester.binding
        ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
        ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await tester.pump();
      expect(session.refreshes, 0);
    });
  });

  group('reconnect backoff', () {
    testWidgets('an endpoint that accepts and drops at once backs off', (
      tester,
    ) async {
      var now = Duration.zero;
      final connects = <String, int>{};
      final socket = NotificationSocket(
        random: Random(3),
        elapsed: () => now,
        connector: (uri, _) async {
          connects[uri.path] = (connects[uri.path] ?? 0) + 1;
          return _Connection(uri.path)..drop();
        },
      );
      var catchUps = 0;
      await socket.start(
        accessToken: ({required refresh}) async => 'access',
        onEvent: (_, _) {},
        onConnected: (_) => catchUps++,
      );

      for (var i = 0; i < 120; i++) {
        await tester.pump(const Duration(milliseconds: 500));
        now += const Duration(milliseconds: 500);
      }

      // A minute. Resetting the backoff on every accepted handshake redialled
      // every 0.5-1 s: 60-120 connects per endpoint, each asking for a
      // catch-up. Growing towards the 32 s ceiling it is a handful.
      expect(connects.keys.toSet(), NotificationSocket.paths.toSet());
      for (final count in connects.values) {
        expect(count, lessThanOrEqualTo(9));
      }
      expect(catchUps, lessThanOrEqualTo(18));
      await _stop(tester, socket);
    });

    testWidgets(
      'a connection that stayed up reconnects promptly after a drop',
      (tester) async {
        var now = Duration.zero;
        final attempts = <String, int>{};
        final live = <String, _Connection>{};
        final socket = NotificationSocket(
          random: Random(3),
          elapsed: () => now,
          connector: (uri, _) async {
            final attempt = (attempts[uri.path] ?? 0) + 1;
            attempts[uri.path] = attempt;
            // A short streak of refused handshakes first.
            if (attempt <= 3) throw StateError('refused');
            return live[uri.path] = _Connection(uri.path);
          },
        );
        await socket.start(
          accessToken: ({required refresh}) async => 'access',
          onEvent: (_, _) {},
          onConnected: (_) {},
        );
        for (var i = 0; i < 40 && live.length < 2; i++) {
          await tester.pump(const Duration(milliseconds: 500));
          now += const Duration(milliseconds: 500);
        }
        expect(live, hasLength(2));

        // Up for a minute, then the network changes under it.
        await tester.pump(const Duration(minutes: 1));
        now += const Duration(minutes: 1);
        final before = Map.of(attempts);
        for (final connection in live.values) {
          connection.drop();
        }
        await tester.pump(const Duration(milliseconds: 1100));

        for (final path in NotificationSocket.paths) {
          expect(attempts[path], before[path]! + 1, reason: path);
        }
        await _stop(tester, socket);
      },
    );
  });

  group('bell badge', () {
    testWidgets('the bell and "Mark all read" share one read, and a read '
        'marker resets both', (tester) async {
      var active = 3;
      var unreadActive = 1;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle(
          'GET',
          '/api/notifications/unread-count',
          (_) => FakeResponse(200, {
            'active': active,
            'unread': active,
            'unread_active': unreadActive,
          }),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);

      Future<void> settle() async {
        for (var i = 0; i < 20; i++) {
          await tester.pump(const Duration(milliseconds: 20));
        }
      }

      final session = container.listen(sessionProvider, (_, _) {});
      addTearDown(session.close);
      await settle();
      expect(container.read(accountProvider)?.id, 42);

      final bell = container.listen(unreadNotificationsProvider, (_, _) {});
      final inbox = container.listen(
        unreadActiveNotificationsProvider,
        (_, _) {},
      );
      addTearDown(bell.close);
      addTearDown(inbox.close);

      int reads() =>
          backend.to('GET', '/api/notifications/unread-count').length;

      await settle();
      expect(container.read(unreadNotificationsProvider).value, 3);
      expect(container.read(unreadActiveNotificationsProvider).value, 1);
      expect(reads(), 1);

      // A realtime event naming the badge: one read, not one per consumer.
      container.read(liveUpdatesProvider)
        ..bindAccount(42)
        ..ingest({
          'event_id': 'k5-badge',
          'type': 'deal.updated',
          'deal_id': 7,
        }, source: LiveEventSource.websocket);
      await settle();
      expect(reads(), 2);

      // Marking read invalidates both, as the inbox does.
      active = 0;
      unreadActive = 0;
      container
        ..invalidate(unreadNotificationsProvider)
        ..invalidate(unreadActiveNotificationsProvider);
      await settle();
      expect(reads(), 3);
      expect(container.read(unreadNotificationsProvider).value, 0);
      expect(container.read(unreadActiveNotificationsProvider).value, 0);
    });
  });
}
