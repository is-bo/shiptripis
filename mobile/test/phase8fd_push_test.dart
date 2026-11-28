/// Phase 8F-D: push taps route only from structured, non-secret identifiers.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/push.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';

import 'support/harness.dart';
import 'support/push_router.dart';
import 'support/fake_api.dart';

class _PushTokenStore extends FakeTokenStore {
  _PushTokenStore();

  String? _pendingPushToken;

  @override
  Future<String> readOrCreateInstallationId() async =>
      'ca7eedc0-1665-4bbd-bfae-45f841beb8d7';

  @override
  Future<String?> readPendingPushToken() async => _pendingPushToken;

  @override
  Future<void> writePendingPushToken(String? token) async {
    _pendingPushToken = token;
  }
}

class _FakePushCoordinator extends PushCoordinator {
  _FakePushCoordinator(this.initial);

  final PushRuntimeState initial;
  bool requested = false;

  @override
  PushRuntimeState build() => initial;

  @override
  Future<PushPermission> requestPermission({bool Function()? onScreen}) async {
    requested = true;
    state = const PushRuntimeState(
      availability: PushAvailability.available,
      permission: PushPermission.authorized,
      registration: PushRegistrationState.registered,
    );
    return PushPermission.authorized;
  }
}

class _FakePushMessaging implements PushMessaging {
  _FakePushMessaging();

  PushPermission currentPermission = PushPermission.notDetermined;
  PushPermission requestResult = PushPermission.authorized;
  String? currentToken = 'fcm-token-that-never-enters-the-ui';
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
    currentPermission = requestResult;
    return requestResult;
  }

  @override
  Future<String?> token() async => currentToken;
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// A signed-in coordinator with a router on screen: the first-open prompt asks
/// only once a usable screen is painted.
Future<ProviderContainer> _mountedCoordinator(
  WidgetTester tester,
  FakeBackend backend,
  FakeTokenStore tokens,
  PushMessaging messaging,
) async {
  final router = pushTestRouter();
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      sessionCoreProvider.overrideWithValue(backend.session),
      fakeApiClient(backend),
      sessionProvider.overrideWith(_FixedSession.new),
      routerProvider.overrideWithValue(router),
      notificationSocketProvider.overrideWithValue(_NoopSocket()),
      pushMessagingProvider.overrideWithValue(messaging),
    ],
  );
  addTearDown(() {
    container.dispose();
    router.dispose();
  });
  await mountRouter(tester, container, router);
  return container;
}

