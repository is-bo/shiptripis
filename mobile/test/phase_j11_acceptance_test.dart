/// Phase J1.1 — the regressions the owner hit on the installed app.
///
/// Each group pins one reported symptom to the server fact that settles it, so
/// a future change that reintroduces a client-side inference fails here rather
/// than on a phone.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/domain/rating.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

/// A sender's delivery request as `GET /api/parcels` returns it.
///
/// `status` deliberately stays at `matched` even for a finished delivery: the
/// backend never advances a ParcelRequest past that, which is exactly why the
/// client cannot use it to decide whether a shipment is still running.
Map<String, dynamic> requestFixture({
  int id = 300,
  String status = 'matched',
  String title = 'Winter coat',
}) => {
  'id': id,
  'sender_id': 42,
  'kind': 'delivery',
  'status': status,
  'title': title,
  'schema_version': 2,
  'weight_kg': '2.00',
  'item_type': 'clothing',
  'category': 'clothing',
  'description': 'A coat.',
  'media': <Object>[],
};

/// A deal list row, carrying the server-derived activity state and the id of
/// the request it settles.
Map<String, dynamic> dealRowFixture({
  required int id,
  required String activityState,
  required int deliveryRequestId,
  String status = 'funded',
}) => {
  'id': id,
  'sender_id': 42,
  'traveler_id': 99,
  'delivery_request_id': deliveryRequestId,
  'status': status,
  'activity_state': activityState,
  'is_legacy': false,
  'leg_allocations': <Object>[],
  'funded_at': '2026-08-20T10:00:00Z',
};

Map<String, dynamic> ratingsFixture({
  required String state,
  bool canRate = false,
  bool submitted = false,
  bool counterpartySubmitted = false,
  bool bothSidesSubmitted = false,
  bool windowOpen = true,
  List<Map<String, dynamic>> ratings = const [],
}) => {
  'deal_id': 7,
  'state': state,
  'viewer_role': 'sender',
  'window_open': windowOpen,
  'can_rate': canRate,
  'submitted': submitted,
  'counterparty_submitted': counterpartySubmitted,
  'both_sides_submitted': bothSidesSubmitted,
  'allowed_tags': <String>['on_time'],
  'max_comment_length': 500,
  'ratings': ratings,
};

