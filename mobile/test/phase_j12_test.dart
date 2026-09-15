/// Phase J1.2 — route projection, catch-up traffic and payout review state.
///
/// Each group pins one J1.2 finding to the smallest fact that settles it: the
/// wire shape the server actually sends, the number of reads one foreground
/// causes, and the reviewer decision a Traveler is shown.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/env/app_config.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/domain/discovery.dart';
import 'package:shiptrip/domain/transport_mode.dart';
import 'package:shiptrip/features/profile/payout_methods_screen.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

/// One covered leg exactly as `GET /api/matches/compatible-journeys` sends it
/// for a canonical (V1) journey.
///
/// The legacy `origin`/`destination` keys are present and **null** — that is
/// the live contract, verified against the real projection, and reading only
/// those keys is what made the route line render blank stops.
Map<String, dynamic> canonicalLeg({
  int id = 1,
  int position = 0,
  String mode = 'FLIGHT',
  String originName = 'Paris CDG',
  String originIata = 'CDG',
  String destinationName = 'Houari Boumediene',
  String? destinationIata = 'ALG',
}) => {
  'journey_leg_id': id,
  'position': position,
  'mode': mode,
  'origin': null,
  'destination': null,
  'origin_place': {
    'id': 4,
    'name': originName,
    'display_label': originName,
    'place_type': 'airport',
    'country_code': 'FR',
    'iata_code': originIata,
    'matching_locality_id': 1,
  },
  'destination_place': {
    'id': 5,
    'name': destinationName,
    'display_label': destinationName,
    'place_type': destinationIata == null ? 'locality' : 'airport',
    'country_code': 'DZ',
    'iata_code': destinationIata,
    'matching_locality_id': 2,
  },
  'depart_at': '2026-09-17T11:00:00Z',
  'arrive_at': '2026-09-17T14:00:00Z',
};

/// `GET /api/payouts/methods` with the DZD rail in one review state.
Map<String, dynamic> methodsFixture({required String reviewState}) => {
  'contract_version': 'h6a_v1',
  'preference': 'dzd_only',
  'preference_required': false,
  'revisions': {'EUR': 0, 'DZD': 2},
  'available_actions': <String>['update_preference'],
  'eur': {
    'state': 'not_configured',
    'ready': false,
    'supported': true,
    'country': null,
    'available_actions': <String>[],
    'supported_countries': <String>['FR'],
  },
  'dzd': {
    'state': 'needs_attention',
    'ready': false,
    'supported': true,
    'country': 'DZ',
    'blocking_reason': 'payout_profile_needs_attention',
    'available_actions': <String>['replace_dzd_profile'],
    'replacement_scope': 'future_payouts_only',
    'profile': {
      'reference': 'aaaaaaaa-0000-0000-0000-000000000000',
      'review_state': reviewState,
      'ccp_last_four': '4321',
      'rip_last_four': '9876',
      'submitted_at': '2026-09-10T08:00:00Z',
    },
  },
};

