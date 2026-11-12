/// L2B: the person page, the member's own public profile, and route alerts.
///
/// The server holds every alert and every opt-in, so each test drives a small
/// stateful fake of it and asserts what the screen shows from what the server
/// then says, never from what the client assumed it sent.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/discovery/alerts_screen.dart';
import 'package:shiptrip/features/discovery/person_screen.dart';
import 'package:shiptrip/features/discovery/public_profile_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

/// A server that keeps the member's alerts between requests.
class _Alerts {
  final List<Map<String, dynamic>> rows = [];
  int _next = 1;

  void install(FakeBackend backend) {
    backend
      ..handle(
        'GET',
        '/api/discovery/alerts',
        (_) => FakeResponse(200, {'results': List.of(rows)}),
      )
      ..handle('POST', '/api/discovery/alerts', (r) {
        final subject = r.body['subject_profile_id'];
        final row = alertFixture(
          _next++,
          watches: r.body['watches'] as String,
          from: 'Paris',
          to: 'Algiers',
          subject: subject == null
              ? null
              : {'id': subject, 'display_name': 'Samira'},
        );
        rows.add(row);
        return FakeResponse(201, row);
      });
  }

  void allowDelete(FakeBackend backend, int id) =>
      backend.handle('DELETE', '/api/discovery/alerts/$id', (_) {
        rows.removeWhere((r) => r['id'] == id);
        return const FakeResponse(204, {});
      });
}

Map<String, dynamic> _person({
  List<Map<String, dynamic>> routes = const [],
  List<Map<String, dynamic>> trips = const [],
  List<Map<String, dynamic>> requests = const [],
}) => {
  'state': 'results',
  'profile': profileCardFixture(name: 'Samira', routes: routes),
  'trips': trips,
  'requests': requests,
};

/// Tall enough that the whole settings page is built, so a test reads what the
/// page says and not how far down it is.
const _tall = DeviceProfile(name: 'tall (412x2400)', size: Size(412, 2400));

