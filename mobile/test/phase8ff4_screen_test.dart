/// Phase 8F-F4: live events refresh the mounted authoritative screens.
///
/// These tests deliberately drive the shared LiveUpdates bus and then let the
/// real Riverpod providers make their normal HTTP reads through FakeBackend.
/// No event payload is copied into a widget model by the test.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/delivery_screen.dart';
import 'package:shiptrip/features/deals/payment_screen.dart';
import 'package:shiptrip/features/deals/pickup_screen.dart';
import 'package:shiptrip/features/disputes/dispute_detail_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _viewerId = 42;

Map<String, dynamic> _travelerDeal({
  required bool pickedUp,
  String status = 'pickup_ready',
}) {
  final deliveryCodeAvailableAt = pickedUp
      ? DateTime.now()
            .add(const Duration(minutes: 24))
            .toUtc()
            .toIso8601String()
      : null;
  final payload = dealFixture(
    id: 7,
    status: status,
    pickupConfirmedAt: pickedUp ? '2026-08-30T10:00:00Z' : null,
  );
  payload['sender_id'] = 99;
  payload['traveler_id'] = _viewerId;
  payload['delivery_code_available_at'] = deliveryCodeAvailableAt;
  payload['handover'] = {
    'deal_status': status,
    'pickup_confirmed_at': pickedUp ? '2026-08-30T10:00:00Z' : null,
    'pickup': {
      'exists': !pickedUp,
      'status': pickedUp ? 'used' : 'active',
      'rotation': 1,
    },
    'delivery_code_available_at': deliveryCodeAvailableAt,
    'delivery': {
      'exists': pickedUp,
      'status': pickedUp ? 'buffered' : 'unknown',
    },
    'can_reveal_pickup_code': false,
    'can_reveal_delivery_code': false,
    'traveler_can_view_delivery_code': false,
    'can_submit_pickup_code': !pickedUp,
    'can_submit_delivery_code': false,
    'in_delivery_code_buffer': pickedUp,
  };
  return payload;
}

Map<String, dynamic> _senderDeal({
  required String status,
  String? pickupConfirmedAt,
}) {
  final payload = dealFixture(
    id: 7,
    status: status,
    pickupConfirmedAt: pickupConfirmedAt,
  );
  payload['match_id'] = 77;
  payload['handover'] = {
    'deal_status': status,
    'pickup_confirmed_at': pickupConfirmedAt,
    'pickup': {
      'exists': pickupConfirmedAt == null,
      'status': pickupConfirmedAt == null ? 'active' : 'used',
      'rotation': 1,
    },
    'delivery': {'exists': false, 'status': 'unknown'},
    'can_reveal_pickup_code': pickupConfirmedAt == null,
    'can_reveal_delivery_code': false,
    'traveler_can_view_delivery_code': false,
    'can_submit_pickup_code': false,
    'can_submit_delivery_code': false,
    'in_delivery_code_buffer': false,
  };
  return payload;
}

Map<String, dynamic> _offer({
  required int id,
  required String status,
  required List<String> allowedActions,
  required int reward,
}) => {
  'id': id,
  'match': 77,
  'parent_offer': null,
  'proposed_by': 'traveler',
  'proposer_id': 99,
  'economics_version': 'v1_eur',
  'currency': 'EUR',
  'traveler_reward_minor': reward,
  'commission_rate_bps': 1000,
  'platform_fee_minor': 300,
  'sender_total_minor': reward + 300,
  'status': status,
  'note': '',
  'awaiting_party': status == 'accepted' ? null : 'sender',
  'awaiting_user_id': status == 'accepted' ? null : _viewerId,
  'allowed_actions': allowedActions,
};

