/// L2B: Browse trips, Browse requests and the People list, and the previews
/// they open.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/domain/public_discovery.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';

List<Map<String, dynamic>> _trips(int from, int count) => [
  for (var i = from; i < from + count; i++)
    tripCardFixture(i, name: 'Traveler $i'),
];

Future<void> _scrollToEnd(WidgetTester tester) async {
  await tester.drag(find.byType(ListView).first, const Offset(0, -20000));
  await tester.pumpAndSettle();
}

void main() {
  group('Browse trips', () {
    testWidgets(
      'lists the first page and pages on the server\'s cursor as it scrolls',
      (tester) async {
        final backend = discoveryBackend()
          ..handle('GET', '/api/discovery/trips', (r) {
            final offset = (r.query['offset'] as int?) ?? 0;
            return switch (offset) {
              0 => discoveryPage(_trips(1, 20), next: 20),
              20 => discoveryPage(_trips(21, 5), next: null),
              _ => throw StateError('offset $offset'),
            };
          });
        await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

        expect(find.text('Traveler 1'), findsOneWidget);
        expect(backend.to('GET', '/api/discovery/trips'), hasLength(1));

        await _scrollToEnd(tester);
        await _scrollToEnd(tester);

        final sent = backend.to('GET', '/api/discovery/trips');
        expect([for (final r in sent) r.query['offset']], [null, 20]);
        expect(find.text('Traveler 25'), findsOneWidget);

        await _scrollToEnd(tester);
        expect(
          backend.to('GET', '/api/discovery/trips'),
          hasLength(2),
          reason: 'no cursor, no third read',
        );
      },
    );

    testWidgets('a next page that fails keeps the list and offers a retry', (
      tester,
    ) async {
      var failing = true;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (r) {
          final offset = (r.query['offset'] as int?) ?? 0;
          if (offset == 0) return discoveryPage(_trips(1, 20), next: 20);
          return failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : discoveryPage(_trips(21, 1));
        });
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      await _scrollToEnd(tester);
      await _scrollToEnd(tester);
      expect(find.text('Traveler 1'), findsNothing, reason: 'scrolled away');
      expect(find.text('Try again'), findsOneWidget);

      failing = false;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();
      await _scrollToEnd(tester);

      expect(find.text('Traveler 21'), findsOneWidget);
    });

    testWidgets('a corridor from Home becomes the filter pills and the query', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(corridor: Corridor('FR', 'DZ')),
        backend,
      );

      final sent = backend.lastTo('GET', '/api/discovery/trips')!;
      expect(sent.query['origin_country'], 'FR');
      expect(sent.query['destination_country'], 'DZ');
      expect(find.bySemanticsLabel('From: France'), findsOneWidget);
      expect(find.bySemanticsLabel('To: Algeria'), findsOneWidget);
    });

    testWidgets('clearing a pill reads again without it', (tester) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(corridor: Corridor('FR', 'DZ')),
        backend,
      );

      await tester.tap(find.byTooltip('Clear From'));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('GET', '/api/discovery/trips')!;
      expect(sent.query.containsKey('origin_country'), isFalse);
      expect(sent.query['destination_country'], 'DZ');
    });

    testWidgets('a date filter is sent as the start of that day', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      await tester.tap(find.bySemanticsLabel('From date'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('OK'));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('GET', '/api/discovery/trips')!;
      final now = DateTime.now();
      expect(
        DateTime.parse(sent.query['departing_after'] as String),
        DateTime(now.year, now.month, now.day).toUtc(),
      );
    });

    testWidgets('an empty list with no filter says what to do', (tester) async {
      final backend = discoveryBackend();
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      expect(find.text('No trips right now'), findsOneWidget);

      await tester.tap(find.text('Send a parcel'));
      await tester.pumpAndSettle();
      expect(find.textContaining('at request-create'), findsOneWidget);
    });

    testWidgets('an empty list under a filter offers to clear it', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(corridor: Corridor('ES', 'DZ')),
        backend,
      );

      expect(find.text('No results'), findsOneWidget);
      await tester.tap(find.text('Clear filters'));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('GET', '/api/discovery/trips')!;
      expect(sent.query, {'limit': 20});
      expect(find.text('No trips right now'), findsOneWidget);
    });

    testWidgets('a tier switched off reads "not available", not an error', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          const FakeResponse(200, {'state': 'disabled', 'results': <Object>[]}),
        );
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      expect(find.text('Not available right now'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
    });

    testWidgets('a failed first read has a retry', (tester) async {
      var failing = true;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (_) {
          return failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : discoveryPage([tripCardFixture(1, name: 'Nadia')]);
        });
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      failing = false;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Nadia'), findsOneWidget);
    });
  });

  group('a route alert opens Browse', () {
    testWidgets('on its own route, with the trip that triggered it', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/alerts',
          FakeResponse(200, {
            'results': [alertFixture(4)],
          }),
        )
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'Nadia')]),
        );

      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(alertId: 4, focusJourneyId: 11),
        backend,
      );

      final trips = backend.to('GET', '/api/discovery/trips');
      expect(trips, hasLength(1), reason: 'no unfiltered read is thrown away');
      expect(trips.single.query['origin_place_id'], 1);
      expect(trips.single.query['destination_place_id'], 2);
      expect(
        find.text('You propose first. Nothing is booked from here.'),
        findsOneWidget,
        reason: 'the trip that triggered the alert is opened',
      );
    });

    testWidgets('and falls back to everything when the alert is gone', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/alerts',
          const FakeResponse(200, {'results': <Object>[]}),
        );

      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(alertId: 4, focusJourneyId: 11),
        backend,
      );

      expect(backend.lastTo('GET', '/api/discovery/trips')!.query, {
        'limit': 20,
      });
      expect(
        find.text('You propose first. Nothing is booked from here.'),
        findsNothing,
      );
    });
  });

  group('the trip preview, for a sender', () {
    testWidgets(
      'lists the sender\'s open parcels and opens Find Travelers on the chosen one',
      (tester) async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/trips',
            discoveryPage([tripCardFixture(11, name: 'Nadia')]),
          )
          ..on(
            'GET',
            '/api/parcels',
            FakeResponse(200, [
              ownRequestFixture(5, title: 'Wedding dress'),
              ownRequestFixture(6, status: 'completed', title: 'Done already'),
            ]),
          );
        await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

        await tester.tap(find.text('Nadia'));
        await tester.pumpAndSettle();

        expect(find.text('Choose one of your parcels'), findsOneWidget);
        expect(find.text('Wedding dress'), findsOneWidget);
        expect(
          find.text('Done already'),
          findsNothing,
          reason: 'only open ones',
        );

        await tester.tap(find.text('Wedding dress'));
        await tester.pumpAndSettle();

        expect(
          find.text('at request-discovery {id: 5} {journey: 11}'),
          findsOneWidget,
        );
      },
    );

    testWidgets('with no open parcel, offers a new one for the route', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'Nadia')]),
        );
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

      await tester.tap(find.text('Nadia'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Post a parcel for this route'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at request-create'), findsOneWidget);
    });

    testWidgets(
      'shows only what the card carries: first name, cities, dates, space',
      (tester) async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/trips',
            discoveryPage([tripCardFixture(11, name: 'Nadia')]),
          );
        await pumpDiscovery(tester, const BrowseTripsScreen(), backend);

        await tester.tap(find.text('Nadia'));
        await tester.pumpAndSettle();

        expect(find.text('Identity verified'), findsOneWidget);
        expect(find.text('8 kg left'), findsOneWidget, reason: 'the card');
        expect(find.text('8 kg'), findsOneWidget, reason: 'the sheet value');
        expect(find.textContaining('Paris'), findsWidgets);
        expect(find.textContaining('detour'), findsNothing);
        expect(find.textContaining('km'), findsNothing);
      },
    );
  });

  group('Browse requests and the request preview, for a traveler', () {
    Future<FakeBackend> carryBackend({
      List<Map<String, dynamic>>? journeys,
    }) async {
      return discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/requests',
          discoveryPage([requestCardFixture(31, title: 'Passport photos')]),
        )
        ..on(
          'GET',
          '/api/journeys',
          FakeResponse(200, journeys ?? [liveJourneyFixture(3)]),
        );
    }

    testWidgets('"I can carry this" on a single live trip sends it', (
      tester,
    ) async {
      final backend = await carryBackend()
        ..on(
          'POST',
          '/api/discovery/requests/31/interest',
          const FakeResponse(201, {
            'request_id': 31,
            'journey_id': 3,
            'created': true,
          }),
        );
      await pumpDiscovery(
        tester,
        const BrowseRequestsScreen(),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('Passport photos'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();

      expect(
        backend.lastTo('POST', '/api/discovery/requests/31/interest')!.body,
        {'journey_id': 3},
      );
      expect(find.text('Sender notified'), findsOneWidget);
      expect(find.text('Done'), findsOneWidget);
    });

    testWidgets('with two live trips the traveler chooses which', (
      tester,
    ) async {
      final backend =
          await carryBackend(
              journeys: [
                liveJourneyFixture(3),
                liveJourneyFixture(4, from: 'Lyon'),
              ],
            )
            ..on(
              'POST',
              '/api/discovery/requests/31/interest',
              const FakeResponse(201, {
                'request_id': 31,
                'journey_id': 4,
                'created': true,
              }),
            );
      await pumpDiscovery(
        tester,
        const BrowseRequestsScreen(),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('Passport photos'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();
      expect(find.text('Which trip?'), findsOneWidget);
      await tester.tap(find.textContaining('Lyon'));
      await tester.pumpAndSettle();

      expect(
        backend.lastTo('POST', '/api/discovery/requests/31/interest')!.body,
        {'journey_id': 4},
      );
    });

    testWidgets('with no live trip the action is to add one', (tester) async {
      final backend = await carryBackend(journeys: const []);
      await pumpDiscovery(
        tester,
        const BrowseRequestsScreen(),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('Passport photos'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Add a journey to carry this'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at journey-create'), findsOneWidget);
      expect(
        backend.to('POST', '/api/discovery/requests/31/interest'),
        isEmpty,
      );
    });

    testWidgets(
      'the daily cap and a closed request each have their own sentence',
      (tester) async {
        final backend = await carryBackend()
          ..on(
            'POST',
            '/api/discovery/requests/31/interest',
            const FakeResponse(429, {'code': 'interest_daily_cap_reached'}),
          );
        await pumpDiscovery(
          tester,
          const BrowseRequestsScreen(),
          backend,
          role: RoleContext.traveler,
        );

        await tester.tap(find.text('Passport photos'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('I can carry this'));
        await tester.pumpAndSettle();

        expect(find.textContaining("today's limit"), findsOneWidget);
      },
    );

    testWidgets('the preview says what the action is not', (tester) async {
      final backend = await carryBackend();
      await pumpDiscovery(
        tester,
        const BrowseRequestsScreen(),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.text('Passport photos'));
      await tester.pumpAndSettle();

      expect(find.textContaining("It isn't an offer"), findsOneWidget);
      expect(find.text('Documents'), findsWidgets);
    });
  });

  group('People', () {
    testWidgets('lists members who opted in and opens their page', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([
            profileCardFixture(
              id: 'p-7',
              name: 'Leila',
              routes: [usualRouteFixture()],
            ),
          ]),
        );
      await pumpDiscovery(tester, const BrowsePeopleScreen(), backend);

      expect(find.text('Travelers on Wassla'), findsOneWidget);
      await tester.tap(find.text('Leila'));
      await tester.pumpAndSettle();

      expect(find.text('at person {id: p-7} {}'), findsOneWidget);
    });

    testWidgets('a person without an id cannot be opened', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([profileCardFixture(name: 'Leila')..['id'] = null]),
        );
      await pumpDiscovery(tester, const BrowsePeopleScreen(), backend);

      await tester.tap(find.text('Leila'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at person'), findsNothing);
    });

    testWidgets('empty and switched-off are different states', (tester) async {
      await pumpDiscovery(
        tester,
        const BrowsePeopleScreen(),
        discoveryBackend(),
      );
      expect(find.text('No public profiles yet'), findsOneWidget);
    });

    testWidgets('switched off', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people',
          const FakeResponse(200, {'state': 'disabled', 'results': <Object>[]}),
        );
      await pumpDiscovery(tester, const BrowsePeopleScreen(), backend);
      expect(find.text('Not available right now'), findsOneWidget);
    });

    testWidgets('a traveler sees senders', (tester) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const BrowsePeopleScreen(),
        backend,
        role: RoleContext.traveler,
      );

      expect(find.text('Senders on Wassla'), findsOneWidget);
      expect(
        backend.lastTo('GET', '/api/discovery/people')!.query['role'],
        'traveler',
      );
    });
  });
}
