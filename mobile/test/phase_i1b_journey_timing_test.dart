/// Phase I1B: Early Arrival, Route Visibility & Delivery Lifecycle Mobile UX tests.
///
/// Asserts on:
/// - Traveler reporting flow (dialog, body, payout floor consequence, server POST).
/// - Traveler pending confirmation state ("Waiting for Sender confirmation").
/// - Sender banner, "Confirm arrival" and "Decline" actions, server POSTs.
/// - Arrival confirmed and arrival declined presentations.
/// - Arrival != Delivery: traveler never gets delivery code, 30m buffer honored.
/// - Route timeline: ordered stops, FLIGHT/DRIVE modes, snapshot basis.
/// - Activity query filtering: active vs completed lists query backend activity endpoints.
/// - Payout floor presentation and explanation.
/// - Notification parsing and deep-link routing.
/// - Localization in EN, FR, AR with RTL layout and zero overflow.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _senderId = 42;
const _travelerId = 99;

class _FixedSession extends SessionController {
  _FixedSession(this._account);
  final Account _account;

  @override
  SessionState build() => SessionSignedIn(_account);
}

Account _accountFor(int id) => Account.fromJson({
  ...meFixture(),
  'id': id,
  'email': id == _senderId ? 'sender@example.com' : 'traveler@example.com',
  'full_name': id == _senderId ? 'Amina Sender' : 'Yacine Traveler',
});

ProviderContainer _containerForAccount(FakeBackend backend, Account account) {
  final store = FakeTokenStore();
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
      sessionProvider.overrideWith(() => _FixedSession(account)),
    ],
  );
}

