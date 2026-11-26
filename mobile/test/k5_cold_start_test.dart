/// K5: what a cold start waits on before the first frame, and what it does not.
///
/// `main` used to await Firebase initialisation before `runApp`, so every
/// launch held its first frame on platform-channel work that paints nothing.
/// Firebase now starts after the first frame behind [DeferredPushMessaging].
/// These tests hold that contract: the app paints and works before push is
/// ready, the push coordinator picks push up once it is, a failed start leaves
/// the app usable, and an offline launch without a snapshot is never a silent
/// dead end.
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/push.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';
import 'package:shiptrip/features/splash/splash_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

class _PushTokenStore extends FakeTokenStore {
  _PushTokenStore({super.refresh});

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
}

class _FakePushMessaging implements PushMessaging {
  _FakePushMessaging({
    this.currentPermission = PushPermission.notDetermined,
    this.requestResult = PushPermission.authorized,
  });

  PushPermission currentPermission;

  /// What the person answers when the system asks.
  PushPermission requestResult;
  int requests = 0;

  /// While set, the system dialog stays open until it completes.
  Completer<void>? dialog;

  @override
  bool get available => true;
  @override
  PushAvailability get availability => PushAvailability.available;
  @override
  Stream<PushMessage> get foregroundMessages => const Stream.empty();
  @override
  Stream<PushMessage> get openedMessages => const Stream.empty();
  @override
  Stream<String> get tokenRefresh => const Stream.empty();
  @override
  Future<PushMessage?> initialMessage() async => null;
  @override
  Future<PushPermission> permission() async => currentPermission;
  @override
  Future<PushPermission> requestPermission() async {
    requests++;
    await dialog?.future;
    currentPermission = requestResult;
    return requestResult;
  }

  @override
  Future<String?> token() async => 'fcm-token';
}

class _StaticPushCoordinator extends PushCoordinator {
  _StaticPushCoordinator(this.initial);

  final PushRuntimeState initial;

  @override
  PushRuntimeState build() => initial;
}

class _FixedSession extends SessionController {
  @override
  SessionState build() => SessionSignedIn(Account.fromJson(meFixture()));
}

/// A session a test moves by hand: a guest until [enter], a guest again after
/// [leave].
class _HandSession extends SessionController {
  @override
  SessionState build() => const SessionSignedOut();

  void enter() => state = SessionSignedIn(Account.fromJson(meFixture()));
  void leave() => state = const SessionSignedOut();
}

class _NoopSocket extends NotificationSocket {
  @override
  Future<void> start({
    required NotificationSocketToken accessToken,
    required NotificationSocketEvent onEvent,
    required NotificationSocketConnected onConnected,
  }) async {}

  @override
  Future<void> stop() async {}
}

Never _offline(RecordedRequest r) => throw DioException(
  requestOptions: RequestOptions(path: r.path),
  type: DioExceptionType.connectionError,
);

Future<void> _settle(WidgetTester tester, [int frames = 20]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Boots the real app, the way `main` does: push is handed over unresolved.
Future<ProviderContainer> _boot(
  WidgetTester tester, {
  required FakeBackend backend,
  required FakeTokenStore tokens,
  required PushMessaging push,
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(412, 915);
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
        notificationSocketProvider.overrideWithValue(_NoopSocket()),
        pushMessagingProvider.overrideWithValue(push),
      ],
      child: const ShipTripApp(),
    ),
  );
  return ProviderScope.containerOf(tester.element(find.byType(ShipTripApp)));
}

Future<void> _shutdown(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await _settle(tester, 5);
}

/// A signed-in coordinator over [push], without a widget tree. [session]
/// replaces the signed-in member, for a test that starts as a guest.
ProviderContainer _coordinatorContainer(
  FakeBackend backend,
  FakeTokenStore tokens,
  PushMessaging push, {
  SessionController Function()? session,
}) {
  final router = GoRouter(
    routes: [GoRoute(path: '/', builder: (_, _) => const SizedBox.shrink())],
  );
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
      sessionProvider.overrideWith(session ?? _FixedSession.new),
      routerProvider.overrideWithValue(router),
      notificationSocketProvider.overrideWithValue(_NoopSocket()),
      pushMessagingProvider.overrideWithValue(push),
    ],
  );
  addTearDown(() {
    container.dispose();
    router.dispose();
  });
  return container;
}

