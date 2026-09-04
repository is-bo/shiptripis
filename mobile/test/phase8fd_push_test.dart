/// Phase 8F-D: push taps route only from structured, non-secret identifiers.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/data/auth_repository.dart';
import 'package:shiptrip/domain/push.dart';
import 'package:shiptrip/features/profile/notification_settings_screen.dart';

import 'support/harness.dart';
import 'support/fake_api.dart';

class _PushTokenStore extends FakeTokenStore {
  _PushTokenStore();

  @override
  Future<String> readOrCreateInstallationId() async =>
      'ca7eedc0-1665-4bbd-bfae-45f841beb8d7';
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
      available: true,
      permission: PushPermission.authorized,
    );
    return PushPermission.authorized;
  }
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
        available: true,
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

  testWidgets('Arabic preferences are RTL and essential remains fixed', (
    tester,
  ) async {
    final coordinator = _FakePushCoordinator(
      const PushRuntimeState(available: false),
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