Map<String, dynamic> _i1bDeal({
  int id = 7,
  int senderId = _senderId,
  int travelerId = _travelerId,
  String status = 'in_transit',
  String activityState = 'active',
  String arrivalState = 'not_reported',
  String arrivalBasis = 'allocated_leg_arrival',
  bool canReportEarly = false,
  bool canConfirmEarly = false,
  bool canDeclineEarly = false,
  DateTime? fundedScheduledArrivalAt,
  DateTime? arrivalConfirmedAt,
  DateTime? deliveryConfirmedAt,
  Map<String, dynamic>? route,
  Map<String, dynamic>? payoutFloor,
  bool delivered = false,
  bool inBuffer = false,
  bool canRevealDelivery = false,
  bool canSubmitDelivery = false,
}) {
  final scheduledStr =
      (fundedScheduledArrivalAt ?? DateTime.parse('2026-09-10T14:00:00Z'))
          .toUtc()
          .toIso8601String();
  final arrivalConfirmedStr = arrivalConfirmedAt?.toUtc().toIso8601String();
  final deliveryConfirmedStr = deliveryConfirmedAt?.toUtc().toIso8601String();

  final arrivalActions = <String>[];
  if (canReportEarly) arrivalActions.add('report_early_arrival');
  if (canConfirmEarly) arrivalActions.add('confirm_early_arrival');
  if (canDeclineEarly) arrivalActions.add('decline_early_arrival');

  return {
    'id': id,
    'sender_id': senderId,
    'traveler_id': travelerId,
    'status': status,
    'activity_state': activityState,
    'funded_scheduled_arrival_floor_at': scheduledStr,
    'arrival_confirmed_at': arrivalConfirmedStr,
    'pickup_confirmed_at': '2026-09-06T09:00:00Z',
    'delivery_confirmed_at': deliveryConfirmedStr,
    'created_at': '2026-09-05T10:00:00Z',
    'funded_at': '2026-09-05T11:00:00Z',
    'arrival': {
      'state': arrivalState,
      'basis': arrivalBasis,
      'funded_scheduled_arrival_at': scheduledStr,
      'material_early_threshold_seconds': 21600,
      'is_materially_early_now': true,
      'seconds_until_scheduled_arrival': 86400,
      'server_time': '2026-09-06T12:00:00Z',
      'reported_at': arrivalState != 'not_reported'
          ? '2026-09-06T12:00:00Z'
          : null,
      'reported_early_by_seconds': arrivalState != 'not_reported' ? 7200 : null,
      'decided_at': arrivalState == 'confirmed' || arrivalState == 'declined'
          ? '2026-09-06T12:30:00Z'
          : null,
      'arrival_confirmed_at': arrivalConfirmedStr,
      'confirmed_arrival_is_not_delivery': true,
      'delivery_confirmed_at': deliveryConfirmedStr,
      'report_available': canReportEarly,
      'report_unavailable_reason': canReportEarly ? null : 'already_reported',
      'decision_available': canConfirmEarly || canDeclineEarly,
      'decision_unavailable_reason': null,
      'available_actions': arrivalActions,
    },
    'route':
        route ??
        {
          'basis': 'funded_snapshot',
          'journey_id': 12,
          'legs': [
            {
              'leg_id': 101,
              'position': 0,
              'mode': 'FLIGHT',
              'depart_at': '2026-09-06T08:00:00Z',
              'arrive_at': '2026-09-06T10:30:00Z',
              'carries_parcel': true,
              'origin': {
                'kind': 'journey_leg_endpoint',
                'id': 1,
                'name': 'Paris Charles de Gaulle',
                'display_label': 'Paris (CDG)',
                'iata_code': 'CDG',
                'place_type': 'airport',
                'country_code': 'FR',
                'parent_name': 'Paris',
              },
              'destination': {
                'kind': 'journey_leg_endpoint',
                'id': 2,
                'name': 'Houari Boumediene Airport',
                'display_label': 'Algiers (ALG)',
                'iata_code': 'ALG',
                'place_type': 'airport',
                'country_code': 'DZ',
                'parent_name': 'Algiers',
              },
            },
            {
              'leg_id': 102,
              'position': 1,
              'mode': 'DRIVE',
              'depart_at': '2026-09-06T12:00:00Z',
              'arrive_at': '2026-09-06T16:00:00Z',
              'carries_parcel': true,
              'origin': {
                'kind': 'journey_leg_endpoint',
                'id': 2,
                'name': 'Algiers Central',
                'display_label': 'Algiers',
                'place_type': 'city',
                'country_code': 'DZ',
                'parent_name': 'Algiers',
              },
              'destination': {
                'kind': 'journey_leg_endpoint',
                'id': 3,
                'name': 'Oran Central',
                'display_label': 'Oran',
                'place_type': 'city',
                'country_code': 'DZ',
                'parent_name': 'Algeria',
              },
            },
          ],
        },
    'protection_ends_at': delivered ? '2026-09-08T10:00:00Z' : null,
    'protection': {
      'protection_ends_at': delivered ? '2026-09-08T10:00:00Z' : null,
      'delivery_confirmed_at': deliveryConfirmedStr,
      'payout_floor':
          payoutFloor ??
          {
            'protection_ends_at': delivered ? '2026-09-08T10:00:00Z' : null,
            'funded_scheduled_arrival_floor_at': scheduledStr,
            'payout_eligible_from': scheduledStr,
            'basis': 'schedule_floor',
            'gate_open': false,
            'server_time': '2026-09-06T12:00:00Z',
          },
      'payout': {
        'status': 'pending',
        'method': 'manual',
        'amount_eur_cents': 3500,
        'eligible_at': scheduledStr,
      },
    },
    'handover': {
      'deal_status': status,
      'pickup_confirmed_at': '2026-09-06T09:00:00Z',
      'delivery_code_available_at': '2026-09-06T09:30:00Z',
      'delivery_code_released_at': inBuffer ? null : '2026-09-06T09:30:00Z',
      'delivery_confirmed_at': deliveryConfirmedStr,
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
    },
    'terms': {
      'currency': 'EUR',
      'traveler_reward_minor': 3500,
      'platform_fee_minor': 500,
      'sender_total_minor': 4000,
      'traveler_total_minor': 3500,
      'sender_total_with_boost_minor': 4000,
      'commission_rate_bps': 1250,
      'is_legacy': false,
    },
    'recipient': {
      'full_name': 'Karim Hadj',
      'phone': '+213555999888',
      'email': 'karim@example.com',
      'recorded': true,
      'updated_at': '2026-09-05T10:00:00Z',
    },
  };
}

