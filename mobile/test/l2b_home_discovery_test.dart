/// L2B: Home's discovery sections, one state at a time.
///
/// Every section reads on its own, so each test breaks or switches off one and
/// proves the others carry on. The server's cards are rendered as they come;
/// nothing here asks the client to rank, filter or match.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/features/home/home_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

/// Tall enough that every Home section is on screen, so a test is about what a
/// section shows and not about how far down it is.
const _tall = DeviceProfile(name: 'tall (412x3000)', size: Size(412, 3000));

Future<void> _pumpHome(
  WidgetTester tester,
  FakeBackend backend, {
  RoleContext role = RoleContext.sender,
  Locale locale = const Locale('en'),
  DeviceProfile device = _tall,
}) async {
  await pumpDiscovery(
    tester,
    const HomeScreen(),
    backend,
    role: role,
    locale: locale,
    device: device,
  );
}

/// Drags Home down past the refresh threshold and lets the reads finish. The
/// threshold is a quarter of the viewport, felt at half speed, so a window
/// this tall needs a long pull.
Future<void> _pullToRefresh(WidgetTester tester) async {
  await tester.drag(find.byType(ListView).first, const Offset(0, 2400));
  await tester.pump(const Duration(seconds: 1));
  await tester.pumpAndSettle();
}