void main() {
  group('the person page', () {
    testWidgets('shows the trust summary, usual routes and live trips', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(
            200,
            _person(
              routes: [usualRouteFixture()],
              trips: [tripCardFixture(11, name: 'Samira')],
            ),
          ),
        );
      _Alerts().install(backend);
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(find.text('Samira'), findsWidgets);
      expect(find.text('Identity verified'), findsOneWidget);
      expect(find.text('Usual routes'), findsOneWidget);
      expect(find.text("Samira's trips"), findsOneWidget);
      expect(find.text("Samira's parcels"), findsNothing);
      expect(
        find.textContaining('Message'),
        findsNothing,
        reason: 'chat begins inside a match, never from a profile',
      );
    });

    testWidgets('a sender follows a route with an alert on trips', (
      tester,
    ) async {
      final alerts = _Alerts();
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, _person(routes: [usualRouteFixture()])),
        );
      alerts.install(backend);
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/discovery/alerts')!;
      expect(sent.body, {
        'watches': 'trips',
        'origin_place_id': 1,
        'destination_place_id': 2,
        'subject_profile_id': 'p-1',
      });
      expect(find.text('Alert turned on'), findsOneWidget);
      expect(
        tester.widget<Switch>(find.byType(Switch)).value,
        isTrue,
        reason: 'the switch is on because the server now lists the alert',
      );
    });

    testWidgets('a traveler follows a sender on requests', (tester) async {
      final alerts = _Alerts();
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, _person(routes: [usualRouteFixture()])),
        );
      alerts.install(backend);
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
        role: RoleContext.traveler,
      );

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      expect(
        backend.lastTo('POST', '/api/discovery/alerts')!.body['watches'],
        'requests',
      );
    });

    testWidgets('an alert the server already holds shows on, and turns off', (
      tester,
    ) async {
      final alerts = _Alerts()
        ..rows.add(
          alertFixture(4, subject: {'id': 'p-1', 'display_name': 'Samira'}),
        );
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, _person(routes: [usualRouteFixture()])),
        );
      alerts
        ..install(backend)
        ..allowDelete(backend, 4);
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      expect(backend.to('DELETE', '/api/discovery/alerts/4'), hasLength(1));
      expect(find.text('Alert turned off'), findsOneWidget);
      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
    });

    testWidgets('an alert on someone else\'s route does not light the switch', (
      tester,
    ) async {
      final alerts = _Alerts()
        ..rows.add(
          alertFixture(4, subject: {'id': 'p-2', 'display_name': 'Other'}),
        )
        ..rows.add(alertFixture(5));
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, _person(routes: [usualRouteFixture()])),
        );
      alerts.install(backend);
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
    });

    testWidgets('a refused alert says why and leaves the switch off', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(200, _person(routes: [usualRouteFixture()])),
        )
        ..on(
          'POST',
          '/api/discovery/alerts',
          const FakeResponse(409, {'code': 'route_alert_limit_reached'}),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      expect(
        find.textContaining('maximum number of active alerts'),
        findsOneWidget,
      );
      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
    });

    testWidgets('with no usual routes it says so and offers no switch', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on('GET', '/api/discovery/people/p-1', FakeResponse(200, _person()));
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(find.text("Samira hasn't added usual routes."), findsOneWidget);
      expect(find.byType(Switch), findsNothing);
      expect(
        find.text('Samira has no live trips or open parcels right now.'),
        findsOneWidget,
      );
    });

    testWidgets('a profile that is gone is an empty state, not an error', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/gone',
          const FakeResponse(404, {'code': 'profile_not_found'}),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'gone'),
        backend,
      );

      expect(find.text('Profile unavailable'), findsOneWidget);
      expect(find.text('Try again'), findsNothing);
    });

    testWidgets('profiles switched off is a calm empty state', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          const FakeResponse(200, {'state': 'disabled'}),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(find.text('Not available right now'), findsOneWidget);
    });

    testWidgets('a failed read offers a retry that reads again', (
      tester,
    ) async {
      var failing = true;
      final backend = discoveryBackend()
        ..handle(
          'GET',
          '/api/discovery/people/p-1',
          (_) => failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : FakeResponse(200, _person()),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(find.text('Try again'), findsOneWidget);
      failing = false;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('Samira'), findsWidgets);
      expect(find.text('Try again'), findsNothing);
    });
  });

  group('the public profile settings', () {
    testWidgets('is off by default and says what turning it on shows', (
      tester,
    ) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      expect(find.text('What others see'), findsOneWidget);
      expect(find.text('Your first name'), findsOneWidget);
      expect(find.text('Never shown'), findsOneWidget);
      expect(find.text('Others can\'t find you.'), findsOneWidget);
      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
      expect(
        find.text('This is what others would see if you turn it on.'),
        findsOneWidget,
      );
    });

    testWidgets('turning it on sends the choice and shows the server answer', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'PUT',
          '/api/discovery/profile/me',
          FakeResponse(
            200,
            ownProfileFixture(state: 'visible', discoverable: true),
          ),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      expect(backend.lastTo('PUT', '/api/discovery/profile/me')!.body, {
        'is_discoverable': true,
      });
      expect(tester.widget<Switch>(find.byType(Switch)).value, isTrue);
      expect(find.text('Others can find you.'), findsOneWidget);
      expect(find.text('This is what others see right now.'), findsOneWidget);
    });

    testWidgets('a profile staff have hidden is told so, with no reason', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/profile/me',
          FakeResponse(
            200,
            ownProfileFixture(state: 'hidden', discoverable: true),
          ),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      expect(
        find.text('Your profile is not currently visible to others.'),
        findsOneWidget,
      );
    });

    testWidgets('a failed write keeps the old state and says so', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'PUT',
          '/api/discovery/profile/me',
          const FakeResponse(500, {'detail': 'boom'}),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      await tester.tap(find.byType(Switch));
      await tester.pumpAndSettle();

      expect(tester.widget<Switch>(find.byType(Switch)).value, isFalse);
      expect(find.byType(SnackBar), findsOneWidget);
    });

    testWidgets('adds a usual route from two picked cities', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'PUT',
          '/api/discovery/profile/me',
          FakeResponse(200, ownProfileFixture(routes: [usualRouteFixture()])),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
        extraRoutes: [
          stubPlacePicker([
            cityPlace(1, 'Paris', 'FR'),
            cityPlace(2, 'Algiers', 'DZ'),
          ]),
        ],
      );

      await tester.tap(find.text('Add a usual route'));
      await tester.pumpAndSettle();

      expect(backend.lastTo('PUT', '/api/discovery/profile/me')!.body, {
        'usual_routes': [
          {'origin_place_id': 1, 'destination_place_id': 2},
        ],
      });
      expect(find.textContaining('Paris'), findsWidgets);
    });

    testWidgets('backing out of the second city adds nothing', (tester) async {
      final backend = discoveryBackend();
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
        extraRoutes: [
          stubPlacePicker([cityPlace(1, 'Paris', 'FR')]),
        ],
      );

      await tester.tap(find.text('Add a usual route'));
      await tester.pumpAndSettle();

      expect(backend.to('PUT', '/api/discovery/profile/me'), isEmpty);
    });

    testWidgets('removes one route and keeps the others in order', (
      tester,
    ) async {
      final routes = [
        usualRouteFixture(),
        usualRouteFixture(from: 'Lyon', to: 'Oran'),
      ];
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/profile/me',
          FakeResponse(200, ownProfileFixture(routes: routes)),
        )
        ..on(
          'PUT',
          '/api/discovery/profile/me',
          FakeResponse(200, ownProfileFixture(routes: [routes.last])),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      await tester.tap(find.byIcon(Icons.delete_outline_rounded).first);
      await tester.pumpAndSettle();

      final sent = backend.lastTo('PUT', '/api/discovery/profile/me')!;
      expect(sent.body['usual_routes'], [
        {'origin_place_id': 1, 'destination_place_id': 2},
      ]);
    });

    testWidgets('at three routes Add gives way to the limit', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/profile/me',
          FakeResponse(
            200,
            ownProfileFixture(
              routes: [
                usualRouteFixture(),
                usualRouteFixture(from: 'Lyon', to: 'Oran'),
                usualRouteFixture(from: 'Lille', to: 'Setif'),
              ],
            ),
          ),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      expect(find.text('Add a usual route'), findsNothing);
      expect(
        find.text("You've added the maximum of three routes."),
        findsOneWidget,
      );
    });

    testWidgets('profiles switched off is a calm empty state', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/profile/me',
          FakeResponse(200, ownProfileFixture(state: 'disabled')),
        );
      await pumpDiscovery(
        tester,
        const PublicProfileScreen(),
        backend,
        device: _tall,
      );

      expect(find.text('Not available right now'), findsOneWidget);
      expect(find.byType(Switch), findsNothing);
    });
  });

  group('route alerts', () {
    testWidgets('an empty list says what an alert is and offers to add one', (
      tester,
    ) async {
      await pumpDiscovery(tester, const AlertsScreen(), discoveryBackend());

      expect(find.text('No route alerts yet'), findsOneWidget);
      expect(find.text('Add alert'), findsWidgets);
    });

    testWidgets('lists alerts by what they watch, and whom they follow', (
      tester,
    ) async {
      final alerts = _Alerts()
        ..rows.addAll([
          alertFixture(1),
          alertFixture(2, watches: 'requests', from: 'Lyon', to: 'Oran'),
          alertFixture(3, subject: {'id': 'p-9', 'display_name': 'Samira'}),
        ]);
      final backend = discoveryBackend();
      alerts.install(backend);
      await pumpDiscovery(tester, const AlertsScreen(), backend);

      expect(find.text('New trips'), findsOneWidget);
      expect(find.text('New parcels'), findsOneWidget);
      expect(find.text('Following Samira'), findsOneWidget);
      expect(
        find.text(
          'We send at most one notification per alert every few hours.',
        ),
        findsOneWidget,
      );
    });

    testWidgets(
      'removing an alert deletes it on the server and drops the row',
      (tester) async {
        final alerts = _Alerts()..rows.add(alertFixture(1));
        final backend = discoveryBackend();
        alerts
          ..install(backend)
          ..allowDelete(backend, 1);
        await pumpDiscovery(tester, const AlertsScreen(), backend);

        await tester.tap(
          find.bySemanticsLabel('Remove alert for Paris → Algiers'),
        );
        await tester.pumpAndSettle();

        expect(backend.to('DELETE', '/api/discovery/alerts/1'), hasLength(1));
        expect(find.text('Alert removed'), findsOneWidget);
        expect(find.text('No route alerts yet'), findsOneWidget);
      },
    );

    testWidgets('a trips alert opens Browse on that alert', (tester) async {
      final alerts = _Alerts()..rows.add(alertFixture(1));
      final backend = discoveryBackend();
      alerts.install(backend);
      await pumpDiscovery(tester, const AlertsScreen(), backend);

      await tester.tap(find.text('New trips'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at browse-trips'), findsOneWidget);
      expect(find.textContaining('alert: 1'), findsOneWidget);
    });

    testWidgets('a followed person opens their page', (tester) async {
      final alerts = _Alerts()
        ..rows.add(
          alertFixture(3, subject: {'id': 'p-9', 'display_name': 'Samira'}),
        );
      final backend = discoveryBackend();
      alerts.install(backend);
      await pumpDiscovery(tester, const AlertsScreen(), backend);

      await tester.tap(find.text('Following Samira'));
      await tester.pumpAndSettle();

      expect(find.text('at person {id: p-9} {}'), findsOneWidget);
    });

    testWidgets('adds an alert for two picked cities', (tester) async {
      final alerts = _Alerts();
      final backend = discoveryBackend();
      alerts.install(backend);
      await pumpDiscovery(
        tester,
        const AlertsScreen(),
        backend,
        extraRoutes: [
          stubPlacePicker([
            cityPlace(1, 'Paris', 'FR'),
            cityPlace(2, 'Algiers', 'DZ'),
          ]),
        ],
      );

      await tester.tap(find.bySemanticsLabel('Add alert').first);
      await tester.pumpAndSettle();
      expect(find.text('New route alert'), findsOneWidget);
      expect(
        tester
            .widget<AppButton>(find.widgetWithText(AppButton, 'Create alert'))
            .onPressed,
        isNull,
        reason: 'no cities yet',
      );

      await tester.tap(find.text('Choose a city').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Choose a city').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Create alert'));
      await tester.pumpAndSettle();

      expect(backend.lastTo('POST', '/api/discovery/alerts')!.body, {
        'watches': 'trips',
        'origin_place_id': 1,
        'destination_place_id': 2,
      });
      expect(find.text('New route alert'), findsNothing);
      expect(find.text('New trips'), findsOneWidget);
    });

    testWidgets('a failed read offers a retry', (tester) async {
      var failing = true;
      final backend = discoveryBackend()
        ..handle(
          'GET',
          '/api/discovery/alerts',
          (_) => failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : FakeResponse(200, {
                  'results': [alertFixture(1)],
                }),
        );
      await pumpDiscovery(tester, const AlertsScreen(), backend);

      expect(find.text('Try again'), findsOneWidget);
      failing = false;
      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(find.text('New trips'), findsOneWidget);
    });
  });
}