class _FixedSession extends SessionController {
  @override
  SessionState build() =>
      SessionSignedIn(Account.fromJson(meFixture()), sid: 'sid-a');
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

void main() {
  group('push tap routing', () {
    test('chat opens its thread', () {
      expect(
        pushLocation({'channel': 'chat.message.new', 'match_id': '42'}),
        '/chat/thread/42',
      );
    });

    test('business identifiers open their authoritative detail', () {
      expect(
        pushLocation({'channel': 'dispute.opened', 'dispute_id': '8'}),
        '/disputes/8',
      );
      expect(
        pushLocation({'channel': 'payment.captured', 'deal_id': '9'}),
        '/deals/9',
      );
      expect(
        pushLocation({'channel': 'leg_proof.status_changed', 'trip_id': '10'}),
        '/journeys/10',
      );
      expect(
        pushLocation({'channel': 'offer.created', 'parcel_id': '11'}),
        '/requests/11',
      );
    });

    test('an open negotiation opens the negotiation, not the journey', () {
      // The real payload: `match_resources` puts `journey_id` on every V1
      // offer event so the traveler's journey can be invalidated live. It is
      // not the destination — tapping "New offer" as the sender must not open
      // the traveler's journey, which the sender may not be able to read.
      const offerPayload = {
        'channel': 'offer.created',
        'match_id': '31',
        'parcel_id': '11',
        'journey_id': '77',
      };
      expect(pushLocation(offerPayload), '/matches/31');
      expect(
        pushLocation({...offerPayload, 'channel': 'offer.updated'}),
        '/matches/31',
      );
      // Once accepted there is a Deal, and the Deal stays authoritative.
      expect(
        pushLocation({
          ...offerPayload,
          'channel': 'offer.accepted',
          'deal_id': '54',
        }),
        '/deals/54',
      );
    });

    test('account and payment events use safe fallback destinations', () {
      expect(pushLocation({'channel': 'kyc.status_changed'}), '/kyc');
      expect(
        pushLocation({'channel': 'payout.status_changed'}),
        '/profile/payouts',
      );
      expect(pushLocation({'channel': 'unknown.new'}), '/notifications');
    });

    test('invalid or absent identifiers cannot form a route', () {
      expect(pushLocation(const {}), isNull);
      expect(
        pushLocation({'channel': 'chat.message.new', 'match_id': '-1'}),
        '/notifications',
      );
      expect(
        pushLocation({'channel': 'chat.message.new', 'match_id': '../admin'}),
        '/notifications',
      );
    });
  });

  test('missing preference fields retain safe enabled defaults', () {
    final preferences = PushPreferences.fromJson(const {});
    expect(preferences.essentialEnabled, isTrue);
    expect(preferences.messagesEnabled, isTrue);
    expect(preferences.marketplaceEnabled, isTrue);
  });

  test('Android permission states preserve retry and Settings semantics', () {
    expect(
      classifyPushPermission(
        AuthorizationStatus.denied,
        platform: TargetPlatform.android,
        androidRuntimePermissionSupported: true,
      ),
      PushPermission.deniedRequestable,
    );
    expect(
      classifyPushPermission(
        AuthorizationStatus.denied,
        platform: TargetPlatform.android,
        androidRuntimePermissionSupported: false,
      ),
      PushPermission.settingsRequired,
    );
    expect(
      classifyPushPermission(
        AuthorizationStatus.deniedPermanently,
        platform: TargetPlatform.android,
        androidRuntimePermissionSupported: true,
      ),
      PushPermission.settingsRequired,
    );
  });

  // Plan 5.3, rule N-B: ending the sign-in switches off every device it
  // registered, so the sign-out no longer names the installation.
  test('logout sends only its refresh token and still works offline', () async {
    final online = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
    final signedIn = containerFor(online);
    addTearDown(signedIn.dispose);
    await launch(signedIn);
    await signedIn.read(sessionProvider.notifier).signOut();
    await pumpEventQueue();
    expect(online.lastTo('POST', '/api/auth/sign-out')?.body, {
      'refresh': fakeToken('sid-a'),
    });

    final offline = FakeBackend();
    final noNetwork = containerFor(offline);
    addTearDown(noNetwork.dispose);
    await noNetwork.read(sessionCoreProvider).load();
    await expectLater(
      noNetwork.read(sessionProvider.notifier).signOut(),
      completes,
    );
    expect(noNetwork.read(sessionProvider), isA<SessionSignedOut>());
  });

  testWidgets('the Profile screen asks only when its button is pressed', (
    tester,
  ) async {
    final coordinator = _FakePushCoordinator(
      const PushRuntimeState(
        availability: PushAvailability.available,
        permission: PushPermission.notDetermined,
      ),
    );
    final container = ProviderContainer(
      overrides: [
        pushCoordinatorProvider.overrideWith(() => coordinator),
        sessionProvider.overrideWith(_FixedSession.new),
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

    expect(coordinator.requested, isFalse);
    await tester.tap(find.text('Enable notifications'));
    await tester.pump();
    expect(coordinator.requested, isTrue);
    expect(find.text('Notifications are enabled.'), findsOneWidget);
  });

  testWidgets('retryable denial offers another explicit Android request', (
    tester,
  ) async {
    final coordinator = _FakePushCoordinator(
      const PushRuntimeState(
        availability: PushAvailability.available,
        permission: PushPermission.deniedRequestable,
      ),
    );
    final container = ProviderContainer(
      overrides: [
        pushCoordinatorProvider.overrideWith(() => coordinator),
        sessionProvider.overrideWith(_FixedSession.new),
        pushPreferencesProvider.overrideWith(
          (ref) async => const PushPreferences(
            essentialEnabled: true,
            messagesEnabled: false,
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
    expect(coordinator.requested, isFalse);
    expect(find.text('Enable notifications'), findsOneWidget);

    await tester.tap(find.text('Enable notifications'));
    await tester.pumpAndSettle();
    expect(coordinator.requested, isTrue);
  });

  testWidgets('permanent denial requires Settings and keeps preferences', (
    tester,
  ) async {
    final coordinator = _FakePushCoordinator(
      const PushRuntimeState(
        availability: PushAvailability.available,
        permission: PushPermission.settingsRequired,
      ),
    );
    final container = ProviderContainer(
      overrides: [
        pushCoordinatorProvider.overrideWith(() => coordinator),
        sessionProvider.overrideWith(_FixedSession.new),
        pushPreferencesProvider.overrideWith(
          (ref) async => const PushPreferences(
            essentialEnabled: true,
            messagesEnabled: false,
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

    expect(find.text('Open notification settings'), findsOneWidget);
    expect(find.text('Enable notifications'), findsNothing);
    expect(find.text('Notification types'), findsOneWidget);
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches[1].value, isFalse);
    expect(switches[2].value, isTrue);
  });

  testWidgets('configuration and registration failures are distinct', (
    tester,
  ) async {
    var state = const PushRuntimeState(
      availability: PushAvailability.configurationIncomplete,
    );
    final coordinator = _FakePushCoordinator(state);
    final container = ProviderContainer(
      overrides: [
        pushCoordinatorProvider.overrideWith(() => coordinator),
        sessionProvider.overrideWith(_FixedSession.new),
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
    expect(find.textContaining('not configured in this build'), findsOneWidget);

    state = const PushRuntimeState(
      availability: PushAvailability.available,
      permission: PushPermission.authorized,
      registration: PushRegistrationState.failed,
    );
    coordinator.state = state;
    await tester.pumpAndSettle();
    expect(find.text('Retry notification setup'), findsOneWidget);
    expect(find.textContaining('could not finish registering'), findsOneWidget);
  });

  testWidgets(
    'the first-open grant uses the existing secure device registration API',
    (tester) async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(201, {'id': 3, 'active': true}),
        );
      final tokens = _PushTokenStore();
      final messaging = _FakePushMessaging();
      final container = await _mountedCoordinator(
        tester,
        backend,
        tokens,
        messaging,
      );

      container.read(pushCoordinatorProvider);
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );

      expect(messaging.requests, 1, reason: 'asked on its own, once');
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
      expect(backend.lastTo('POST', '/api/notifications/devices')?.body, {
        'token': 'fcm-token-that-never-enters-the-ui',
        'installation_id': 'ca7eedc0-1665-4bbd-bfae-45f841beb8d7',
        'binding_sequence': 1,
        'platform': 'android',
        'app_version': '',
      });
    },
  );

  testWidgets(
    'failed device registration can be retried without re-prompting',
    (tester) async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(500, {'detail': 'server error'})
              : const FakeResponse(201, {'id': 3, 'active': true});
        });
      final messaging = _FakePushMessaging();
      final container = await _mountedCoordinator(
        tester,
        backend,
        _PushTokenStore(),
        messaging,
      );

      final coordinator = container.read(pushCoordinatorProvider.notifier);
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
      );
      expect(messaging.requests, 1);

      unawaited(coordinator.retryRegistration());
      await _settle(tester);
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );
      expect(messaging.requests, 1);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(2));
    },
  );

  testWidgets('Arabic preferences are RTL and essential remains fixed', (
    tester,
  ) async {
    final coordinator = _FakePushCoordinator(
      const PushRuntimeState(
        availability: PushAvailability.configurationIncomplete,
      ),
    );
    final container = ProviderContainer(
      overrides: [
        pushCoordinatorProvider.overrideWith(() => coordinator),
        sessionProvider.overrideWith(_FixedSession.new),
        pushPreferencesProvider.overrideWith(
          (ref) async => const PushPreferences(
            essentialEnabled: true,
            messagesEnabled: false,
            marketplaceEnabled: true,
          ),
        ),
      ],
    );

    await pumpApp(
      tester,
      const NotificationSettingsScreen(),
      locale: const Locale('ar'),
      container: container,
    );
    await tester.pumpAndSettle();

    final context = tester.element(find.text('التحديثات الأساسية'));
    expect(Directionality.of(context), TextDirection.rtl);
    final switches = tester.widgetList<Switch>(find.byType(Switch)).toList();
    expect(switches, hasLength(3));
    expect(switches.first.onChanged, isNull);
    expect(switches[1].value, isFalse);
    expect(switches[2].value, isTrue);
  });
}