void main() {
  group('push starts after the first frame', () {
    testWidgets('the app paints and works while Firebase is still starting', (
      tester,
    ) async {
      final push = DeferredPushMessaging();
      final firebase = Completer<PushMessaging>();
      var starts = 0;
      var paintedBeforeStart = false;
      // Same order as `main`: registered before the first frame is drawn.
      push.startAfterFirstFrame(() {
        starts++;
        paintedBeforeStart = find.byType(MaterialApp).evaluate().isNotEmpty;
        return firebase.future;
      });
      expect(starts, 0);

      final container = await _boot(
        tester,
        // Signed out opens guest Home, which reads the public listings.
        backend: FakeBackend()..emptyDiscovery(),
        tokens: _PushTokenStore(refresh: null),
        push: push,
      );
      expect(starts, 1, reason: 'started right after the first frame');
      expect(paintedBeforeStart, isTrue);

      await _settle(tester);
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(
        container.read(pushCoordinatorProvider).availability,
        PushAvailability.initializing,
      );
      final app = tester.widget(find.byType(MaterialApp));

      final messaging = _FakePushMessaging();
      expect(messaging.requests, 0, reason: 'nothing asks before Firebase');
      firebase.complete(messaging);
      await _settle(tester, 5);

      final runtime = container.read(pushCoordinatorProvider);
      expect(runtime.availability, PushAvailability.available);
      expect(messaging.requests, 1, reason: 'asked once on the guest Home');
      expect(runtime.permission, PushPermission.authorized);
      expect(
        identical(tester.widget(find.byType(MaterialApp)), app),
        isTrue,
        reason: 'push becoming ready must not rebuild the app root',
      );
      expect(starts, 1);

      await _shutdown(tester);
    });

    testWidgets('the coordinator registers once push is ready, not before', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(201, {'id': 3, 'active': true}),
        );
      final push = DeferredPushMessaging();
      final container = _coordinatorContainer(backend, _PushTokenStore(), push);

      container.read(pushCoordinatorProvider);
      // A resume can land before Firebase is up; it waits instead of failing.
      final early = container
          .read(pushCoordinatorProvider.notifier)
          .refreshPermission();
      await _settle(tester, 3);
      expect(
        container.read(pushCoordinatorProvider).availability,
        PushAvailability.initializing,
      );
      expect(backend.to('POST', '/api/notifications/devices'), isEmpty);

      await push.start(
        () async =>
            _FakePushMessaging(currentPermission: PushPermission.authorized),
      );
      await _settle(tester, 3);
      await early;

      final runtime = container.read(pushCoordinatorProvider);
      expect(runtime.availability, PushAvailability.available);
      expect(runtime.permission, PushPermission.authorized);
      expect(runtime.registration, PushRegistrationState.registered);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
    });

    testWidgets('a failed Firebase start leaves push off and the app usable', (
      tester,
    ) async {
      final backend = FakeBackend();
      final push = DeferredPushMessaging();
      final container = _coordinatorContainer(backend, _PushTokenStore(), push);
      container.read(pushCoordinatorProvider);

      await push.start(() async => throw StateError('no google-services'));
      await _settle(tester, 3);

      final runtime = container.read(pushCoordinatorProvider);
      expect(runtime.availability, PushAvailability.initializationFailed);
      expect(runtime.registration, PushRegistrationState.idle);
      expect(
        await container
            .read(pushCoordinatorProvider.notifier)
            .requestPermission(),
        PushPermission.unavailable,
      );
      expect(backend.requests, isEmpty);
      expect(container.read(sessionProvider), isA<SessionSignedIn>());
    });

    testWidgets('settings show a neutral notice while push is starting', (
      tester,
    ) async {
      final container = ProviderContainer(
        overrides: [
          pushCoordinatorProvider.overrideWith(
            () => _StaticPushCoordinator(
              const PushRuntimeState(
                availability: PushAvailability.initializing,
              ),
            ),
          ),
          pushPreferencesProvider.overrideWith(
            (ref) async => const PushPreferences(
              essentialEnabled: true,
              messagesEnabled: true,
              marketplaceEnabled: true,
            ),
          ),
        ],
      );

      await pumpApp(
        tester,
        const NotificationSettingsScreen(),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('Get timely updates'), findsOneWidget);
      expect(find.textContaining('could not start'), findsNothing);
      expect(find.textContaining('not configured'), findsNothing);
    });
  });

  group('first open asks for notification permission once', () {
    FakeBackend devices() => FakeBackend()
      ..on(
        'POST',
        '/api/notifications/devices',
        const FakeResponse(201, {'id': 3, 'active': true}),
      );

    Future<void> background(WidgetTester tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      await _settle(tester, 2);
    }

    Future<void> resume(WidgetTester tester) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await _settle(tester, 3);
    }

    testWidgets('a guest is asked, and the phone registers only at sign-in', (
      tester,
    ) async {
      final backend = devices();
      final push = _FakePushMessaging();
      final container = _coordinatorContainer(
        backend,
        _PushTokenStore(),
        push,
        session: _HandSession.new,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);

      expect(push.requests, 1);
      var runtime = container.read(pushCoordinatorProvider);
      expect(runtime.permission, PushPermission.authorized);
      expect(runtime.registration, PushRegistrationState.idle);
      expect(backend.to('POST', '/api/notifications/devices'), isEmpty);

      (container.read(sessionProvider.notifier) as _HandSession).enter();
      await _settle(tester, 3);

      runtime = container.read(pushCoordinatorProvider);
      expect(runtime.registration, PushRegistrationState.registered);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
      expect(push.requests, 1, reason: 'signing in never asks again');
    });

    testWidgets('signing out and in again is never asked a second time', (
      tester,
    ) async {
      final push = _FakePushMessaging();
      final tokens = _PushTokenStore();
      final container = _coordinatorContainer(
        devices(),
        tokens,
        push,
        session: _HandSession.new,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      final session = container.read(sessionProvider.notifier) as _HandSession;

      session.enter();
      await _settle(tester, 3);
      session.leave();
      await _settle(tester, 3);
      push.currentPermission = PushPermission.notDetermined;
      session.enter();
      await _settle(tester, 3);

      expect(push.requests, 1);
      expect(await tokens.readPushPermissionRequests(), 1);
    });

    testWidgets('a restart does not ask again after a denial', (tester) async {
      final tokens = _PushTokenStore();
      final first = _FakePushMessaging(
        currentPermission: PushPermission.deniedRequestable,
        requestResult: PushPermission.deniedRequestable,
      );
      final one = _coordinatorContainer(devices(), tokens, first);
      one.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      expect(first.requests, 1);

      // Android 13+ reports the same requestable denial on the next launch,
      // exactly as it did before the first request.
      final second = _FakePushMessaging(
        currentPermission: PushPermission.deniedRequestable,
      );
      final two = _coordinatorContainer(devices(), tokens, second);
      two.read(pushCoordinatorProvider);
      await _settle(tester, 3);

      expect(second.requests, 0);
      expect(
        two.read(pushCoordinatorProvider).permission,
        PushPermission.deniedRequestable,
        reason: 'Profile still offers the retry',
      );
    });

    testWidgets('Android 13+ asks on a fresh install that reads as denied', (
      tester,
    ) async {
      final push = _FakePushMessaging(
        currentPermission: PushPermission.deniedRequestable,
      );
      final container = _coordinatorContainer(
        devices(),
        _PushTokenStore(),
        push,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);

      expect(push.requests, 1);
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.authorized,
      );
    });

    testWidgets('after a denial Profile retries once, then needs Settings', (
      tester,
    ) async {
      final push = _FakePushMessaging(
        currentPermission: PushPermission.deniedRequestable,
        requestResult: PushPermission.deniedRequestable,
      );
      final container = _coordinatorContainer(
        devices(),
        _PushTokenStore(),
        push,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      expect(push.requests, 1, reason: 'the first-open prompt');
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.deniedRequestable,
      );

      await background(tester);
      await resume(tester);
      await resume(tester);
      expect(push.requests, 1, reason: 'a resume never asks again');

      final coordinator = container.read(pushCoordinatorProvider.notifier);
      await coordinator.requestPermission();
      expect(push.requests, 2, reason: 'the Profile button is explicit');
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.settingsRequired,
        reason: 'Android shows its dialog twice; the next denial is final',
      );

      await background(tester);
      await resume(tester);
      expect(push.requests, 2);
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.settingsRequired,
      );
    });

    testWidgets('a refusal on iPhone is not asked again', (tester) async {
      final push = _FakePushMessaging(
        requestResult: PushPermission.settingsRequired,
      );
      final container = _coordinatorContainer(
        devices(),
        _PushTokenStore(),
        push,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      expect(push.requests, 1);
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.settingsRequired,
        reason: 'Profile offers Settings',
      );

      await background(tester);
      await resume(tester);
      expect(push.requests, 1);
    });

    testWidgets('a denial the system cannot ask about again is never asked', (
      tester,
    ) async {
      // Android below 13 has no runtime dialog and a permanent denial cannot
      // show one: both reach the app as `settingsRequired`.
      final tokens = _PushTokenStore();
      final push = _FakePushMessaging(
        currentPermission: PushPermission.settingsRequired,
      );
      final container = _coordinatorContainer(devices(), tokens, push);
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      await background(tester);
      await resume(tester);

      expect(push.requests, 0);
      expect(await tokens.readPushPermissionRequests(), 0);
      expect(
        container.read(pushCoordinatorProvider).permission,
        PushPermission.settingsRequired,
      );
    });

    testWidgets('a grant already given is not asked again and registers', (
      tester,
    ) async {
      for (final granted in [
        PushPermission.authorized,
        PushPermission.provisional,
      ]) {
        final backend = devices();
        final push = _FakePushMessaging(currentPermission: granted);
        final container = _coordinatorContainer(
          backend,
          _PushTokenStore(),
          push,
        );
        container.read(pushCoordinatorProvider);
        await _settle(tester, 3);

        expect(push.requests, 0, reason: '$granted');
        expect(
          container.read(pushCoordinatorProvider).registration,
          PushRegistrationState.registered,
        );
        expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
      }
    });

    testWidgets('granting in Settings registers on the return', (tester) async {
      final backend = devices();
      final push = _FakePushMessaging(
        currentPermission: PushPermission.settingsRequired,
      );
      final container = _coordinatorContainer(backend, _PushTokenStore(), push);
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.idle,
      );

      await background(tester);
      push.currentPermission = PushPermission.authorized;
      await resume(tester);

      final runtime = container.read(pushCoordinatorProvider);
      expect(runtime.permission, PushPermission.authorized);
      expect(runtime.registration, PushRegistrationState.registered);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
      expect(
        push.requests,
        0,
        reason: 'nobody asked: the person went to Settings',
      );
    });

    testWidgets(
      'a Firebase that never started asks nothing and spends nothing',
      (tester) async {
        final tokens = _PushTokenStore();
        for (final failing in [
          DeferredPushMessaging()
            ..start(() async => throw StateError('no google-services')),
          DeferredPushMessaging()..start(
            () async => const DisabledPushMessaging(
              availability: PushAvailability.configurationIncomplete,
            ),
          ),
        ]) {
          final container = _coordinatorContainer(devices(), tokens, failing);
          container.read(pushCoordinatorProvider);
          await _settle(tester, 3);
          expect(container.read(sessionProvider), isA<SessionSignedIn>());
        }
        expect(await tokens.readPushPermissionRequests(), 0);

        // The next launch that can ask still does.
        final working = _FakePushMessaging();
        _coordinatorContainer(
          devices(),
          tokens,
          working,
        ).read(pushCoordinatorProvider);
        await _settle(tester, 3);
        expect(working.requests, 1);
      },
    );

    // Plain `test`, not `testWidgets`: the failed request is retried by the
    // HTTP layer on real timers, which a widget test's fake clock never fires.
    test('registration that fails after the prompt is retried without '
        'asking again', () async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(500, {'detail': 'temporary failure'})
              : const FakeResponse(201, {'id': 3, 'active': true});
        });
      final push = _FakePushMessaging();
      final container = _coordinatorContainer(backend, _PushTokenStore(), push);
      container.read(pushCoordinatorProvider);
      for (var i = 0; i < 300; i++) {
        if (container.read(pushCoordinatorProvider).registration ==
            PushRegistrationState.failed) {
          break;
        }
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      expect(push.requests, 1);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
      );

      await container
          .read(pushCoordinatorProvider.notifier)
          .retryRegistration();

      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
      expect(push.requests, 1);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(2));
    });

    testWidgets('startup, resume and the Profile button share one dialog', (
      tester,
    ) async {
      final tokens = _PushTokenStore();
      final push = _FakePushMessaging()..dialog = Completer<void>();
      final container = _coordinatorContainer(devices(), tokens, push);
      final coordinator = container.read(pushCoordinatorProvider.notifier);
      await _settle(tester, 3);
      expect(push.requests, 1, reason: 'the first-open prompt is showing');
      expect(
        await tokens.readPushPermissionRequests(),
        1,
        reason: 'counted before the system is asked, in case the app dies',
      );

      final profile = coordinator.requestPermission();
      await background(tester);
      await resume(tester);
      await resume(tester);
      expect(push.requests, 1);

      push.dialog!.complete();
      await _settle(tester, 3);
      expect(await profile, PushPermission.authorized);
      expect(push.requests, 1);
      expect(await tokens.readPushPermissionRequests(), 1);
    });

    testWidgets('the Profile button asking first keeps startup from asking', (
      tester,
    ) async {
      final push = DeferredPushMessaging();
      final container = _coordinatorContainer(
        devices(),
        _PushTokenStore(),
        push,
      );
      final coordinator = container.read(pushCoordinatorProvider.notifier);
      final profile = coordinator.requestPermission();
      final fake = _FakePushMessaging();

      await push.start(() async => fake);
      await _settle(tester, 3);
      expect(await profile, PushPermission.authorized);
      await resume(tester);

      expect(fake.requests, 1);
    });

    testWidgets('a launch in the background asks when the app comes forward', (
      tester,
    ) async {
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      addTearDown(
        () => tester.binding.handleAppLifecycleStateChanged(
          AppLifecycleState.resumed,
        ),
      );
      final push = _FakePushMessaging();
      final container = _coordinatorContainer(
        devices(),
        _PushTokenStore(),
        push,
      );
      container.read(pushCoordinatorProvider);
      await _settle(tester, 3);
      expect(push.requests, 0, reason: 'nobody is looking at the phone');

      await resume(tester);
      expect(push.requests, 1);
    });

    testWidgets('the splash is not a usable screen: no prompt until it ends', (
      tester,
    ) async {
      var online = false;
      final backend = FakeBackend()
        ..handle(
          'GET',
          '/api/me',
          (r) => online ? FakeResponse(200, meFixture()) : _offline(r),
        )
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(201, {'id': 3, 'active': true}),
        )
        ..fallback = (_) => const FakeResponse(503, {'detail': 'unavailable'});
      final push = _FakePushMessaging();
      final container = await _boot(
        tester,
        backend: backend,
        tokens: _PushTokenStore(),
        push: push,
      );

      await _settle(tester, 20);
      expect(find.byType(SplashScreen), findsOneWidget);
      expect(push.requests, 0);

      await _settle(tester, 70);
      expect(push.requests, 0, reason: 'still offline, still on the splash');

      online = true;
      await tester.tap(find.text('Try again'));
      await _settle(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(push.requests, 1);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );

      await _shutdown(tester);
    });

    testWidgets('the first frame is drawn before anything asks', (
      tester,
    ) async {
      final push = DeferredPushMessaging();
      final fake = _FakePushMessaging();
      var requestsAtFirstFrame = -1;
      push.startAfterFirstFrame(() async {
        requestsAtFirstFrame = fake.requests;
        return fake;
      });

      await _boot(
        tester,
        backend: FakeBackend()..emptyDiscovery(),
        tokens: _PushTokenStore(refresh: null),
        push: push,
      );
      expect(find.byType(MaterialApp), findsOneWidget);
      await _settle(tester, 5);

      expect(requestsAtFirstFrame, 0);
      expect(fake.requests, 1);
      expect(find.byType(HomeScreen), findsOneWidget);

      await _shutdown(tester);
    });
  });

  testWidgets('an offline launch without a snapshot offers a way out', (
    tester,
  ) async {
    var online = false;
    final backend = FakeBackend()
      ..handle(
        'GET',
        '/api/me',
        (r) => online ? FakeResponse(200, meFixture()) : _offline(r),
      )
      // Whatever Home reads once signed in; this test is about the splash.
      ..fallback = (_) => const FakeResponse(503, {'detail': 'unavailable'});
    final container = await _boot(
      tester,
      backend: backend,
      tokens: _PushTokenStore(),
      push: const DisabledPushMessaging(),
    );

    await _settle(tester, 20);
    expect(find.byType(SplashScreen), findsOneWidget);
    expect(container.read(sessionProvider), isA<SessionRestoring>());
    expect(find.text('Try again'), findsNothing, reason: 'not before 8 s');

    await _settle(tester, 70);
    expect(find.textContaining('Check your connection'), findsOneWidget);
    expect(find.text('Try again'), findsOneWidget);
    expect(
      container.read(sessionProvider),
      isA<SessionRestoring>(),
      reason: 'offline is not signed out: credentials are kept',
    );

    online = true;
    await tester.tap(find.text('Try again'));
    await _settle(tester);

    expect(container.read(sessionProvider), isA<SessionSignedIn>());
    expect(find.byType(SplashScreen), findsNothing);

    await _shutdown(tester);
  });
}