void main() {
  group('Home no longer keeps finished shipments', () {
    testWidgets('a request whose deal is completed leaves the sender list', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/parcels',
          FakeResponse(200, [
            requestFixture(id: 300, title: 'Running shipment'),
            requestFixture(id: 301, title: 'Finished shipment'),
          ]),
        )
        ..handle('GET', '/api/deals', (request) {
          final activity = request.query['activity'];
          final rows = [
            dealRowFixture(
              id: 10,
              activityState: 'active',
              deliveryRequestId: 300,
            ),
            dealRowFixture(
              id: 11,
              activityState: 'completed',
              deliveryRequestId: 301,
              status: 'completed',
            ),
          ];
          return FakeResponse(
            200,
            activity == null
                ? rows
                : rows.where((r) => r['activity_state'] == activity).toList(),
          );
        });

      final container = containerFor(backend);
      await pumpApp(
        tester,
        Consumer(
          builder: (context, ref, _) {
            final requests = ref.watch(myRequestsProvider).value;
            final settled = ref.watch(settledRequestIdsProvider);
            if (requests == null) return const Text('loading');
            final live = requests
                .where((r) => !r.status.isFinished && !settled.contains(r.id))
                .map((r) => r.title)
                .join(',');
            return Text('live:$live');
          },
        ),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('live:Running shipment'), findsOneWidget);
    });

    testWidgets('History asks the server for cancelled deals too', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle(
          'GET',
          '/api/deals',
          (_) => FakeResponse(200, <Map<String, dynamic>>[]),
        );

      final container = containerFor(backend);
      await pumpApp(
        tester,
        Consumer(
          builder: (context, ref, _) {
            ref.watch(historyDealsProvider);
            return const SizedBox();
          },
        ),
        container: container,
      );
      await tester.pumpAndSettle();

      final activities = backend
          .to('GET', '/api/deals')
          .map((r) => r.query['activity'])
          .toSet();
      expect(activities, containsAll(<String>['completed', 'cancelled']));
    });
  });

  group('Rating state comes from the server', () {
    test('every server state parses, and an older payload falls back', () {
      RatingState stateFor(String? raw) => RatingState.maybe({
        ...ratingsFixture(state: 'available'),
        'state': ?raw,
      })!;

      expect(stateFor('available').state, RatingLifecycleState.available);
      expect(
        stateFor('submitted_waiting').state,
        RatingLifecycleState.submittedWaiting,
      );
      expect(stateFor('revealed').state, RatingLifecycleState.revealed);
      expect(stateFor('expired').state, RatingLifecycleState.expired);
      expect(stateFor('unavailable').state, RatingLifecycleState.unavailable);
      expect(stateFor('something_new').state, RatingLifecycleState.unknown);

      // A deployment that predates the field must not lose the section.
      final legacy = RatingState.maybe(
        Map<String, dynamic>.from(
          ratingsFixture(state: 'available', canRate: true),
        )..remove('state'),
      )!;
      expect(legacy.state, RatingLifecycleState.unknown);
      expect(legacy.isActionable, isTrue);
    });

    test('only a revealed state exposes the counterpart rating', () {
      Map<String, dynamic> theirRating({required bool isRevealed}) => {
        'id': 5,
        'deal_id': 7,
        'score': 4,
        'tags': <String>['on_time'],
        'comment': 'Smooth handover.',
        'is_revealed': isRevealed,
        'is_mine': false,
      };

      final waiting = RatingState.maybe(
        ratingsFixture(
          state: 'submitted_waiting',
          submitted: true,
          ratings: [theirRating(isRevealed: true)],
        ),
      )!;
      expect(waiting.isRevealed, isFalse);
      expect(waiting.revealedCounterpartRating, isNull);

      final revealed = RatingState.maybe(
        ratingsFixture(
          state: 'revealed',
          submitted: true,
          counterpartySubmitted: true,
          bothSidesSubmitted: true,
          ratings: [theirRating(isRevealed: true)],
        ),
      )!;
      expect(revealed.revealedCounterpartRating?.score, 4);

      // Revealed by state but not by the row itself: still not shown.
      final inconsistent = RatingState.maybe(
        ratingsFixture(
          state: 'revealed',
          submitted: true,
          ratings: [theirRating(isRevealed: false)],
        ),
      )!;
      expect(inconsistent.revealedCounterpartRating, isNull);
    });

    test('a submitted or expired rating is never actionable', () {
      for (final state in ['submitted_waiting', 'revealed', 'expired']) {
        final ratings = RatingState.maybe(
          ratingsFixture(state: state, submitted: state != 'expired'),
        )!;
        expect(
          ratings.isActionable,
          isFalse,
          reason: '$state must not invite another rating',
        );
      }
      expect(
        RatingState.maybe(
          ratingsFixture(state: 'available', canRate: true),
        )!.isActionable,
        isTrue,
      );
    });
  });

  group('Deal screen', () {
    Future<void> pumpDeal(
      WidgetTester tester, {
      required Map<String, dynamic> deal,
    }) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('GET', '/api/deals/7', FakeResponse(200, deal));
      final container = containerFor(backend);
      await pumpApp(
        tester,
        const DealScreen(dealId: 7),
        container: container,
        // The route, dispute and rating sections sit far down one ListView.
        // A tall viewport builds them all rather than making every assertion
        // depend on a scroll that could itself be what broke.
        device: const DeviceProfile(name: 'tall', size: Size(411, 4000)),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('a funded delivery with no recorded route says so', (
      tester,
    ) async {
      await pumpDeal(
        tester,
        deal: {
          ...dealFixture(status: 'completed'),
          'activity_state': 'completed',
          'route': null,
          'available_actions': <String>[],
        },
      );

      expect(
        find.text('The travel route was not recorded for this delivery.'),
        findsOneWidget,
      );
    });

    testWidgets('an unfunded delivery says the route arrives with funding', (
      tester,
    ) async {
      final deal =
          Map<String, dynamic>.from(dealFixture(status: 'payment_required'))
            ..['funded_at'] = null
            ..['route'] = null
            ..['available_actions'] = <String>[];
      await pumpDeal(tester, deal: deal);

      expect(
        find.text('The travel route appears here once the delivery is funded.'),
        findsOneWidget,
      );
    });

    testWidgets('no dispute action when the server withholds it', (
      tester,
    ) async {
      await pumpDeal(
        tester,
        deal: {
          ...dealFixture(status: 'protection_window'),
          'available_actions': <String>[],
        },
      );
      expect(find.text('Open a dispute'), findsNothing);
    });

    testWidgets('the dispute action appears when the server offers it', (
      tester,
    ) async {
      await pumpDeal(
        tester,
        deal: {
          ...dealFixture(status: 'protection_window'),
          'available_actions': <String>['open_dispute'],
        },
      );
      expect(find.text('Open a dispute'), findsOneWidget);
    });

    testWidgets('a rated delivery stops asking for a rating', (tester) async {
      await pumpDeal(
        tester,
        deal: {
          ...dealFixture(status: 'completed'),
          'available_actions': <String>[],
          'ratings': ratingsFixture(
            state: 'submitted_waiting',
            submitted: true,
          ),
        },
      );

      expect(find.text('How did it go?'), findsNothing);
      expect(find.text('Rating saved'), findsOneWidget);
      expect(find.text('Rate'), findsNothing);
    });
  });

  group('Live updates', () {
    test('the arrival channels are no longer dropped', () {
      for (final type in [
        'deal.arrival_reported',
        'deal.arrival_confirmed',
        'deal.arrival_declined',
      ]) {
        final resources = resourcesForLiveEvent(type, {'deal_id': 7});
        expect(
          resources,
          contains(const LiveResource.deals()),
          reason: '$type must refresh the deal lists',
        );
        expect(resources, contains(const LiveResource.deal(7)));
      }
    });
  });

  group('Notification badge', () {
    testWidgets('counts active notifications, not unread ones', (tester) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/notifications/unread-count',
          // A read action that still needs doing keeps counting; an unread one
          // whose action is resolved does not.
          FakeResponse(200, {'unread': 3, 'active': 3, 'unread_active': 1}),
        );

      final container = containerFor(backend);
      await pumpApp(
        tester,
        Consumer(
          builder: (context, ref, _) {
            final active = ref.watch(unreadNotificationsProvider).value;
            final unreadActive = ref
                .watch(unreadActiveNotificationsProvider)
                .value;
            return Text('$active/$unreadActive');
          },
        ),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('3/1'), findsOneWidget);
    });
  });

  group('Payout failures say what happened', () {
    // Reproduced live against a real backend: tapping "Set up EUR payouts"
    // returned 409 stripe_connect_unavailable and the app showed a red
    // snackbar containing the single word "Refresh" — the same message every
    // other payout refusal produced, and the owner's reported symptom.
    testWidgets('a payout refusal is no longer the bare word "Refresh"', (
      tester,
    ) async {
      const codes = <String, String>{
        'stripe_connect_unavailable':
            'EUR payout setup is temporarily '
            'unavailable. Your details are unchanged — please try again '
            'shortly.',
        'payout_country_unsupported':
            'EUR payouts are not available in that '
            'country yet. Choose another country, or use DZD payouts.',
        'payout_profile_invalid':
            'Your payout details changed while you were '
            'on this page. Pull down to refresh, then try again.',
        'payout_setup_invalid':
            'That payout setup could not be completed. '
            'Check the details and try again.',
        'payout_evidence_unavailable':
            'The uploaded document is no longer '
            'available. Please upload the crossed cheque again.',
        'stripe_connect_provider_error':
            'Stripe could not complete the '
            'request. Nothing was changed; please try again shortly.',
      };

      for (final entry in codes.entries) {
        late String rendered;
        await pumpApp(
          tester,
          Builder(
            builder: (context) {
              rendered = staleMessage(context, ApiErrorCode(entry.key));
              return const SizedBox();
            },
          ),
        );
        expect(
          rendered,
          entry.value,
          reason: '${entry.key} must explain itself',
        );
        expect(rendered, isNot('Refresh'));
      }
    });
  });
}
