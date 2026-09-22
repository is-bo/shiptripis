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
import 'package:shiptrip/features/onboarding/onboarding_screen.dart';
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
  _FakePushMessaging({this.currentPermission = PushPermission.notDetermined});

  final PushPermission currentPermission;

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
  Future<PushPermission> requestPermission() async => currentPermission;
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

/// A signed-in coordinator over [push], without a widget tree.
ProviderContainer _coordinatorContainer(
  FakeBackend backend,
  FakeTokenStore tokens,
  PushMessaging push,
) {
  final router = GoRouter(
    routes: [GoRoute(path: '/', builder: (_, _) => const SizedBox.shrink())],
  );
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
      sessionProvider.overrideWith(_FixedSession.new),
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
        backend: FakeBackend(),
        tokens: _PushTokenStore(refresh: null),
        push: push,
      );
      expect(starts, 1, reason: 'started right after the first frame');
      expect(paintedBeforeStart, isTrue);

      await _settle(tester);
      expect(find.byType(OnboardingScreen), findsOneWidget);
      expect(
        container.read(pushCoordinatorProvider).availability,
        PushAvailability.initializing,
      );
      final app = tester.widget(find.byType(MaterialApp));

      firebase.complete(_FakePushMessaging());
      await _settle(tester, 5);

      final runtime = container.read(pushCoordinatorProvider);
      expect(runtime.availability, PushAvailability.available);
      expect(runtime.permission, PushPermission.notDetermined);
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
      final container = _coordinatorContainer(
        backend,
        _PushTokenStore(),
        push,
      );

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
      final container = _coordinatorContainer(
        backend,
        _PushTokenStore(),
        push,
      );
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
