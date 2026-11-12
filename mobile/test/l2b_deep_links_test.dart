/// L2B: the two discovery channels, from the push payload and from the bell.
///
/// A route alert is somebody else's trip or request, so it must open Browse
/// and never the member's own journey. "I can carry this" is the sender's own
/// request. Both reach the same screens by push, by the inbox row and by the
/// live socket.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/features/notifications/notifications_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';

Map<String, dynamic> _row(
  int id,
  String channel,
  Map<String, dynamic> payload,
) => {
  'id': id,
  'channel': channel,
  'payload': payload,
  'read_at': null,
  'created_at': '2026-11-12T09:00:00Z',
};

FakeBackend _inbox(List<Map<String, dynamic>> rows) => discoveryBackend()
  ..on(
    'GET',
    '/api/notifications',
    FakeResponse(200, {'count': rows.length, 'next': null, 'results': rows}),
  )
  ..handle(
    'POST',
    '/api/notifications/1/read',
    (_) => const FakeResponse(204, {}),
  );

void main() {
  group('pushLocation', () {
    test('a route alert on a trip opens Browse trips with it in focus', () {
      final uri = Uri.parse(
        pushLocation({
          'channel': 'discovery.route_alert',
          'alert_id': '4',
          'journey_id': '11',
        })!,
      );

      expect(uri.path, '/discover/trips');
      expect(uri.queryParameters, {'alert': '4', 'focus': '11'});
    });

    test('a route alert on a request opens Browse requests', () {
      final uri = Uri.parse(
        pushLocation({
          'channel': 'discovery.route_alert',
          'alert_id': '4',
          'request_id': '31',
        })!,
      );

      expect(uri.path, '/discover/requests');
      expect(uri.queryParameters, {'alert': '4', 'focus': '31'});
    });

    test('a route alert never opens the member\'s own journey', () {
      final location = pushLocation({
        'channel': 'discovery.route_alert',
        'journey_id': '11',
      })!;

      expect(location, isNot(startsWith('/journeys')));
      expect(Uri.parse(location).path, '/discover/trips');
    });

    test('a route alert with nothing to focus opens the alert list', () {
      expect(
        pushLocation({'channel': 'discovery.route_alert', 'alert_id': '4'}),
        '/profile/alerts',
      );
    });

    test(
      'an interested traveler opens that request with the trip in focus',
      () {
        expect(
          pushLocation({
            'channel': 'discovery.traveler_interested',
            'request_id': '31',
            'journey_id': '11',
          }),
          '/requests/31/discovery?journey=11',
        );
      },
    );

    test('an interested traveler without a trip opens the request', () {
      expect(
        pushLocation({
          'channel': 'discovery.traveler_interested',
          'request_id': '31',
        }),
        '/requests/31',
      );
    });

    test('an interested traveler without a request opens the inbox', () {
      expect(
        pushLocation({'channel': 'discovery.traveler_interested'}),
        '/notifications',
      );
    });

    test('a malformed id is treated as absent', () {
      expect(
        pushLocation({
          'channel': 'discovery.route_alert',
          'journey_id': '-3',
          'request_id': 'abc',
        }),
        '/profile/alerts',
      );
    });
  });

  group('the inbox destination', () {
    test('both channels are known, not "other"', () {
      expect(
        NotificationChannel.parse('discovery.route_alert'),
        NotificationChannel.discoveryRouteAlert,
      );
      expect(
        NotificationChannel.parse('discovery.traveler_interested'),
        NotificationChannel.discoveryTravelerInterested,
      );
    });

    test('a route alert carries the alert and what triggered it', () {
      final n = AppNotification.fromJson(
        _row(1, 'discovery.route_alert', {'alert_id': 4, 'journey_id': 11}),
      );

      expect(
        n.destination,
        isA<OpenRouteAlert>()
            .having((d) => d.alertId, 'alert', 4)
            .having((d) => d.journeyId, 'journey', 11)
            .having((d) => d.requestId, 'request', isNull),
      );
    });

    test('an interested traveler without a trip falls back to the request', () {
      final n = AppNotification.fromJson(
        _row(1, 'discovery.traveler_interested', {'request_id': 31}),
      );

      expect(n.destination, isA<OpenRequest>());
      expect((n.destination! as OpenRequest).requestId, 31);
    });

    test('an interested traveler with nothing to open has no destination', () {
      final n = AppNotification.fromJson(
        _row(1, 'discovery.traveler_interested', const {}),
      );

      expect(n.destination, isNull);
    });
  });

  group('live events', () {
    test('both only refresh the bell, never a deal or a request', () {
      for (final type in [
        'discovery.route_alert',
        'discovery.traveler_interested',
      ]) {
        expect(
          resourcesForLiveEvent(type, {'request_id': 31, 'journey_id': 11}),
          {const LiveResource.unread(), const LiveResource.notifications()},
          reason: type,
        );
      }
    });
  });

  group('the bell inbox', () {
    testWidgets('names both channels and opens Browse from a route alert', (
      tester,
    ) async {
      final backend = _inbox([
        _row(1, 'discovery.route_alert', {'alert_id': 4, 'journey_id': 11}),
        _row(2, 'discovery.traveler_interested', {
          'request_id': 31,
          'journey_id': 11,
        }),
      ]);
      await pumpDiscovery(tester, const NotificationsScreen(), backend);

      expect(find.text('New on a route you follow'), findsOneWidget);
      expect(find.text('A traveler can carry your parcel'), findsOneWidget);

      await tester.tap(find.text('New on a route you follow'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at browse-trips'), findsOneWidget);
      expect(find.textContaining('alert: 4'), findsOneWidget);
      expect(find.textContaining('focus: 11'), findsOneWidget);
    });

    testWidgets('an interested traveler opens Find Travelers on that trip', (
      tester,
    ) async {
      final backend = _inbox([
        _row(2, 'discovery.traveler_interested', {
          'request_id': 31,
          'journey_id': 11,
        }),
      ]);
      await pumpDiscovery(tester, const NotificationsScreen(), backend);

      await tester.tap(find.text('A traveler can carry your parcel'));
      await tester.pumpAndSettle();

      expect(
        find.text('at request-discovery {id: 31} {journey: 11}'),
        findsOneWidget,
      );
    });
  });
}
