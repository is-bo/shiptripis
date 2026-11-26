/// N1: what a person can do about notifications without an account, and how
/// the phone's registration keeps its place when the server has seen more.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/auth_repository.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';

import 'support/fake_api.dart';
import 'support/push_router.dart';

class _Store extends FakeTokenStore {
  _Store({super.refresh});

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
}

class _Messaging implements PushMessaging {
  _Messaging({this.currentPermission = PushPermission.notDetermined});

  PushPermission currentPermission;
  PushPermission requestResult = PushPermission.authorized;
  int requests = 0;

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
    return currentPermission = requestResult;
  }

  @override
  Future<String?> token() async => 'fcm-token';
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

class _Member extends SessionController {
  @override
  SessionState build() => SessionSignedIn(Account.fromJson(meFixture()));
}

Future<void> _settle(WidgetTester tester, [int frames = 10]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  group('without an account', () {
    Future<(ProviderContainer, FakeBackend, _Messaging)> openGuestProfile(
      WidgetTester tester,
      _Messaging push,
    ) async {
      tester.view.devicePixelRatio = 1;
      tester.view.physicalSize = const Size(360, 800);
      addTearDown(tester.view.reset);
      final backend = FakeBackend()..emptyDiscovery();
      final tokens = _Store(refresh: null);
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
      final container = ProviderScope.containerOf(
        tester.element(find.byType(ShipTripApp)),
      );
      await _settle(tester);
      await tester.tap(find.text('Profile'));
      await _settle(tester);
      return (container, backend, push);
    }

    testWidgets('guest Profile offers the notification controls, and a refusal '
        'is recoverable from there', (tester) async {
      final push = _Messaging()
        ..requestResult = PushPermission.deniedRequestable;
      final (container, backend, _) = await openGuestProfile(tester, push);
      expect(push.requests, 1, reason: 'asked once on the guest front page');
      expect(find.byType(ProfileScreen), findsOneWidget);

      await tester.tap(find.text('Notifications'));
      await _settle(tester);

      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      expect(find.byType(NotificationSettingsScreen), findsOneWidget);
      expect(find.textContaining('still off'), findsOneWidget);
      expect(
        find.text('Enable notifications'),
        findsOneWidget,
        reason: 'a guest can ask again',
      );
      expect(find.textContaining('Sign in to receive'), findsOneWidget);
      expect(
        backend.to('GET', '/api/notifications/preferences'),
        isEmpty,
        reason: 'account preferences load after sign-in',
      );

      push.requestResult = PushPermission.authorized;
      await tester.tap(find.text('Enable notifications'));
      await _settle(tester);

      expect(push.requests, 2);
      expect(
        find.textContaining('Sign in and Wassla will start'),
        findsOneWidget,
      );
      expect(
        backend.to('POST', '/api/notifications/devices'),
        isEmpty,
        reason: 'the phone registers to an account at sign-in',
      );
    });
  });

  group('the registration number', () {
    Future<ProviderContainer> member(
      WidgetTester tester,
      FakeBackend backend,
      FakeTokenStore tokens,
    ) async {
      final router = pushTestRouter();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
          sessionProvider.overrideWith(_Member.new),
          routerProvider.overrideWithValue(router),
          notificationSocketProvider.overrideWithValue(_NoopSocket()),
          pushMessagingProvider.overrideWithValue(
            _Messaging(currentPermission: PushPermission.authorized),
          ),
        ],
      );
      addTearDown(() {
        container.dispose();
        router.dispose();
      });
      await mountRouter(tester, container, router);
      return container;
    }

    testWidgets(
      'signing out takes a number above the registration it follows',
      (tester) async {
        final backend = FakeBackend()
          ..on(
            'POST',
            '/api/notifications/devices',
            const FakeResponse(201, {'id': 3, 'active': true}),
          )
          ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
        final tokens = _Store();
        final container = await member(tester, backend, tokens);
        container.read(pushCoordinatorProvider);
        await _settle(tester);

        unawaited(
          AuthRepository(apiClientFor(backend, tokens), tokens).signOut(),
        );
        await _settle(tester);

        expect(
          backend
              .lastTo('POST', '/api/notifications/devices')
              ?.body['binding_sequence'],
          1,
        );
        expect(
          backend
              .lastTo('POST', '/api/auth/sign-out')
              ?.body['binding_sequence'],
          2,
        );
      },
    );

    testWidgets('a phone that fell behind the server catches up and registers '
        'once more', (tester) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(409, {
                  'code': 'push_registration_superseded',
                  'detail': 'newer',
                  'current_sequence': 40,
                })
              : const FakeResponse(200, {'id': 3, 'active': true});
        });
      final container = await member(tester, backend, _Store());
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      final sent = backend.to('POST', '/api/notifications/devices');
      expect([for (final r in sent) r.body['binding_sequence']], [1, 41]);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
    });

    testWidgets('a registration the server keeps refusing as old stops after '
        'one more try', (tester) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(409, {
            'code': 'push_registration_superseded',
            'detail': 'newer',
            'current_sequence': 40,
          }),
        );
      final container = await member(tester, backend, _Store());
      container.read(pushCoordinatorProvider);
      await _settle(tester);

      expect(backend.to('POST', '/api/notifications/devices'), hasLength(2));
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
        reason: 'the Retry button is the way back',
      );
    });
  });
}
