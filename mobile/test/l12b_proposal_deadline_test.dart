/// L12B: the proposal deadline and the "a parcel fits your trip" alert, on the
/// app.
///
/// What the tests hold to: the deadline line says what the server published
/// (`expires_at`, `awaiting_user_id`) and decides nothing; the last hour is a
/// calm countdown; an expired proposal is a designed state with the next step
/// for each side, and an `offer_expired` refusal lands there instead of in an
/// error banner; both new channels reach the right screen from the push, the
/// bell and the socket; the trip-fit alert opens the preview of that parcel
/// with that trip, even when the parcel is not on the first page, and says so
/// when it is gone.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/features/deliveries/deliveries_screen.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/notifications/notifications_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/features/requests/request_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

const _phone = DeviceProfile(name: 'phone (360x740)', size: Size(360, 740));

final _now = DateTime.utc(2026, 11, 14, 10);

String _at(Duration after) => _now.add(after).toIso8601String();

/// A proposal from the sender (42) to the traveler (99).
///
/// [awaiting] is who must answer: `sender`, `traveler` or null once it is over.
Map<String, dynamic> _offer({
  String status = 'pending',
  Duration? deadline,
  int? awaitingUser = 99,
  List<String> actions = const ['accept', 'counter', 'decline'],
}) => {
  'id': 501,
  'match': 77,
  'proposed_by': 'sender',
  'proposer_id': 42,
  'economics_version': 'v1_eur',
  'currency': 'EUR',
  'traveler_reward_minor': 3000,
  'traveler_total_minor': 3000,
  'sender_total_minor': 3500,
  'sender_total_with_boost_minor': 3500,
  'platform_fee_minor': 500,
  'status': status,
  'note': '',
  'expires_at': deadline == null ? null : _at(deadline),
  'awaiting_party': awaitingUser == null
      ? null
      : (awaitingUser == 99 ? 'traveler' : 'sender'),
  'awaiting_user_id': awaitingUser,
  'allowed_actions': actions,
};

Map<String, dynamic> _match({Map<String, dynamic>? offer, String? status}) => {
  'id': 77,
  'parcel_id': 12,
  'journey_id': 3,
  'sender_id': 42,
  'traveler_id': 99,
  'sender_name': 'Amina',
  'traveler_name': 'Karim',
  'status': status ?? 'pending',
  'parcel': {
    'id': 12,
    'kind': 'delivery',
    'origin': {'id': 1, 'name': 'Paris', 'country_code': 'FR'},
    'destination': {'id': 2, 'name': 'Alger', 'country_code': 'DZ'},
  },
  'latest_offer': ?offer,
};

FakeBackend _negotiation(
  Map<String, dynamic> offer, {
  bool traveler = false,
  String? matchStatus,
}) {
  final match = _match(offer: offer, status: matchStatus);
  return discoveryBackend()
    ..on(
      'GET',
      '/api/me',
      FakeResponse(200, {...meFixture(), 'id': traveler ? 99 : 42}),
    )
    ..on('GET', '/api/matches/77', FakeResponse(200, match))
    ..on('GET', '/api/matches', FakeResponse(200, [match]))
    ..on('GET', '/api/matches/77/offers', FakeResponse(200, [offer]));
}

Future<void> _pump(
  WidgetTester tester,
  Widget screen,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
  RoleContext role = RoleContext.sender,
  DateTime Function()? now,
}) => pumpDiscovery(
  tester,
  screen,
  backend,
  locale: locale,
  device: _phone,
  role: role,
  now: now ?? () => _now,
  extraRoutes: [marker(Routes.negotiation, '/matches/:id')],
);

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

Map<String, dynamic> _row(
  int id,
  String channel,
  Map<String, dynamic> payload,
) => {
  'id': id,
  'channel': channel,
  'payload': payload,
  'read_at': null,
  'created_at': '2026-11-14T09:00:00Z',
};