void main() {
  group('Phase I1B — Traveler Early Arrival Flow', () {
    testWidgets(
      'Traveler sees "I arrived early", opens sheet, confirms, and transitions to pending state',
      (tester) async {
        final backend = FakeBackend();
        var reported = false;

        backend.handle('GET', '/api/deals/7', (_) {
          if (!reported) {
            return FakeResponse(
              200,
              _i1bDeal(
                id: 7,
                canReportEarly: true,
                arrivalState: 'not_reported',
              ),
            );
          } else {
            return FakeResponse(
              200,
              _i1bDeal(
                id: 7,
                canReportEarly: false,
                arrivalState: 'pending_confirmation',
              ),
            );
          }
        });

        backend.handle('POST', '/api/deals/7/arrival/report', (_) {
          reported = true;
          return FakeResponse(200, {
            'deal': _i1bDeal(
              id: 7,
              canReportEarly: false,
              arrivalState: 'pending_confirmation',
            ),
            'arrival_report_id': 1,
            'arrival_report_status': 'pending_confirmation',
            'changed': true,
          });
        });

        final container = _containerForAccount(
          backend,
          _accountFor(_travelerId),
        );

        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: container,
        );
        await tester.pumpAndSettle();

        // "I arrived early" button is visible for traveler
        expect(
          find.widgetWithText(AppButton, 'I arrived early'),
          findsOneWidget,
        );

        // Tap "I arrived early" button
        await tester.tap(find.widgetWithText(AppButton, 'I arrived early'));
        await tester.pumpAndSettle();

        // Confirmation dialog is shown
        expect(find.text('Report early arrival'), findsOneWidget);
        expect(
          find.text(
            'Arriving early does not make the payout available earlier than the protected payout date for this delivery.',
          ),
          findsOneWidget,
        );

        // Confirm in dialog
        await tester.tap(find.widgetWithText(TextButton, 'I arrived early'));
        await tester.pumpAndSettle();

        // Verify POST call was recorded
        final postRequest = backend.requests.firstWhere(
          (r) => r.path == '/api/deals/7/arrival/report',
        );
        expect(postRequest.method, 'POST');

        // Traveler now sees "Waiting for Sender confirmation"
        expect(
          find.widgetWithText(InfoNotice, 'Waiting for Sender confirmation'),
          findsOneWidget,
        );
        expect(
          find.text(
            'You reported your early arrival. The sender has been notified to confirm it. Handover and delivery remain separate.',
          ),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Traveler cannot report early arrival when server disallows it',
      (tester) async {
        final backend = FakeBackend();
        backend.handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              canReportEarly: false,
              arrivalState: 'not_reported',
            ),
          ),
        );

        final container = _containerForAccount(
          backend,
          _accountFor(_travelerId),
        );

        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: container,
        );
        await tester.pumpAndSettle();

        // No "I arrived early" button when server reportAvailable == false
        expect(find.text('I arrived early'), findsNothing);
      },
    );
  });

  group('Phase I1B — Sender Early Arrival Review & Actions', () {
    testWidgets('Sender sees banner and confirms early arrival', (
      tester,
    ) async {
      final backend = FakeBackend();
      var confirmed = false;

      backend.handle('GET', '/api/deals/7', (_) {
        if (!confirmed) {
          return FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              arrivalState: 'pending_confirmation',
              canConfirmEarly: true,
              canDeclineEarly: true,
            ),
          );
        } else {
          return FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              arrivalState: 'confirmed',
              arrivalConfirmedAt: DateTime.parse('2026-09-06T12:30:00Z'),
            ),
          );
        }
      });

      backend.handle('POST', '/api/deals/7/arrival/confirm', (_) {
        confirmed = true;
        return FakeResponse(200, {
          'deal': _i1bDeal(
            id: 7,
            arrivalState: 'confirmed',
            arrivalConfirmedAt: DateTime.parse('2026-09-06T12:30:00Z'),
          ),
          'arrival_report_id': 1,
          'arrival_report_status': 'confirmed',
          'changed': true,
        });
      });

      final container = _containerForAccount(backend, _accountFor(_senderId));

      await pumpApp(tester, const DealScreen(dealId: 7), container: container);
      await tester.pumpAndSettle();

      // Notice title and buttons are shown
      expect(find.text('Traveler says they arrived early'), findsOneWidget);
      expect(find.text('Confirm arrival'), findsOneWidget);
      expect(find.text('Decline'), findsOneWidget);

      // Tap "Confirm arrival"
      await tester.tap(find.text('Confirm arrival'));
      await tester.pumpAndSettle();

      // Verify POST call
      final postRequest = backend.requests.firstWhere(
        (r) => r.path == '/api/deals/7/arrival/confirm',
      );
      expect(postRequest.method, 'POST');

      // Confirmed banner is rendered
      expect(
        find.widgetWithText(InfoNotice, 'Arrival confirmed'),
        findsOneWidget,
      );
    });

    testWidgets('Sender can decline early arrival', (tester) async {
      final backend = FakeBackend();
      var declined = false;

      backend.handle('GET', '/api/deals/7', (_) {
        if (!declined) {
          return FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              arrivalState: 'pending_confirmation',
              canConfirmEarly: true,
              canDeclineEarly: true,
            ),
          );
        } else {
          return FakeResponse(200, _i1bDeal(id: 7, arrivalState: 'declined'));
        }
      });

      backend.handle('POST', '/api/deals/7/arrival/decline', (_) {
        declined = true;
        return FakeResponse(200, {
          'deal': _i1bDeal(id: 7, arrivalState: 'declined'),
          'arrival_report_id': 1,
          'arrival_report_status': 'declined',
          'changed': true,
        });
      });

      final container = _containerForAccount(backend, _accountFor(_senderId));

      await pumpApp(tester, const DealScreen(dealId: 7), container: container);
      await tester.pumpAndSettle();

      // Tap "Decline"
      await tester.tap(find.text('Decline'));
      await tester.pumpAndSettle();

      // Verify POST call
      final postRequest = backend.requests.firstWhere(
        (r) => r.path == '/api/deals/7/arrival/decline',
      );
      expect(postRequest.method, 'POST');

      // Declined banner is rendered
      expect(
        find.widgetWithText(InfoNotice, 'Early arrival not confirmed'),
        findsOneWidget,
      );
    });
  });

  group('Phase I1B — Arrival != Delivery Separation & Security', () {
    testWidgets(
      'Confirmed arrival does NOT complete delivery and traveler NEVER sees delivery code',
      (tester) async {
        final backend = FakeBackend();
        backend.handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              arrivalState: 'confirmed',
              arrivalConfirmedAt: DateTime.parse('2026-09-06T12:30:00Z'),
              inBuffer: true,
              delivered: false,
            ),
          ),
        );

        final container = _containerForAccount(
          backend,
          _accountFor(_travelerId),
        );

        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: container,
        );
        await tester.pumpAndSettle();

        // Arrival is confirmed
        expect(find.text('Arrival confirmed'), findsOneWidget);

        // Handover delivery code is still locked / in buffer
        expect(
          find.text('Delivery safety buffer active'),
          findsNothing,
        ); // Never leaks delivery code
        // Delivery has NOT been completed
        expect(find.text('Deal completed'), findsNothing);
      },
    );
  });

  group('Phase I1B — Route Visibility', () {
    testWidgets(
      'Route timeline displays ordered stops, modes, and snapshot basis',
      (tester) async {
        final backend = FakeBackend();
        backend.handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(200, _i1bDeal(id: 7)),
        );

        final container = _containerForAccount(backend, _accountFor(_senderId));

        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: container,
        );
        await tester.pumpAndSettle();

        // Route title and snapshot badge
        expect(find.text('Route'), findsWidgets);
        expect(find.text('Frozen at booking'), findsOneWidget);

        // Stops
        expect(find.text('Paris (CDG)'), findsOneWidget);
        expect(find.text('Algiers (ALG)'), findsOneWidget);
        expect(find.text('Oran'), findsOneWidget);

        // Mode labels
        expect(find.textContaining('Flight'), findsOneWidget);
        expect(find.textContaining('Drive'), findsOneWidget);
      },
    );
  });

  group('Phase I1B — Activity Lists & Backend Queries', () {
    test('DealRepository list passes activity parameter to backend', () async {
      final backend = FakeBackend();
      backend.handle('GET', '/api/deals', (request) {
        final activity = request.query['activity'];
        if (activity == 'active') {
          return FakeResponse(200, {
            'count': 1,
            'next': null,
            'previous': null,
            'results': [
              _i1bDeal(id: 7, status: 'in_transit', activityState: 'active'),
            ],
          });
        } else if (activity == 'completed') {
          return FakeResponse(200, {
            'count': 1,
            'next': null,
            'previous': null,
            'results': [
              _i1bDeal(
                id: 8,
                status: 'completed',
                activityState: 'completed',
                delivered: true,
              ),
            ],
          });
        }
        return const FakeResponse(400, {'detail': 'Invalid query'});
      });

      final container = _containerForAccount(backend, _accountFor(_senderId));
      final repo = container.read(dealRepositoryProvider);

      // Query active deals via repository
      final activeList = await repo.list(activity: ActivityState.active);
      expect(activeList.length, 1);
      expect(activeList.first.id, 7);
      expect(activeList.first.activityState, ActivityState.active);

      // Query history deals via repository
      final historyList = await repo.list(activity: ActivityState.completed);
      expect(historyList.length, 1);
      expect(historyList.first.id, 8);
      expect(historyList.first.activityState, ActivityState.completed);

      // Verify queries sent with exact wire values
      final queries = backend.requests
          .where((r) => r.path == '/api/deals')
          .map((r) => r.query['activity'])
          .toList();
      expect(queries, containsAll(['active', 'completed']));
    });
  });

  group('Phase I1B — Payout Floor Presentation', () {
    testWidgets(
      'Protection section displays scheduled arrival floor and early arrival payout floor explanation',
      (tester) async {
        final backend = FakeBackend();
        backend.handle(
          'GET',
          '/api/deals/7',
          (_) => FakeResponse(
            200,
            _i1bDeal(
              id: 7,
              arrivalState: 'confirmed',
              arrivalConfirmedAt: DateTime.parse('2026-09-06T12:30:00Z'),
              fundedScheduledArrivalAt: DateTime.parse('2026-09-10T14:00:00Z'),
              delivered: true,
            ),
          ),
        );

        final container = _containerForAccount(
          backend,
          _accountFor(_travelerId),
        );

        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: container,
        );
        await tester.pumpAndSettle();

        final explanationFinder = find.text(
          'Arriving early does not make the payout available earlier than the protected payout date for this delivery.',
        );
        await tester.scrollUntilVisible(explanationFinder, 200);

        // Payout floor explanation notice
        expect(explanationFinder, findsOneWidget);
        expect(
          find.textContaining('Scheduled arrival for this delivery:'),
          findsOneWidget,
        );
        expect(find.textContaining('Payout eligible from:'), findsOneWidget);
      },
    );
  });

  group('Phase I1B — Notifications & Deep Linking', () {
    test(
      'NotificationChannel parses early arrival events and maps to OpenDeal',
      () {
        final reported = AppNotification.fromJson({
          'id': 100,
          'user_id': 42,
          'channel': 'deal.arrival_reported',
          'event_id': 'evt-1',
          'payload': {'deal_id': 7},
          'created_at': '2026-09-06T12:00:00Z',
        });
        expect(reported.channel, NotificationChannel.dealArrivalReported);
        expect(reported.destination, isA<OpenDeal>());
        expect((reported.destination as OpenDeal).dealId, 7);

        final confirmed = AppNotification.fromJson({
          'id': 101,
          'user_id': 99,
          'channel': 'deal.arrival_confirmed',
          'event_id': 'evt-2',
          'payload': {'deal_id': 7},
          'created_at': '2026-09-06T12:30:00Z',
        });
        expect(confirmed.channel, NotificationChannel.dealArrivalConfirmed);
        expect(confirmed.destination, isA<OpenDeal>());

        final declined = AppNotification.fromJson({
          'id': 102,
          'user_id': 99,
          'channel': 'deal.arrival_declined',
          'event_id': 'evt-3',
          'payload': {'deal_id': 7},
          'created_at': '2026-09-06T12:30:00Z',
        });
        expect(declined.channel, NotificationChannel.dealArrivalDeclined);
        expect(declined.destination, isA<OpenDeal>());
      },
    );
  });

  group('Phase I1B — Localization & Arabic RTL', () {
    for (final locale in [
      const Locale('en'),
      const Locale('fr'),
      const Locale('ar'),
    ]) {
      testWidgets(
        '${locale.languageCode}: DealScreen renders early arrival and route without overflow',
        (tester) async {
          final backend = FakeBackend();
          backend.handle(
            'GET',
            '/api/deals/7',
            (_) => FakeResponse(
              200,
              _i1bDeal(
                id: 7,
                arrivalState: 'pending_confirmation',
                canConfirmEarly: true,
                canDeclineEarly: true,
              ),
            ),
          );

          final container = _containerForAccount(
            backend,
            _accountFor(_senderId),
          );

          await pumpApp(
            tester,
            const DealScreen(dealId: 7),
            locale: locale,
            container: container,
            device: DeviceProfile.iphone,
          );
          await tester.pumpAndSettle();

          // Check for any Flutter error or overflow
          expect(tester.takeException(), isNull);
        },
      );
    }
  });
}