void main() {
  group('canonical route projection', () {
    test('a covered leg resolves its endpoints from the place keys', () {
      final leg = CoveredLeg.fromJson(canonicalLeg());

      // Before J1.2 both of these were null and every route stop rendered as
      // an empty label with a dot and nothing beside it.
      expect(leg.origin, isNotNull);
      expect(leg.destination, isNotNull);
      expect(leg.origin!.coarseLabel, 'Paris CDG');
      expect(leg.destination!.coarseLabel, 'Houari Boumediene');
      expect(leg.origin!.airportIata, 'CDG');
      expect(leg.origin!.canonicalPlaceId, 4);
      expect(leg.mode, TransportMode.flight);

      // A place summary carries no coordinates, so nothing may read as exact.
      expect(leg.origin!.isExact, isFalse);
      expect(leg.origin!.point, isNull);
    });

    test('the legacy location shape still wins where it is present', () {
      final leg = CoveredLeg.fromJson({
        ...canonicalLeg(),
        'origin': {
          'id': 77,
          'kind': 'city',
          'public_label': 'Algiers, DZ',
          'city': 'Algiers',
          'country_code': 'DZ',
          'precision': 'city',
        },
      });

      expect(leg.origin!.id, 77);
      expect(leg.origin!.coarseLabel, 'Algiers, DZ');
    });

    test('a candidate journey falls back to its canonical endpoints', () {
      final journey = CandidateJourney.maybe({
        'id': 12,
        'traveler_id': 99,
        'start_location': null,
        'destination_location': null,
        'start_place': {
          'id': 4,
          'name': 'Paris CDG',
          'display_label': 'Paris CDG',
          'place_type': 'airport',
          'country_code': 'FR',
          'iata_code': 'CDG',
        },
        'destination_place': {
          'id': 3,
          'name': 'Jijel',
          'display_label': 'Jijel',
          'place_type': 'locality',
          'country_code': 'DZ',
          'iata_code': null,
        },
        'first_departure': '2026-09-17T11:00:00Z',
        'start_leg_id': 1,
        'end_leg_id': 2,
        'covered_legs': [canonicalLeg()],
      })!;

      expect(journey.startLocation!.coarseLabel, 'Paris CDG');
      expect(journey.destinationLocation!.coarseLabel, 'Jijel');
      expect(journey.coveredLegs.single.origin!.coarseLabel, 'Paris CDG');
    });

    test('a candidate request falls back to its canonical endpoints', () {
      final request = CandidateRequest.maybe({
        'id': 5,
        'sender_id': 42,
        'pickup': null,
        'delivery': null,
        'pickup_place': {
          'id': 1,
          'name': 'Paris',
          'display_label': 'Paris',
          'place_type': 'locality',
          'country_code': 'FR',
          'iata_code': null,
        },
        'delivery_place': {
          'id': 3,
          'name': 'Jijel',
          'display_label': 'Jijel',
          'place_type': 'locality',
          'country_code': 'DZ',
          'iata_code': null,
        },
        'actual_weight_kg': '2.00',
      })!;

      expect(request.pickup!.coarseLabel, 'Paris');
      expect(request.delivery!.coarseLabel, 'Jijel');
    });

    test('every stop on a multi-leg canonical route is labelled', () {
      final compatibility = Compatibility.maybe({
        'compatible': true,
        'rejection_codes': <String>[],
        'covered_leg_ids': [1, 2],
        'covered_legs': [
          canonicalLeg(),
          canonicalLeg(
            id: 2,
            position: 1,
            mode: 'DRIVE',
            originName: 'Houari Boumediene',
            originIata: 'ALG',
            destinationName: 'Jijel',
            destinationIata: null,
          ),
        ],
        'limitations': <String>[],
      })!;

      final labels = <String>[
        for (final leg in compatibility.coveredLegs) leg.origin!.coarseLabel,
        compatibility.coveredLegs.last.destination!.coarseLabel,
      ];
      expect(labels, ['Paris CDG', 'Houari Boumediene', 'Jijel']);
      expect(labels.any((label) => label.isEmpty), isFalse);
    });
  });

  group('Find Travelers renders a labelled route', () {
    testWidgets('every stop on the candidate card carries a place name', (
      tester,
    ) async {
      final backend = FakeBackend();
      backend.on('GET', '/api/matches/compatible-journeys', FakeResponse(200, {
        'count': 1,
        'results': [
          {
            'delivery_request': {
              'id': 5,
              'sender_id': 42,
              'pickup': null,
              'delivery': null,
              'pickup_place': {
                'id': 1,
                'name': 'Paris',
                'display_label': 'Paris',
                'place_type': 'locality',
                'country_code': 'FR',
                'iata_code': null,
              },
              'delivery_place': {
                'id': 3,
                'name': 'Jijel',
                'display_label': 'Jijel',
                'place_type': 'locality',
                'country_code': 'DZ',
                'iata_code': null,
              },
              'actual_weight_kg': '2.00',
            },
            'journey': {
              'id': 12,
              'traveler_id': 99,
              'start_location': null,
              'destination_location': null,
              'first_departure': '2026-09-17T11:00:00Z',
              'start_leg_id': 1,
              'end_leg_id': 2,
              'covered_legs': <Object>[],
            },
            'compatibility': {
              'compatible': true,
              'rejection_codes': <String>[],
              'covered_leg_ids': [1, 2],
              'covered_legs': [
                canonicalLeg(),
                canonicalLeg(
                  id: 2,
                  position: 1,
                  mode: 'DRIVE',
                  originName: 'Houari Boumediene',
                  originIata: 'ALG',
                  destinationName: 'Jijel',
                  destinationIata: null,
                ),
              ],
              'limitations': <String>[],
            },
            'pricing': null,
          },
        ],
      }));

      await pumpRouted(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();

      // The three stops of the sub-route, each named. Before J1.2 the route
      // line drew three dots with empty labels beside them.
      expect(find.text('Paris CDG'), findsOneWidget);
      expect(find.text('Houari Boumediene'), findsOneWidget);
      expect(find.text('Jijel'), findsOneWidget);
    });
  });

  group('catch-up traffic', () {
    /// A `LiveUpdates` on a clock the test controls, with the coalescing
    /// window short enough that each flush can be awaited on its own.
    ({LiveUpdates live, void Function(Duration) advance}) build() {
      var clock = DateTime.utc(2026, 9, 15, 12);
      final live = LiveUpdates(
        coalesceFor: const Duration(milliseconds: 1),
        now: () => clock,
      );
      addTearDown(live.dispose);
      live.bindAccount(42);
      return (live: live, advance: (d) => clock = clock.add(d));
    }

    Future<void> settle() =>
        Future<void>.delayed(const Duration(milliseconds: 20));

    test('three catch-ups for one foreground cause one round of reads', () async {
      final (:live, :advance) = build();
      var deals = 0;
      live.register(const LiveResource.deals(), () => deals++);

      // Resume, then the chat socket connects, then the notification socket.
      // All three ask for the same catch-up within a second of each other.
      live.reconcileScope(const []);
      await settle();
      advance(const Duration(milliseconds: 900));
      live.reconcileScope(const []);
      await settle();
      advance(const Duration(milliseconds: 900));
      live.reconcileScope(const []);
      await settle();

      expect(deals, 1);
    });

    test('a resource that was not covered still reconciles immediately', () async {
      final (:live, :advance) = build();
      var deals = 0;
      var thread = 0;
      live.register(const LiveResource.deals(), () => deals++);
      live.register(const LiveResource.chat(7), () => thread++);

      live.reconcileScope(const []);
      await settle();
      advance(const Duration(milliseconds: 100));
      // The user pushed a chat thread after the first catch-up. That detail
      // resource was in nobody's scope a moment ago, so it is not "covered".
      live.reconcileScope(const [LiveResource.chat(7)]);
      await settle();

      expect(deals, 1);
      expect(thread, 1);
    });

    test('a genuine reconnect after the window still catches up', () async {
      final (:live, :advance) = build();
      var deals = 0;
      live.register(const LiveResource.deals(), () => deals++);

      live.reconcileScope(const []);
      await settle();
      advance(const Duration(seconds: 30));
      live.reconcileScope(const []);
      await settle();

      expect(deals, 2);
    });

    test('a real business event is never suppressed by the window', () async {
      final (:live, advance: _) = build();
      var deals = 0;
      live.register(const LiveResource.deals(), () => deals++);

      live.reconcileScope(const []);
      await settle();
      expect(deals, 1);

      live.ingest(const {
        'type': 'deal.updated',
        'event_id': 'e-1',
        'data': <String, dynamic>{},
      }, source: LiveEventSource.websocket);
      await settle();

      expect(deals, 2);
    });
  });

  group('a slow read is bounded and honestly named', () {
    test('the whole read cannot outlast three full attempts', () {
      // Per-attempt timeouts are unchanged: they are sized for a phone on a
      // bad connection. What J1.2 bounds is the sum. A read retries twice, so
      // without a budget one stalled request held a screen for three full
      // receive timeouts plus backoff before saying anything.
      expect(AppConfig.requestBudget, lessThan(AppConfig.requestTimeout * 3));
      expect(
        AppConfig.requestBudget,
        greaterThan(AppConfig.requestTimeout),
        reason: 'a budget under one attempt would disable retrying entirely',
      );
    });

    testWidgets('a cancelled request is not reported as a server fault', (
      tester,
    ) async {
      late FailureCopy cancelled;
      late FailureCopy server;
      await pumpApp(
        tester,
        Builder(
          builder: (context) {
            cancelled = describeFailure(
              context,
              ApiException(
                kind: ApiFailureKind.cancelled,
                code: ApiErrorCode.unknown,
              ),
            );
            server = describeFailure(
              context,
              ApiException(
                kind: ApiFailureKind.server,
                code: ApiErrorCode.unknown,
              ),
            );
            return const SizedBox.shrink();
          },
        ),
      );
      final l = await L.delegate.load(const Locale('en'));

      // Cancelling happens when the user leaves a screen or a newer read
      // replaces an older one. Blaming the server for it invites a pointless
      // retry of something nobody is waiting for.
      expect(cancelled.title, l.stateTimeoutTitle);
      expect(cancelled.tone, isNot(server.tone));
      expect(server.title, l.stateServerErrorTitle);
    });

    testWidgets('a timeout says the screen kept what it had', (tester) async {
      final l = await L.delegate.load(const Locale('en'));
      expect(l.stateTimeoutBody, contains('try again'));
      expect(l.stateTimeoutBody, contains('Nothing was lost'));
    });
  });

  group('payout review state on the Traveler card', () {
    Future<void> pumpMethods(WidgetTester tester, String reviewState) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/methods',
        FakeResponse(200, methodsFixture(reviewState: reviewState)),
      );
      await pumpRouted(
        tester,
        const PayoutMethodsScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('a correction says what to do again', (tester) async {
      await pumpMethods(tester, 'needs_attention');
      final l = await L.delegate.load(const Locale('en'));
      expect(find.text(l.payoutDzdCorrectionBody), findsOneWidget);
      expect(find.text(l.payoutDzdRejectedBody), findsNothing);
    });

    testWidgets('a rejection says the account was refused', (tester) async {
      await pumpMethods(tester, 'rejected');
      final l = await L.delegate.load(const Locale('en'));
      expect(find.text(l.payoutDzdRejectedBody), findsOneWidget);
      expect(find.text(l.payoutDzdCorrectionBody), findsNothing);
    });

    testWidgets('an older server without the field keeps the old sentence', (
      tester,
    ) async {
      await pumpMethods(tester, '');
      final l = await L.delegate.load(const Locale('en'));
      expect(find.text(l.payoutDzdNeedsAttentionBody), findsOneWidget);
    });

    testWidgets('no reviewer note or internal code reaches the card', (
      tester,
    ) async {
      await pumpMethods(tester, 'rejected');
      expect(find.textContaining('profile_'), findsNothing);
      expect(find.textContaining('review'), findsNothing);
    });
  });
}