AppNotification _notification(String channel, Map<String, dynamic> payload) =>
    AppNotification.fromJson(_row(1, channel, payload));

void main() {
  group('the contract', () {
    test('the deadline and who must answer are read as published', () {
      final offer = Offer.fromJson(
        _offer(deadline: const Duration(hours: 5), awaitingUser: 99),
      );
      expect(
        offer.expiresAt!.isAtSameMomentAs(_now.add(const Duration(hours: 5))),
        isTrue,
      );
      expect(offer.isAwaiting(99), isTrue);
      expect(offer.isAwaiting(42), isFalse);
    });

    test('an expired proposal has no actions and nobody awaited', () {
      final offer = Offer.fromJson(
        _offer(
          status: 'expired',
          deadline: const Duration(hours: -1),
          awaitingUser: null,
          actions: const [],
        ),
      );
      expect(offer.status, OfferStatus.expired);
      expect(offer.status.isFinished, isTrue);
      expect(offer.hasAnyAction, isFalse);
      expect(offer.isAwaiting(99), isFalse);
    });

    test('a proposal without a deadline has none to show', () {
      expect(Offer.fromJson(_offer()).expiresAt, isNull);
    });

    test('offer_expired is a stale-state refusal, not a failure', () {
      expect(ApiErrorCode.offerExpired.raw, 'offer_expired');
      expect(ApiErrorCode.offerExpired.impliesStaleClientState, isTrue);
    });

    test('the two channels are known', () {
      expect(
        NotificationChannel.parse('offer.response_reminder'),
        NotificationChannel.offerResponseReminder,
      );
      expect(
        NotificationChannel.parse('discovery.request_fits_trip'),
        NotificationChannel.discoveryRequestFitsTrip,
      );
    });

    test('the reminder opens the proposal, the alert opens the parcel', () {
      final reminder = _notification('offer.response_reminder', {
        'match_id': 77,
        'parcel_id': 12,
        'journey_id': 3,
        'offer_id': 501,
        'tracking_number': 'WSL-7K3M9QXD',
      }).destination;
      expect(reminder, isA<OpenMatch>());
      expect((reminder! as OpenMatch).matchId, 77);

      final fits = _notification('discovery.request_fits_trip', {
        'request_id': 31,
        'journey_id': 11,
      }).destination;
      expect(fits, isA<OpenRequestFit>());
      final alert = fits! as OpenRequestFit;
      expect(alert.requestId, 31);
      expect(alert.journeyId, 11);
    });

    test('a row missing an id has nowhere to go', () {
      expect(
        _notification('offer.response_reminder', const {}).destination,
        isNull,
      );
      expect(
        _notification('discovery.request_fits_trip', {
          'request_id': 31,
        }).destination,
        isNull,
      );
    });

    test('a push opens the same places', () {
      expect(
        pushLocation({
          'channel': 'offer.response_reminder',
          'match_id': '77',
          'parcel_id': '12',
          'journey_id': '3',
          'offer_id': '501',
        }),
        '/matches/77',
      );
      final fits = Uri.parse(
        pushLocation({
          'channel': 'discovery.request_fits_trip',
          'request_id': '31',
          'journey_id': '11',
        })!,
      );
      expect(fits.path, '/discover/requests');
      expect(fits.queryParameters, {'focus': '31', 'journey': '11'});
      expect(
        pushLocation({
          'channel': 'discovery.request_fits_trip',
          'request_id': '31',
        }),
        '/notifications',
      );
    });

    test('the live socket refreshes the proposal and the bell', () {
      final reminder = resourcesForLiveEvent('offer.response_reminder', {
        'match_id': 77,
        'offer_id': 501,
      });
      expect(reminder, contains(const LiveResource.notifications()));
      expect(reminder, contains(LiveResource.offers(77)));
      expect(reminder, contains(LiveResource.match(77)));

      final fits = resourcesForLiveEvent('discovery.request_fits_trip', {
        'request_id': 31,
        'journey_id': 11,
      });
      expect(fits, contains(const LiveResource.notifications()));
      expect(fits, contains(const LiveResource.unread()));
      expect(
        fits,
        isNot(contains(LiveResource.request(31))),
        reason: 'someone else’s parcel is not the member’s own request',
      );

      final expired = resourcesForLiveEvent('offer.updated', {
        'match_id': 77,
        'offer_id': 501,
        'status': 'expired',
      });
      expect(expired, contains(LiveResource.offers(77)));
    });
  });

  group('the deadline line', () {
    testWidgets('far away it names the moment, for each side', (tester) async {
      final backend = _negotiation(_offer(deadline: const Duration(hours: 5)));
      await _pump(tester, const NegotiationScreen(matchId: 77), backend);
      // The sender wrote it and waits.
      expect(
        find.textContaining('Waiting for an answer until'),
        findsOneWidget,
      );
      expect(find.textContaining('Answer by'), findsNothing);
    });

    testWidgets('the person who must answer is asked to answer by then', (
      tester,
    ) async {
      final backend = _negotiation(
        _offer(deadline: const Duration(hours: 5)),
        traveler: true,
      );
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.textContaining('Answer by'), findsOneWidget);
      expect(find.text('Accept'), findsOneWidget);
    });

    testWidgets('in the last hour it is a countdown in minutes', (
      tester,
    ) async {
      final backend = _negotiation(
        _offer(deadline: const Duration(minutes: 42)),
        traveler: true,
      );
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.text('Answer within 42 minutes'), findsOneWidget);
    });

    testWidgets('the other side sees how long is left', (tester) async {
      final backend = _negotiation(
        _offer(deadline: const Duration(minutes: 42)),
      );
      await _pump(tester, const NegotiationScreen(matchId: 77), backend);
      expect(
        find.text('Waiting for an answer, 42 minutes left'),
        findsOneWidget,
      );
    });

    testWidgets('the last minute says so', (tester) async {
      final backend = _negotiation(
        _offer(deadline: const Duration(seconds: 40)),
        traveler: true,
      );
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.text('Answer within less than a minute'), findsOneWidget);
    });

    testWidgets('a proposal without a deadline shows no line', (tester) async {
      final backend = _negotiation(_offer(), traveler: true);
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.textContaining('Answer by'), findsNothing);
      expect(find.textContaining('Answer within'), findsNothing);
      expect(find.text('Accept'), findsOneWidget);
    });

    testWidgets('the countdown ticks, and at zero the screen re-reads', (
      tester,
    ) async {
      var now = _now;
      final backend = _negotiation(
        _offer(deadline: const Duration(minutes: 3)),
        traveler: true,
      );
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
        now: () => now,
      );
      expect(find.text('Answer within 3 minutes'), findsOneWidget);
      final reads = backend.to('GET', '/api/matches/77').length;

      now = _now.add(const Duration(minutes: 1));
      await tester.pump(const Duration(seconds: 20));
      expect(find.text('Answer within 2 minutes'), findsOneWidget);

      now = _now.add(const Duration(minutes: 3, seconds: 1));
      await tester.pump(const Duration(minutes: 3));
      await tester.pumpAndSettle();
      expect(find.text('The time to answer has passed'), findsOneWidget);
      expect(
        backend.to('GET', '/api/matches/77').length,
        greaterThan(reads),
        reason: 'the server, not the clock, says the proposal expired',
      );
    });
  });

  group('an expired proposal', () {
    testWidgets('the sender is offered another traveler', (tester) async {
      final backend = _negotiation(
        _offer(
          status: 'expired',
          deadline: const Duration(hours: -1),
          awaitingUser: null,
          actions: const [],
        ),
      );
      await _pump(tester, const NegotiationScreen(matchId: 77), backend);

      expect(find.text('This proposal expired'), findsOneWidget);
      expect(find.textContaining('Nothing was reserved or charged'), findsOne);
      expect(
        find.textContaining('Expired '),
        findsNothing,
        reason: 'the notice says it; no second line for the deadline',
      );
      expect(find.text('Accept'), findsNothing);
      expect(find.text('Decline'), findsNothing);

      await tester.tap(find.text('Propose to another traveler'));
      await tester.pumpAndSettle();
      expect(find.textContaining('at request-discovery {id: 12}'), findsOne);
    });

    testWidgets('the traveler is offered the open parcels', (tester) async {
      final backend = _negotiation(
        _offer(
          status: 'expired',
          deadline: const Duration(hours: -1),
          awaitingUser: null,
          actions: const [],
        ),
        traveler: true,
      );
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );

      expect(find.text('This proposal expired'), findsOneWidget);
      expect(find.textContaining('Other parcels may fit'), findsOneWidget);
      await tester.tap(find.text('Browse parcels'));
      await tester.pumpAndSettle();
      expect(find.textContaining('at browse-requests'), findsOneWidget);
    });

    testWidgets('an offer_expired refusal shows that state, not an error', (
      tester,
    ) async {
      var expired = false;
      final pending = _offer(deadline: const Duration(minutes: 1));
      final over = _offer(
        status: 'expired',
        deadline: const Duration(minutes: -1),
        awaitingUser: null,
        actions: const [],
      );
      final backend = _negotiation(pending, traveler: true)
        ..handle(
          'GET',
          '/api/matches/77',
          (_) => FakeResponse(200, _match(offer: expired ? over : pending)),
        )
        ..handle('POST', '/api/offers/501/decline', (_) {
          expired = true;
          return FakeResponse(409, {
            'code': 'offer_expired',
            'detail': 'This proposal has expired.',
            'expires_at': _at(const Duration(minutes: -1)),
          });
        });
      await _pump(
        tester,
        const NegotiationScreen(matchId: 77),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('Decline'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Decline').last);
      await tester.pumpAndSettle();

      expect(find.text('This proposal expired'), findsOneWidget);
      expect(find.text('Browse parcels'), findsOneWidget);
      expect(find.text('This proposal has expired.'), findsNothing);
    });
  });

  group('the lists', () {
    testWidgets('Open offers carries the deadline on each row', (tester) async {
      final backend = _negotiation(
        _offer(deadline: const Duration(minutes: 42)),
        traveler: true,
      );
      await _pump(
        tester,
        const DeliveriesScreen(),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.text('Answer within 42 minutes'), findsOneWidget);
      expect(find.text('Your move'), findsWidgets);
    });

    testWidgets('a request keeps its expired proposal in the list', (
      tester,
    ) async {
      final offer = _offer(
        status: 'expired',
        deadline: const Duration(hours: -1),
        awaitingUser: null,
        actions: const [],
      );
      final backend = discoveryBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('GET', '/api/parcels/12', FakeResponse(200, ownRequestFixture(12)))
        ..on(
          'GET',
          '/api/matches',
          FakeResponse(200, [_match(offer: offer, status: 'cancelled')]),
        )
        ..on(
          'GET',
          '/api/parcels/12/pricing',
          FakeResponse(404, {'code': 'not_found', 'detail': 'n/a'}),
        );
      await _pump(tester, const RequestDetailScreen(requestId: 12), backend);
      await tester.scrollUntilVisible(
        find.text('Karim'),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text('Expired'), findsWidgets);
      expect(find.textContaining('Expired '), findsWidgets);
    });
  });

  group('the bell', () {
    FakeBackend inbox(List<Map<String, dynamic>> rows) => discoveryBackend()
      ..on(
        'GET',
        '/api/notifications',
        FakeResponse(200, {
          'count': rows.length,
          'next': null,
          'results': rows,
        }),
      )
      ..handle(
        'POST',
        '/api/notifications/1/read',
        (_) => const FakeResponse(204, {}),
      )
      ..handle(
        'POST',
        '/api/notifications/2/read',
        (_) => const FakeResponse(204, {}),
      );

    testWidgets('lists both and opens the proposal and the parcel', (
      tester,
    ) async {
      final backend = inbox([
        _row(1, 'offer.response_reminder', {'match_id': 77, 'offer_id': 501}),
        _row(2, 'discovery.request_fits_trip', {
          'request_id': 31,
          'journey_id': 11,
        }),
      ]);
      await _pump(tester, const NotificationsScreen(), backend);

      expect(find.text('A proposal is about to expire'), findsOneWidget);
      expect(find.text('A parcel fits your trip'), findsOneWidget);

      await tester.tap(find.text('A proposal is about to expire'));
      await tester.pumpAndSettle();
      expect(find.textContaining('at negotiation {id: 77}'), findsOneWidget);
    });

    testWidgets('the parcel alert opens Browse with the trip named', (
      tester,
    ) async {
      final backend = inbox([
        _row(2, 'discovery.request_fits_trip', {
          'request_id': 31,
          'journey_id': 11,
        }),
      ]);
      await _pump(tester, const NotificationsScreen(), backend);

      await tester.tap(find.text('A parcel fits your trip'));
      await tester.pumpAndSettle();
      expect(find.textContaining('at browse-requests'), findsOneWidget);
      expect(find.textContaining('focus: 31'), findsOneWidget);
      expect(find.textContaining('journey: 11'), findsOneWidget);
    });
  });

  group('the parcel preview from a trip-fit alert', () {
    FakeBackend feed({
      required List<Map<String, dynamic>> firstPage,
      List<Map<String, dynamic>>? secondPage,
      List<Map<String, dynamic>>? journeys,
    }) => discoveryBackend()
      ..handle('GET', '/api/discovery/requests', (r) {
        final offset = (r.query['offset'] as int?) ?? 0;
        return offset == 0
            ? discoveryPage(firstPage, next: secondPage == null ? null : 20)
            : discoveryPage(secondPage ?? const []);
      })
      ..on(
        'GET',
        '/api/journeys',
        FakeResponse(
          200,
          journeys ??
              [liveJourneyFixture(3), liveJourneyFixture(4, from: 'Lyon')],
        ),
      );

    testWidgets('opens that parcel and carries it on that trip', (
      tester,
    ) async {
      final backend =
          feed(firstPage: [requestCardFixture(31, title: 'Passport photos')])
            ..on(
              'POST',
              '/api/discovery/requests/31/interest',
              const FakeResponse(201, {
                'request_id': 31,
                'journey_id': 4,
                'created': true,
              }),
            );
      await _pump(
        tester,
        const BrowseRequestsScreen(focusRequestId: 31, carryJourneyId: 4),
        backend,
        role: RoleContext.traveler,
      );

      expect(find.text('Passport photos'), findsWidgets);
      expect(find.textContaining('Suggested for your trip'), findsOneWidget);
      expect(find.textContaining('Lyon'), findsWidgets);

      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();

      expect(find.text('Which trip?'), findsNothing);
      expect(
        backend.lastTo('POST', '/api/discovery/requests/31/interest')!.body,
        {'journey_id': 4},
      );
      expect(find.text('Sender notified'), findsOneWidget);
    });

    testWidgets('finds a parcel that is not on the first page', (tester) async {
      final backend = feed(
        firstPage: [
          for (var i = 1; i <= 20; i++)
            requestCardFixture(100 + i, title: 'Other $i'),
        ],
        secondPage: [requestCardFixture(31, title: 'Passport photos')],
      );
      await _pump(
        tester,
        const BrowseRequestsScreen(focusRequestId: 31, carryJourneyId: 3),
        backend,
        role: RoleContext.traveler,
      );

      expect(find.text('I can carry this'), findsOneWidget);
      expect(find.textContaining('Suggested for your trip'), findsOneWidget);
      expect(find.text('This parcel is no longer open'), findsNothing);
    });

    testWidgets('says so when the parcel is gone', (tester) async {
      final backend = feed(
        firstPage: [requestCardFixture(40, title: 'Something else')],
      );
      await _pump(
        tester,
        const BrowseRequestsScreen(focusRequestId: 31, carryJourneyId: 3),
        backend,
        role: RoleContext.traveler,
      );

      expect(find.text('This parcel is no longer open'), findsOneWidget);
      expect(find.text('Something else'), findsOneWidget);
      expect(find.text('I can carry this'), findsNothing);
    });

    testWidgets('the server’s reason shows when the pair no longer fits', (
      tester,
    ) async {
      final backend =
          feed(firstPage: [requestCardFixture(31, title: 'Passport photos')])
            ..on(
              'POST',
              '/api/discovery/requests/31/interest',
              const FakeResponse(409, {
                'code': 'incompatible_candidate',
                'detail': 'No.',
                'rejection_codes': <String>[],
              }),
            );
      await _pump(
        tester,
        const BrowseRequestsScreen(focusRequestId: 31, carryJourneyId: 3),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();
      expect(find.textContaining("doesn't fit that trip"), findsOneWidget);
    });

    testWidgets('a trip that is no longer live falls back to the chooser', (
      tester,
    ) async {
      final backend = feed(
        firstPage: [requestCardFixture(31, title: 'Passport photos')],
      );
      await _pump(
        tester,
        const BrowseRequestsScreen(focusRequestId: 31, carryJourneyId: 99),
        backend,
        role: RoleContext.traveler,
      );
      expect(find.textContaining('Suggested for your trip'), findsNothing);
      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();
      expect(find.text('Which trip?'), findsOneWidget);
    });
  });

  group('every state in English, French and Arabic at 360 px', () {
    for (final code in const ['en', 'fr', 'ar']) {
      testWidgets('countdown, far deadline and expired fit ($code)', (
        tester,
      ) async {
        for (final deadline in const [
          Duration(hours: 5),
          Duration(minutes: 42),
          Duration(seconds: 30),
        ]) {
          final backend = _negotiation(
            _offer(deadline: deadline),
            traveler: true,
          );
          await _pump(
            tester,
            const NegotiationScreen(matchId: 77),
            backend,
            locale: Locale(code),
            role: RoleContext.traveler,
          );
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox.shrink());
        }
        final backend = _negotiation(
          _offer(
            status: 'expired',
            deadline: const Duration(hours: -1),
            awaitingUser: null,
            actions: const [],
          ),
        );
        await _pump(
          tester,
          const NegotiationScreen(matchId: 77),
          backend,
          locale: Locale(code),
        );
        expect(tester.takeException(), isNull);
        final l = _l(tester);
        expect(find.text(l.offerExpiredTitle), findsOneWidget);
        expect(find.text(l.offerExpiredActionSender), findsOneWidget);
        expect(l.offerExpiredTitle, isNotEmpty);
      });
    }

    test('the French and Arabic copy is translated, not English', () async {
      final en = await L.delegate.load(const Locale('en'));
      for (final code in const ['fr', 'ar']) {
        final other = await L.delegate.load(Locale(code));
        for (final pair in [
          (en.offerExpiredTitle, other.offerExpiredTitle),
          (en.offerExpiredActionSender, other.offerExpiredActionSender),
          (en.offerExpiredActionTraveler, other.offerExpiredActionTraveler),
          (en.offerDeadlinePassed, other.offerDeadlinePassed),
          (en.offerAnswerWithin('x'), other.offerAnswerWithin('x')),
          (en.notificationOfferReminder, other.notificationOfferReminder),
          (en.notificationFitsTrip, other.notificationFitsTrip),
          (
            en.discoveryFocusGoneRequestTitle,
            other.discoveryFocusGoneRequestTitle,
          ),
        ]) {
          expect(pair.$2, isNot(pair.$1), reason: '$code: ${pair.$1}');
        }
      }
    });
  });
}