Map<String, dynamic> _matchWithOffer(Map<String, dynamic> offer) => {
  'id': 77,
  'parcel_id': 12,
  'journey_id': 21,
  'start_leg_id': 31,
  'end_leg_id': 32,
  'sender_id': _viewerId,
  'traveler_id': 99,
  'sender_name': 'Amina',
  'traveler_name': 'Karim',
  'status': 'pending',
  'latest_offer': offer,
  'parcel': {
    'id': 12,
    'kind': 'delivery',
    'actual_weight_kg': '2.50',
    'origin': {'id': 1, 'name': 'Paris', 'country_code': 'FR'},
    'destination': {'id': 2, 'name': 'Alger', 'country_code': 'DZ'},
  },
};

Map<String, dynamic> _payment({
  required String orderStatus,
  required String attemptStatus,
}) => {
  'deal_id': 7,
  'deal_status': 'payment_required',
  'currency': 'EUR',
  'sender_total_eur_cents': 3500,
  'traveler_reward_eur_cents': 3000,
  'platform_fee_eur_cents': 500,
  'order': {
    'public_reference': 'ord_7',
    'purpose': 'deal_balance',
    'status': orderStatus,
    'currency': 'EUR',
    'amount_eur_cents': 3500,
    'outstanding_eur_cents': orderStatus == 'paid' ? 0 : 3500,
    'paid_eur_cents': orderStatus == 'paid' ? 3500 : 0,
    'attempts': [
      {
        'id': 1,
        'provider': 'stripe',
        'status': attemptStatus,
        'amount_eur_cents': 3500,
        'currency': 'EUR',
        'created_at': '2026-08-30T09:00:00Z',
      },
    ],
    'refunds': <Object>[],
    'providers': <Object>[],
  },
};

Map<String, dynamic> _dispute({required String status}) => {
  'id': 9,
  'public_reference': 'DSP-9',
  'deal_id': 7,
  'deal_status': status == 'resolved' ? 'completed' : 'disputed',
  'status': status,
  'category': 'not_delivered',
  'reason_text': 'The parcel did not arrive.',
  'opened_by_id': _viewerId,
  'opened_by_role': 'sender',
  'opened_at': '2026-08-29T09:00:00Z',
  'protection_ends_at': '2026-09-01T09:00:00Z',
  'resolution': status == 'resolved' ? 'full_sender_refund' : null,
  'sender_refund_eur_cents': status == 'resolved' ? 3500 : null,
  'traveler_payout_eur_cents': 0,
  'platform_fee_eur_cents': 0,
  'collected_total_eur_cents': 3500,
  'resolution_note': status == 'resolved' ? 'Refund approved.' : null,
  'resolved_at': status == 'resolved' ? '2026-08-30T12:00:00Z' : null,
  'closed_at': null,
  'payout_frozen': status != 'resolved',
  'payout_already_settled': false,
  'evidence': <Object>[],
  'events': <Object>[],
};