void main() {
  group('a sender', () {
    testWidgets('sees matches, trips and people, each from its own read', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          senderMatches([
            senderMatchGroup(5, [travelerCandidateFixture(101, name: 'Karim')]),
          ]),
        )
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'Nadia')]),
        )
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([
            profileCardFixture(name: 'Leila', routes: [usualRouteFixture()]),
          ]),
        );

      await _pumpHome(tester, backend);

      expect(find.text('Matches for you'), findsOneWidget);
      expect(find.text('Karim'), findsOneWidget);
      expect(find.text('Trips leaving soon'), findsOneWidget);
      expect(find.text('Nadia'), findsOneWidget);
      expect(find.text('Travelers on Wassla'), findsOneWidget);
      expect(find.text('Leila'), findsOneWidget);
      expect(find.text('Parcels looking for a traveler'), findsNothing);

      final trips = backend.lastTo('GET', '/api/discovery/trips')!;
      expect(trips.query, {'limit': 5}, reason: 'a preview, no filter');
      final people = backend.lastTo('GET', '/api/discovery/people')!;
      expect(people.query['role'], 'sender');
      expect(people.query['limit'], 10);
      expect(
        backend.to('GET', '/api/discovery/matches').single.query['role'],
        'sender',
        reason: 'the other role is not read',
      );
    });

    testWidgets('a tapped match opens Find Travelers with that trip in focus', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          senderMatches([
            senderMatchGroup(5, [travelerCandidateFixture(101, name: 'Karim')]),
          ]),
        );
      await _pumpHome(tester, backend);

      await tester.tap(find.text('Karim'));
      await tester.pumpAndSettle();

      expect(
        find.text('at request-discovery {id: 5} {journey: 101}'),
        findsOneWidget,
      );
    });

    testWidgets('more matches than shown offers See all on that item', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          senderMatches([
            senderMatchGroup(5, [travelerCandidateFixture(101)], more: true),
          ]),
        );
      await _pumpHome(tester, backend);

      await tester.tap(find.text('See all').first);
      await tester.pumpAndSettle();

      expect(
        find.textContaining('at request-discovery {id: 5}'),
        findsOneWidget,
      );
    });

    testWidgets('with nothing to match, Matches gives the next step', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await _pumpHome(tester, backend);

      expect(find.text('No matches yet'), findsOneWidget);
      expect(
        find.text(
          'Post a parcel and the travelers who fit it will show up here.',
        ),
        findsOneWidget,
      );
    });

    testWidgets(
      'while nothing fits yet, Matches says so and asks for nothing',
      (tester) async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/matches',
            const FakeResponse(200, {'state': 'none', 'groups': <Object>[]}),
          );
        await _pumpHome(tester, backend);

        expect(
          find.textContaining('No traveler fits your open parcels yet'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'a trip tapped on Home opens its preview with the sender\'s actions',
      (tester) async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/trips',
            discoveryPage([tripCardFixture(11, name: 'Nadia')]),
          );
        await _pumpHome(tester, backend);

        await tester.tap(find.text('Nadia'));
        await tester.pumpAndSettle();

        expect(
          find.text('You propose first. Nothing is booked from here.'),
          findsOneWidget,
        );
        expect(find.text('Post a parcel for this route'), findsOneWidget);
      },
    );
  });

  group('a traveler', () {
    testWidgets('sees parcels and senders, and the right reads are sent', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          FakeResponse(200, {
            'state': 'results',
            'groups': [
              travelerMatchGroup(3, [compatibleRequestFixture(21)]),
            ],
          }),
        )
        ..on(
          'GET',
          '/api/discovery/requests',
          discoveryPage([requestCardFixture(31, title: 'Passport photos')]),
        )
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([profileCardFixture(name: 'Yacine')]),
        );

      await _pumpHome(tester, backend, role: RoleContext.traveler);

      expect(find.text('Parcels looking for a traveler'), findsOneWidget);
      expect(find.text('Passport photos'), findsOneWidget);
      expect(find.text('Senders on Wassla'), findsOneWidget);
      expect(find.text('Yacine'), findsOneWidget);
      expect(find.text('I can carry this'), findsOneWidget);
      expect(find.text('Trips leaving soon'), findsNothing);
      expect(
        backend.to('GET', '/api/discovery/matches').single.query['role'],
        'traveler',
      );
      expect(
        backend.lastTo('GET', '/api/discovery/people')!.query['role'],
        'traveler',
      );
      expect(backend.to('GET', '/api/discovery/trips'), isEmpty);
    });

    testWidgets(
      '"I can carry this" sends the signal for that pair and says so',
      (tester) async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/matches',
            FakeResponse(200, {
              'state': 'results',
              'groups': [
                travelerMatchGroup(3, [compatibleRequestFixture(21)]),
              ],
            }),
          )
          ..on(
            'POST',
            '/api/discovery/requests/21/interest',
            const FakeResponse(201, {
              'request_id': 21,
              'journey_id': 3,
              'created': true,
            }),
          );
        await _pumpHome(tester, backend, role: RoleContext.traveler);

        await tester.tap(find.text('I can carry this'));
        await tester.pumpAndSettle();

        expect(
          backend.lastTo('POST', '/api/discovery/requests/21/interest')!.body,
          {'journey_id': 3},
        );
        expect(find.text('Sender notified'), findsOneWidget);
        expect(
          find.text('I can carry this'),
          findsNothing,
          reason: 'the same signal is not offered twice',
        );
      },
    );

    testWidgets('a refusal from the server is shown as the server\'s reasons', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          FakeResponse(200, {
            'state': 'results',
            'groups': [
              travelerMatchGroup(3, [compatibleRequestFixture(21)]),
            ],
          }),
        )
        ..on(
          'POST',
          '/api/discovery/requests/21/interest',
          const FakeResponse(409, {
            'code': 'incompatible_candidate',
            'rejection_codes': [
              'delivery_before_deadline',
              'a_code_from_the_future',
            ],
          }),
        );
      await _pumpHome(tester, backend, role: RoleContext.traveler);

      await tester.tap(find.text('I can carry this'));
      await tester.pumpAndSettle();

      expect(
        find.textContaining("This parcel doesn't fit that trip"),
        findsOneWidget,
      );
      expect(
        find.textContaining('It would arrive after the deadline.'),
        findsOneWidget,
      );
      expect(
        find.textContaining("The trip and the parcel don't match."),
        findsOneWidget,
        reason: 'an unknown code becomes the generic line, never raw text',
      );
      expect(find.textContaining('a_code_from_the_future'), findsNothing);
      expect(
        find.text('I can carry this'),
        findsOneWidget,
        reason: 'can be tried again',
      );
    });
  });

  group('states', () {
    testWidgets('a tier staff switched off is absent, not an error', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          const FakeResponse(200, {'state': 'disabled', 'results': <Object>[]}),
        )
        ..on(
          'GET',
          '/api/discovery/people',
          const FakeResponse(200, {'state': 'disabled', 'results': <Object>[]}),
        );

      await _pumpHome(tester, backend);

      expect(find.text('Trips leaving soon'), findsNothing);
      expect(find.text('Travelers on Wassla'), findsNothing);
      expect(find.text('Try again'), findsNothing);
      expect(
        find.text('Matches for you'),
        findsOneWidget,
        reason: 'the other tier carries on',
      );
    });

    testWidgets('one failing section shows its own retry and leaves the rest', (
      tester,
    ) async {
      var failing = true;
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([profileCardFixture(name: 'Leila')]),
        )
        ..handle('GET', '/api/discovery/trips', (_) {
          return failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : discoveryPage([tripCardFixture(11, name: 'Nadia')]);
        });
      await _pumpHome(tester, backend);

      expect(
        find.text('Leila'),
        findsOneWidget,
        reason: 'People is unaffected',
      );
      expect(find.text('Try again'), findsOneWidget);
      expect(find.text('Nadia'), findsNothing);

      failing = false;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Nadia'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
      expect(backend.to('GET', '/api/discovery/trips'), hasLength(2));
    });

    testWidgets('loading is its own state, not an empty one', (tester) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const HomeScreen(),
        backend,
        device: _tall,
        settle: false,
      );
      await tester.pump();

      // Before any answer: neither "nothing here" copy nor a failure.
      expect(find.text('Nothing listed yet'), findsNothing);
      expect(find.text('Try again'), findsNothing);
      expect(find.byType(SkeletonBox), findsWidgets);
      await tester.pumpAndSettle();
    });

    testWidgets(
      'an empty list says what to do next, and an empty route offers all routes',
      (tester) async {
        final backend = discoveryBackend();
        await _pumpHome(tester, backend);

        expect(find.text('Nothing listed yet'), findsOneWidget);
        expect(
          find.text('Trips that are about to leave will show up here.'),
          findsOneWidget,
        );
        expect(find.text('No public profiles yet'), findsOneWidget);

        await tester.tap(find.bySemanticsLabel('From France to Algeria'));
        await tester.pumpAndSettle();

        expect(find.text('Nothing on this route yet'), findsOneWidget);
        expect(
          find.text('All routes'),
          findsNWidgets(2),
          reason: 'the chip, and the way back out of an empty route',
        );
      },
    );

    testWidgets('a refresh that fails keeps what was loaded and says so', (
      tester,
    ) async {
      var calls = 0;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (_) {
          calls++;
          return calls == 1
              ? discoveryPage([tripCardFixture(11, name: 'Nadia')])
              : const FakeResponse(500, {'detail': 'boom'});
        });
      await _pumpHome(tester, backend);
      expect(find.text('Nadia'), findsOneWidget);

      await _pullToRefresh(tester);

      expect(find.text('Nadia'), findsOneWidget, reason: 'content stays');
      expect(find.text('Showing what we loaded earlier'), findsOneWidget);
    });
  });

  group('the corridor chips', () {
    testWidgets('narrow the section by country pair and send nothing else', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (r) {
          return r.query['origin_country'] == 'FR'
              ? discoveryPage([tripCardFixture(12, name: 'Lina')])
              : discoveryPage([tripCardFixture(11, name: 'Nadia')]);
        });
      await _pumpHome(tester, backend);
      expect(find.text('Nadia'), findsOneWidget);

      await tester.tap(find.bySemanticsLabel('From France to Algeria'));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('GET', '/api/discovery/trips')!;
      expect(sent.query['origin_country'], 'FR');
      expect(sent.query['destination_country'], 'DZ');
      expect(find.text('Lina'), findsOneWidget);
      expect(find.text('Nadia'), findsNothing);
    });

    testWidgets('are the six launch corridors, nothing else', (tester) async {
      await _pumpHome(tester, discoveryBackend());

      for (final label in [
        'From France to Algeria',
        'From Algeria to France',
        'From Spain to Algeria',
        'From Algeria to Spain',
        'From Germany to Algeria',
        'From Algeria to Germany',
      ]) {
        expect(find.bySemanticsLabel(label), findsOneWidget, reason: label);
      }
    });
  });

  group('the opt-in card', () {
    testWidgets('previews the card, and "Show my profile" turns it on', (
      tester,
    ) async {
      var shown = true;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/profile/me', (_) {
          return FakeResponse(200, ownProfileFixture(showPrompt: shown));
        })
        ..handle('PUT', '/api/discovery/profile/me', (_) {
          shown = false;
          return FakeResponse(
            200,
            ownProfileFixture(state: 'visible', discoverable: true),
          );
        });
      await _pumpHome(tester, backend);

      expect(find.text('Be found on Wassla'), findsOneWidget);
      expect(find.text('This is what others would see'), findsOneWidget);
      expect(
        find.text('Amina'),
        findsOneWidget,
        reason: 'the server\'s own card',
      );

      await tester.tap(find.text('Show my profile'));
      await tester.pumpAndSettle();

      expect(backend.lastTo('PUT', '/api/discovery/profile/me')!.body, {
        'is_discoverable': true,
      });
      expect(find.text('Be found on Wassla'), findsNothing);
    });

    testWidgets('"Not now" only dismisses it', (tester) async {
      var shown = true;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/profile/me', (_) {
          return FakeResponse(200, ownProfileFixture(showPrompt: shown));
        })
        ..handle('PUT', '/api/discovery/profile/me', (_) {
          shown = false;
          return FakeResponse(200, ownProfileFixture());
        });
      await _pumpHome(tester, backend);

      await tester.tap(find.text('Not now'));
      await tester.pumpAndSettle();

      expect(backend.lastTo('PUT', '/api/discovery/profile/me')!.body, {
        'prompt_dismissed': true,
      });
      expect(find.text('Be found on Wassla'), findsNothing);
    });

    testWidgets('is absent when the server does not ask for it', (
      tester,
    ) async {
      await _pumpHome(tester, discoveryBackend());

      expect(find.text('Be found on Wassla'), findsNothing);
    });

    testWidgets('a failed read leaves it out instead of an error', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/profile/me',
          const FakeResponse(500, {'detail': 'boom'}),
        );

      await _pumpHome(tester, backend);

      expect(find.text('Be found on Wassla'), findsNothing);
      expect(find.text('Try again'), findsNothing);
    });
  });

  group('pull to refresh', () {
    testWidgets('re-reads every section once, and only those', (tester) async {
      final backend = discoveryBackend();
      await _pumpHome(tester, backend);
      final before = backend.requests.length;

      await _pullToRefresh(tester);

      final after = backend.requests.skip(before).map((r) => r.path).toList();
      for (final path in [
        '/api/discovery/matches',
        '/api/discovery/trips',
        '/api/discovery/people',
        '/api/discovery/profile/me',
      ]) {
        expect(after.where((p) => p == path), hasLength(1), reason: path);
      }
      expect(after.where((p) => p == '/api/discovery/alerts'), isEmpty);
    });
  });

  group('the request budget', () {
    testWidgets('a cold Home reads each discovery section exactly once', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await _pumpHome(tester, backend);

      final discovery =
          backend.requests
              .where((r) => r.path.startsWith('/api/discovery'))
              .map((r) => r.path)
              .toList()
            ..sort();
      expect(discovery, [
        '/api/discovery/matches',
        '/api/discovery/people',
        '/api/discovery/profile/me',
        '/api/discovery/trips',
      ]);
    });

    testWidgets('a section far below the fold is not read until it is near', (
      tester,
    ) async {
      // A phone, not a tall window: Home's own sections fill the screen, so
      // listings and people lie a long way down.
      final backend = discoveryBackend();
      await _pumpHome(
        tester,
        backend,
        device: const DeviceProfile(name: 'short', size: Size(360, 480)),
      );

      expect(backend.to('GET', '/api/discovery/matches'), hasLength(1));
      expect(
        backend.to('GET', '/api/discovery/people'),
        isEmpty,
        reason: 'People is below the cache extent and must not be read yet',
      );

      await tester.drag(find.byType(ListView).first, const Offset(0, -3000));
      await tester.pumpAndSettle();

      expect(backend.to('GET', '/api/discovery/people'), hasLength(1));
    });
  });

  group('right to left', () {
    testWidgets('Home in Arabic lays out every section without overflow', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/matches',
          senderMatches([
            senderMatchGroup(5, [travelerCandidateFixture(101, name: 'كريم')]),
          ]),
        )
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'نادية')]),
        )
        ..on(
          'GET',
          '/api/discovery/people',
          discoveryPage([
            profileCardFixture(name: 'ليلى', routes: [usualRouteFixture()]),
          ]),
        )
        ..on(
          'GET',
          '/api/discovery/profile/me',
          FakeResponse(200, ownProfileFixture(showPrompt: true)),
        );

      await _pumpHome(tester, backend, locale: const Locale('ar'));

      expect(find.text('مطابقات لك'), findsOneWidget);
      expect(find.text('رحلات تنطلق قريبًا'), findsOneWidget);
      expect(find.text('مسافرون على Wassla'), findsOneWidget);
      expect(find.text('كن ظاهرًا على Wassla'), findsOneWidget);
      expect(tester.takeException(), isNull);
      // The chips start on the reading side: "All routes" is at the right edge.
      final all = tester.getTopRight(find.text('كل المسارات').first).dx;
      final first = tester
          .getTopRight(find.bySemanticsLabel('من فرنسا إلى الجزائر'))
          .dx;
      expect(all, greaterThan(first));
    });

    testWidgets('and in French at the narrowest phone width', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'Nadia')]),
        );

      await _pumpHome(
        tester,
        backend,
        locale: const Locale('fr'),
        device: const DeviceProfile(name: 'narrowest', size: Size(320, 3000)),
      );

      expect(find.text('Trajets au départ bientôt'), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}
