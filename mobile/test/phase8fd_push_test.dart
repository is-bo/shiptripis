/// Phase 8F-D: push taps route only from structured, non-secret identifiers.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/auth_repository.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/push.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';

import 'support/harness.dart';
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
  Future<PushPermission> requestPermission() async {
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
        pushLocation({'channel': 'trip.updated', 'trip_id': '10'}),
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

  test(
    'logout sends only the current installation and still works offline',
    () async {
      final online = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
      final onlineTokens = _PushTokenStore();
      await AuthRepository(
        apiClientFor(online, onlineTokens),
        onlineTokens,
      ).signOut();
      expect(online.lastTo('POST', '/api/auth/sign-out')?.body, {
        'refresh': 'refresh-token',
        'installation_id': 'ca7eedc0-1665-4bbd-bfae-45f841beb8d7',
      });

      final offline = FakeBackend();
      final offlineTokens = _PushTokenStore();
      await expectLater(
        AuthRepository(
          apiClientFor(offline, offlineTokens),
          offlineTokens,
        ).signOut(),
        completes,
      );
    },
  );

  testWidgets('permission is requested only from the contextual action', (
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

  test(
    'permission grant uses the existing secure device registration API',
    () async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/notifications/devices',
          const FakeResponse(201, {'id': 3, 'active': true}),
        );
      final tokens = _PushTokenStore();
      final messaging = _FakePushMessaging();
      final router = GoRouter(
        routes: [
          GoRoute(path: '/', builder: (_, _) => const SizedBox.shrink()),
        ],
      );
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
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

      final coordinator = container.read(pushCoordinatorProvider.notifier);
      await Future<void>.delayed(Duration.zero);
      expect(messaging.requests, 0);
      await coordinator.requestPermission();
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.registered,
      );

      expect(messaging.requests, 1);
      expect(backend.to('POST', '/api/notifications/devices'), hasLength(1));
      expect(backend.lastTo('POST', '/api/notifications/devices')?.body, {
        'token': 'fcm-token-that-never-enters-the-ui',
        'installation_id': 'ca7eedc0-1665-4bbd-bfae-45f841beb8d7',
        'platform': 'android',
        'app_version': '',
      });
    },
  );

  test(
    'failed device registration can be retried without re-prompting',
    () async {
      var attempts = 0;
      final backend = FakeBackend()
        ..handle('POST', '/api/notifications/devices', (_) {
          attempts++;
          return attempts == 1
              ? const FakeResponse(500, {'detail': 'temporary failure'})
              : const FakeResponse(201, {'id': 3, 'active': true});
        });
      final tokens = _PushTokenStore();
      final messaging = _FakePushMessaging();
      final router = GoRouter(
        routes: [
          GoRoute(path: '/', builder: (_, _) => const SizedBox.shrink()),
        ],
      );
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
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

      final coordinator = container.read(pushCoordinatorProvider.notifier);
      await coordinator.requestPermission();
      expect(
        container.read(pushCoordinatorProvider).registration,
        PushRegistrationState.failed,
      );
      expect(messaging.requests, 1);

      await coordinator.retryRegistration();
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
