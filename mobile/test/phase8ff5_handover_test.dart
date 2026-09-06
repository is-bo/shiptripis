/// Phase 8F-F5: post-pickup and protection states follow the server handover
/// permissions without exposing a premature delivery action.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/delivery_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _viewerId = 42;

Map<String, dynamic> _deal({
  required bool viewerIsSender,
  required String status,
  required bool inBuffer,
  bool canRevealDelivery = false,
  bool canSubmitDelivery = false,
  bool delivered = false,
  bool completed = false,
}) {
  final availableAt = DateTime.now()
      .add(const Duration(minutes: 24))
      .toUtc()
      .toIso8601String();
  final deliveredAt = delivered ? '2026-09-06T10:00:00Z' : null;
  final payload = dealFixture(
    status: status,
    pickupConfirmedAt: '2026-09-06T09:00:00Z',
    recipient: viewerIsSender ? recipientFixture() : null,
  );
  payload
    ..['sender_id'] = viewerIsSender ? _viewerId : 99
    ..['traveler_id'] = viewerIsSender ? 99 : _viewerId
    ..['delivery_code_available_at'] = availableAt
    ..['delivery_code_released_at'] = inBuffer ? null : '2026-09-06T09:30:00Z'
    ..['delivery_confirmed_at'] = deliveredAt
    ..['protection_ends_at'] = delivered
        ? DateTime.now()
              .add(Duration(hours: completed ? -1 : 47))
              .toUtc()
              .toIso8601String()
        : null
    ..['completed_at'] = completed ? '2026-09-08T10:00:00Z' : null
    ..['handover'] = {
      'deal_status': status,
      'pickup_confirmed_at': '2026-09-06T09:00:00Z',
      'delivery_code_available_at': availableAt,
      'delivery_code_released_at': inBuffer ? null : '2026-09-06T09:30:00Z',
      'delivery_confirmed_at': deliveredAt,
      'in_delivery_code_buffer': inBuffer,
      'pickup': {'exists': false, 'status': 'used'},
      'delivery': {
        'exists': !delivered,
        'status': delivered ? 'used' : (inBuffer ? 'buffered' : 'active'),
      },
      'can_reveal_pickup_code': false,
      'can_reveal_delivery_code': canRevealDelivery,
      'traveler_can_view_delivery_code': false,
      'can_submit_pickup_code': false,
      'can_submit_delivery_code': canSubmitDelivery,
    };
  if (delivered) {
    payload['protection'] = {
      'delivery_confirmed_at': deliveredAt,
      'protection_ends_at': payload['protection_ends_at'],
      'payout': {
        'status': completed ? 'paid' : 'pending',
        'method': 'manual',
        'amount_eur_cents': 3000,
        'eligible_at': payload['protection_ends_at'],
        'paid_at': completed ? '2026-09-08T10:00:00Z' : null,
      },
    };
  }
  return payload;
}

Future<void> _emitAvailability(
  WidgetTester tester,
  ProviderContainer container,
) async {
  final live = container.read(liveUpdatesProvider)..bindAccount(_viewerId);
  live.ingest({
    'type': 'handover.delivery_code_available',
    'event_id': 'f5-code-ready',
    'deal_id': 7,
  }, source: LiveEventSource.websocket);
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pumpAndSettle();
}

void main() {
  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets('${locale.languageCode}: safety wait has no delivery action', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/deals/7',
          FakeResponse(
            200,
            _deal(viewerIsSender: true, status: 'picked_up', inBuffer: true),
          ),
        );

      await pumpApp(
        tester,
        const DealScreen(dealId: 7),
        locale: locale,
        device: locale.languageCode == 'fr'
            ? DeviceProfile.largeText
            : DeviceProfile.smallAndroid,
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DealScreen)));

      expect(find.text(l.pickupConfirmedTitle), findsOneWidget);
      expect(find.text(l.deliverySafetyWaitingSenderBody), findsOneWidget);
      expect(find.text(l.dealActionDelivery), findsNothing);
      expect(tester.takeException(), isNull);
      if (locale.languageCode == 'ar') {
        expect(
          Directionality.of(tester.element(find.byType(DealScreen))),
          TextDirection.rtl,
        );
      }
    });
  }

  testWidgets(
    'traveler receives delivery action only after live authorization',
    (tester) async {
      var available = false;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(
            200,
            _deal(
              viewerIsSender: false,
              status: available ? 'delivery_ready' : 'picked_up',
              inBuffer: !available,
              canSubmitDelivery: available,
            ),
          ),
        );
      final container = containerFor(backend);

      await pumpApp(
        tester,
        const DeliveryScreen(dealId: 7),
        container: container,
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DeliveryScreen)));
      expect(find.text(l.deliverySafetyWaitingTravelerBody), findsOneWidget);
      expect(find.text(l.deliveryConfirmAction), findsNothing);
      expect(find.text(l.deliveryCodeTravelerNever), findsOneWidget);

      available = true;
      await _emitAvailability(tester, container);

      expect(find.text(l.deliveryConfirmAction), findsWidgets);
      expect(find.text(l.deliverySafetyWaitingTravelerBody), findsNothing);
      expect(backend.to('GET', '/api/deals/7').length, greaterThanOrEqualTo(2));
    },
  );

  testWidgets('delivery confirmation shows protection and no obsolete CTA', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(
          200,
          _deal(
            viewerIsSender: false,
            status: 'protection_window',
            inBuffer: false,
            delivered: true,
          ),
        ),
      );

    await pumpApp(
      tester,
      const DeliveryScreen(dealId: 7),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DeliveryScreen)));

    expect(find.text(l.deliveryConfirmedTitle), findsOneWidget);
    expect(find.text(l.protectionTitle), findsWidgets);
    expect(find.text(l.deliveryConfirmAction), findsNothing);
    expect(find.textContaining('fcm-token'), findsNothing);
  });

  testWidgets('completed deal leaves no handover action behind', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(
          200,
          _deal(
            viewerIsSender: true,
            status: 'completed',
            inBuffer: false,
            delivered: true,
            completed: true,
          ),
        ),
      );

    await pumpApp(
      tester,
      const DealScreen(dealId: 7),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DealScreen)));

    expect(find.text(l.dealStatusCompleted), findsWidgets);
    expect(find.text(l.dealActionDelivery), findsNothing);
    expect(find.text(l.dealStepCompleted), findsWidgets);
  });
}