Future<void> _emit(
  WidgetTester tester,
  ProviderContainer container, {
  required String type,
  required String eventId,
  required Map<String, dynamic> data,
}) async {
  final live = container.read(liveUpdatesProvider);
  live.bindAccount(_viewerId);
  live.ingest({
    'type': type,
    'event_id': eventId,
    ...data,
  }, source: LiveEventSource.websocket);
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
    'traveler pickup submit renders the authoritative post-pickup state',
    (tester) async {
      var pickedUp = false;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(
            200,
            _travelerDeal(
              pickedUp: pickedUp,
              status: pickedUp ? 'picked_up' : 'pickup_ready',
            ),
          ),
        )
        ..handle('POST', '/api/deals/7/handover/pickup', (request) {
          expect(request.body, {'code': 'ABCD1234'});
          pickedUp = true;
          return const FakeResponse(200, {
            'deal_id': 7,
            'kind': 'pickup',
            'status': 'picked_up',
            'changed': true,
          });
        });
      final container = containerFor(backend);

      await pumpApp(
        tester,
        const PickupScreen(dealId: 7),
        container: container,
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(PickupScreen)));
      await tester.enterText(find.byType(TextField), 'ABCD1234');
      await tester.tap(find.text(l.pickupConfirmAction).last);
      await tester.pumpAndSettle();

      expect(find.text(l.pickupConfirmedTitle), findsWidgets);
      expect(find.text(l.pickupConfirmedBody), findsOneWidget);
      expect(find.text(l.deliverySafetyWaitingTravelerBody), findsOneWidget);
      expect(find.text(l.deliveryConfirmAction), findsNothing);
      expect(backend.to('GET', '/api/deals/7').length, greaterThanOrEqualTo(2));
    },
  );

  testWidgets('mounted DealScreen refreshes after a pickup event', (
    tester,
  ) async {
    var pickedUp = false;
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle(
        'GET',
        '/api/deals/7',
        (_) => FakeResponse(
          200,
          _senderDeal(
            status: pickedUp ? 'picked_up' : 'funded',
            pickupConfirmedAt: pickedUp ? '2026-08-30T10:00:00Z' : null,
          ),
        ),
      );
    final container = containerFor(backend);

    await pumpApp(tester, const DealScreen(dealId: 7), container: container);
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DealScreen)));
    expect(find.text(l.dealStatusFunded), findsOneWidget);

    pickedUp = true;
    await _emit(
      tester,
      container,
      type: 'match.in_transit',
      eventId: 'pickup-7',
      data: {'deal_id': 7},
    );

    expect(find.text(l.dealStatusPickedUp), findsOneWidget);
    expect(backend.to('GET', '/api/deals/7').length, greaterThanOrEqualTo(2));
  });

  testWidgets('mounted negotiation screen renders an accepted live offer', (
    tester,
  ) async {
    var accepted = false;
    final initial = _offer(
      id: 1,
      status: 'pending',
      allowedActions: const ['counter'],
      reward: 3000,
    );
    final updated = _offer(
      id: 2,
      status: 'accepted',
      allowedActions: const [],
      reward: 3200,
    );
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle(
        'GET',
        '/api/matches/77',
        (_) => FakeResponse(200, _matchWithOffer(accepted ? updated : initial)),
      )
      ..handle(
        'GET',
        '/api/matches/77/offers',
        (_) => FakeResponse(200, accepted ? [updated, initial] : [initial]),
      );
    final container = containerFor(backend);

    await pumpApp(
      tester,
      const NegotiationScreen(matchId: 77),
      container: container,
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(NegotiationScreen)));
    expect(find.text(l.offerCounter), findsOneWidget);

    accepted = true;
    await _emit(
      tester,
      container,
      type: 'offer.accepted',
      eventId: 'offer-accepted-2',
      data: {'match_id': 77, 'deal_id': 7},
    );

    expect(find.text(l.offerStatusAccepted), findsWidgets);
    expect(find.text(l.offerCounter), findsNothing);
    expect(
      backend.to('GET', '/api/matches/77/offers').length,
      greaterThanOrEqualTo(2),
    );
  });

  testWidgets('payment screen refreshes from captured and failed events', (
    tester,
  ) async {
    var paymentStatus = 'pending';
    var attemptStatus = 'processing';
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(200, _senderDeal(status: 'funded')),
      )
      ..on(
        'GET',
        '/api/payments/providers',
        const FakeResponse(200, {
          'timing_mode': 'after_acceptance',
          'canonical_currency': 'EUR',
          'providers': [
            {
              'provider': 'stripe',
              'available': true,
              'settlement_currency': 'EUR',
              'supports_guest_payment': false,
              'unavailable_reason': '',
              'settlement_amount_eur_cents': 3500,
            },
          ],
        }),
      )
      ..handle(
        'GET',
        '/api/deals/7/payment',
        (_) => FakeResponse(
          200,
          _payment(orderStatus: paymentStatus, attemptStatus: attemptStatus),
        ),
      );
    final container = containerFor(backend);

    await pumpApp(
      tester,
      const DealPaymentScreen(dealId: 7),
      container: container,
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DealPaymentScreen)));
    expect(find.text(l.paymentChooseProvider), findsOneWidget);

    paymentStatus = 'paid';
    attemptStatus = 'succeeded';
    await _emit(
      tester,
      container,
      type: 'payment.captured',
      eventId: 'payment-captured-7',
      data: {'deal_id': 7},
    );
    // J7D: the balance settled while the Sender watched.
    expect(find.text(l.guestPaidTitle), findsOneWidget);
  });

  testWidgets('payment screen refreshes to failed after a failed event', (
    tester,
  ) async {
    var attemptStatus = 'processing';
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(200, _senderDeal(status: 'funded')),
      )
      ..on(
        'GET',
        '/api/payments/providers',
        const FakeResponse(200, {
          'timing_mode': 'after_acceptance',
          'canonical_currency': 'EUR',
          'providers': <Object>[],
        }),
      )
      ..handle(
        'GET',
        '/api/deals/7/payment',
        (_) => FakeResponse(
          200,
          _payment(orderStatus: 'pending', attemptStatus: attemptStatus),
        ),
      );
    final container = containerFor(backend);

    await pumpApp(
      tester,
      const DealPaymentScreen(dealId: 7),
      container: container,
    );
    await tester.pumpAndSettle();
    attemptStatus = 'failed';
    await _emit(
      tester,
      container,
      type: 'payment.failed',
      eventId: 'payment-failed-7',
      data: {'deal_id': 7},
    );
    // The private payment provider was invalidated and re-read while the
    // mounted checkout section remains in its own confirmation lifecycle.
    expect(
      backend.to('GET', '/api/deals/7/payment').length,
      greaterThanOrEqualTo(2),
    );
  });

  testWidgets('mounted dispute detail refreshes to a resolved settlement', (
    tester,
  ) async {
    var resolved = false;
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle(
        'GET',
        '/api/disputes/9',
        (_) =>
            FakeResponse(200, _dispute(status: resolved ? 'resolved' : 'open')),
      );
    final container = containerFor(backend);

    await pumpApp(
      tester,
      const DisputeDetailScreen(disputeId: 9),
      container: container,
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DisputeDetailScreen)));
    expect(find.text(l.disputeStatusOpen), findsOneWidget);

    resolved = true;
    await _emit(
      tester,
      container,
      type: 'dispute.resolved',
      eventId: 'dispute-resolved-9',
      data: {'dispute_id': 9, 'deal_id': 7},
    );

    expect(find.text(l.disputeStatusResolved), findsOneWidget);
    expect(find.text(l.disputeResolutionRefunded), findsOneWidget);
    expect(
      backend.to('GET', '/api/disputes/9').length,
      greaterThanOrEqualTo(2),
    );
  });

  testWidgets('live code availability overrides an older device countdown', (
    tester,
  ) async {
    var available = false;
    final deviceFuture = DateTime.now()
        .add(const Duration(minutes: 15))
        .toUtc()
        .toIso8601String();
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('GET', '/api/deals/7', (_) {
        final deal = _senderDeal(
          status: 'picked_up',
          pickupConfirmedAt: '2026-08-30T10:00:00Z',
        );
        deal['handover'] = {
          'deal_status': 'picked_up',
          'pickup_confirmed_at': '2026-08-30T10:00:00Z',
          'delivery_code_available_at': deviceFuture,
          'in_delivery_code_buffer': !available,
          'can_reveal_delivery_code': available,
          'traveler_can_view_delivery_code': false,
          'can_submit_delivery_code': available,
          'pickup': {'exists': true, 'status': 'used'},
          'delivery': {
            'exists': true,
            'status': available ? 'active' : 'buffered',
          },
        };
        return FakeResponse(200, deal);
      });
    final container = containerFor(backend);
    await pumpApp(
      tester,
      const DeliveryScreen(dealId: 7),
      container: container,
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DeliveryScreen)));
    expect(find.text(l.deliveryCodeReadyTitle), findsNothing);
    available = true;
    await _emit(
      tester,
      container,
      type: 'handover.delivery_code_available',
      eventId: 'code-ready-7',
      data: {'deal_id': 7, 'match_id': 77},
    );
    expect(find.text(l.deliveryCodeReadyTitle), findsOneWidget);
    expect(find.text(l.deliveryCodeReveal), findsOneWidget);
  });
}
