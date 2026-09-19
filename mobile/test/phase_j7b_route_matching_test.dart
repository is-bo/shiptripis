/// Phase J7B — the published request's route, and the arrival a Journey leg
/// needs before it can ever be matched.
///
/// **The empty route.** A published V1 request's route is its two canonical
/// places. The request detail, the Deliveries row and the Home row drew it
/// from the sender's *optional* preferred meeting points instead, and since
/// Phase 8F-B most requests have none — so the route card rendered empty and
/// the list rows showed a bare arrow. The J7A detail tests used a fixture with
/// places and no meeting points, which is exactly the owner's case, and never
/// looked at the route.
///
/// **The arrival.** The traveller's route editor labelled a leg's arrival
/// "Optional". Matching compares that arrival with the sender's deadline, so a
/// Journey written without one was published and then matched nobody. It is
/// now required here and on the server.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/features/deliveries/deliveries_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/journeys/journey_create_screen.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';
import 'package:shiptrip/features/requests/request_detail_screen.dart';
import 'package:shiptrip/features/requests/request_labels.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures — the server's own shape (`ParcelRequestSerializer._place_summary`)
// ---------------------------------------------------------------------------

Map<String, dynamic> _locality(int id, String name, String country) => {
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'locality',
  'iata_code': null,
  'country_code': country,
  'parent_name': null,
  'matching_locality_id': id,
  'matching_locality_name': name,
};

Map<String, dynamic> _airport(
  int id,
  String name,
  String iata,
  String country, {
  required int servedId,
  required String servedName,
}) => {
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'airport',
  'iata_code': iata,
  'country_code': country,
  'parent_name': null,
  'matching_locality_id': servedId,
  'matching_locality_name': servedName,
};

Map<String, dynamic> _meetingPoint(int id, String label) => {
  'id': id,
  'kind': 'address',
  'public_label': 'Near $label',
  'private_label': label,
  'city': 'Algiers',
  'country_code': 'DZ',
  'latitude': '36.7700',
  'longitude': '3.0600',
  'precision': 'exact',
};

/// A published request exactly as `GET /api/parcels/<id>` serves it after the
/// owner's flow: canonical places, and no preferred meeting point at either
/// end.
Map<String, dynamic> _published({
  String status = 'open',
  Object? pickupPlace,
  Object? deliveryPlace,
  Object? pickupLocation,
  Object? deliveryLocation,
  int schemaVersion = 3,
}) => {
  'id': 77,
  'sender_id': 42,
  'target_traveler_id': null,
  'kind': 'delivery',
  'status': status,
  'schema_version': schemaVersion,
  'title': 'Documents for Paris',
  'description': 'A sealed folder of documents.',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'actual_weight_kg': '2.50',
  'declared_value_eur_cents': 5000,
  'sender_proposed_reward_eur_cents': 4000,
  'boost_eur_cents': 0,
  'total_offered_reward_eur_cents': 4000,
  'ready_window_start': '2026-10-01T09:00:00Z',
  'ready_window_end': '2026-10-02T16:00:00Z',
  'deadline_at': '2026-10-04T09:00:00Z',
  'media': <Object>[],
  'item_photo_media_id': null,
  'pickup_location': pickupLocation,
  'delivery_location': deliveryLocation,
  'pickup_place': pickupPlace,
  'delivery_place': deliveryPlace,
};

final _algiers = _locality(11, 'Algiers', 'DZ');
final _paris = _locality(22, 'Paris', 'FR');
final _alg = _airport(
  33,
  'Houari Boumediene',
  'ALG',
  'DZ',
  servedId: 11,
  servedName: 'Algiers',
);

final L _en = lookupL(const Locale('en'));

DeliveryRequest _decode(Map<String, dynamic> json) =>
    DeliveryRequest.fromJson(json);

FakeBackend _detailBackend(Map<String, dynamic> request) => FakeBackend()
  ..on('GET', '/api/me', FakeResponse(200, meFixture()))
  ..on('GET', '/api/parcels/77', FakeResponse(200, request))
  ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
  ..on(
    'GET',
    '/api/parcels/77/pricing',
    FakeResponse(404, {'code': 'not_found', 'detail': 'n/a'}),
  );

Future<L> _pumpDetail(
  WidgetTester tester,
  Map<String, dynamic> request, {
  Locale locale = const Locale('en'),
}) async {
  final backend = _detailBackend(request);
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  await pumpApp(
    tester,
    const RequestDetailScreen(requestId: 77),
    container: container,
    locale: locale,
  );
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(RequestDetailScreen)));
}

RouteSummary _routeSummary(WidgetTester tester) =>
    tester.widget<RouteSummary>(find.byType(RouteSummary));

/// The two list screens a sender sees their requests on. Each reads only the
/// routes it needs; the request list is the one that matters here.
Future<void> _pumpList(
  WidgetTester tester,
  Widget screen, {
  Locale locale = const Locale('en'),
}) async {
  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..on('GET', '/api/deals', FakeResponse(200, <Object>[]))
    ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
    ..on('GET', '/api/journeys', FakeResponse(200, <Object>[]))
    ..on(
      'GET',
      '/api/notifications/unread-count',
      FakeResponse(200, {'unread': 0}),
    )
    ..on(
      'GET',
      '/api/parcels',
      FakeResponse(200, [
        _published(pickupPlace: _algiers, deliveryPlace: _paris),
      ]),
    );
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  await pumpApp(tester, screen, container: container, locale: locale);
  await tester.pumpAndSettle();
}

void main() {
  // -------------------------------------------------------------------------
  group('the route is the canonical places', () {
    test('the decoder keeps both places from the server payload', () {
      final request = _decode(
        _published(pickupPlace: _algiers, deliveryPlace: _paris),
      );
      expect(request.pickupLocation, isNull);
      expect(request.deliveryLocation, isNull);
      expect(request.pickupPlace?.id, 11);
      expect(request.deliveryPlace?.id, 22);
      expect(request.isCanonical, isTrue);
    });

    test('labels come from the places when there is no meeting point', () {
      final request = _decode(
        _published(pickupPlace: _algiers, deliveryPlace: _paris),
      );
      expect(requestHasRoute(request), isTrue);
      expect(requestPickupLabel(_en, request), 'Algiers');
      expect(requestDeliveryLabel(_en, request), 'Paris');
    });

    test('an airport the sender chose carries its own code, and no other', () {
      final request = _decode(
        _published(pickupPlace: _alg, deliveryPlace: _paris),
      );
      expect(requestPickupLabel(_en, request), 'Algiers · ALG');
      // A locality never grows an airport code it was not given.
      expect(requestDeliveryLabel(_en, request), 'Paris');
    });

    test('an airport the catalogue has no served city for keeps its name', () {
      final request = _decode(
        _published(
          pickupPlace: {
            ..._alg,
            'matching_locality_id': null,
            'matching_locality_name': null,
          },
          deliveryPlace: _paris,
        ),
      );
      expect(requestPickupLabel(_en, request), 'Houari Boumediene (ALG)');
    });

    test('a meeting point never replaces the place it sits inside', () {
      final request = _decode(
        _published(
          pickupPlace: _algiers,
          deliveryPlace: _paris,
          pickupLocation: _meetingPoint(5, '12 Rue Didouche Mourad'),
        ),
      );
      expect(requestPickupLabel(_en, request), 'Algiers');
    });

    test('a legacy row with no place falls back to its coarse location', () {
      final request = _decode(
        _published(
          schemaVersion: 2,
          pickupLocation: _meetingPoint(5, '12 Rue Didouche Mourad'),
          deliveryLocation: _meetingPoint(6, '3 Rue de Rivoli'),
        ),
      );
      expect(requestHasRoute(request), isTrue);
      expect(requestPickupLabel(_en, request), 'Near 12 Rue Didouche Mourad');
    });

    test('a historical row with no route at all is not given one', () {
      final request = _decode(_published(schemaVersion: 1));
      expect(requestHasRoute(request), isFalse);
      expect(requestPickupLabel(_en, request), '—');
    });
  });

  // -------------------------------------------------------------------------
  group('request detail shows the route', () {
    for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
      testWidgets('with no meeting point, in ${locale.languageCode}', (
        tester,
      ) async {
        final l = await _pumpDetail(
          tester,
          _published(pickupPlace: _algiers, deliveryPlace: _paris),
          locale: locale,
        );

        final route = _routeSummary(tester);
        expect(route.from, 'Algiers');
        expect(route.to, 'Paris');
        expect(find.text('Algiers'), findsOneWidget);
        expect(find.text('Paris'), findsOneWidget);
        expect(find.text(l.requestRouteNotRecorded), findsNothing);
        expect(tester.takeException(), isNull);
      });
    }

    for (final status in const [
      'open',
      'matched',
      'in_transit',
      'delivered',
      'completed',
      'cancelled',
    ]) {
      testWidgets('at status $status', (tester) async {
        await _pumpDetail(
          tester,
          _published(
            status: status,
            pickupPlace: _algiers,
            deliveryPlace: _paris,
          ),
        );
        final route = _routeSummary(tester);
        expect((route.from, route.to), ('Algiers', 'Paris'));
      });
    }

    testWidgets('an airport endpoint is named with its code', (tester) async {
      await _pumpDetail(
        tester,
        _published(pickupPlace: _alg, deliveryPlace: _paris),
      );
      expect(_routeSummary(tester).from, 'Algiers · ALG');
    });

    testWidgets('meeting points are shown as detail inside the route', (
      tester,
    ) async {
      final l = await _pumpDetail(
        tester,
        _published(
          pickupPlace: _algiers,
          deliveryPlace: _paris,
          pickupLocation: _meetingPoint(5, '12 Rue Didouche Mourad'),
        ),
      );
      expect(_routeSummary(tester).from, 'Algiers');
      expect(find.text(l.requestPickupLocation), findsOneWidget);
      expect(find.text('12 Rue Didouche Mourad'), findsOneWidget);
      expect(find.text(l.requestDeliveryLocation), findsNothing);
    });

    testWidgets('a historical request without a route says so honestly', (
      tester,
    ) async {
      final l = await _pumpDetail(tester, _published(schemaVersion: 1));
      expect(find.byType(RouteSummary), findsNothing);
      expect(find.text(l.requestRouteNotRecorded), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  group('the request rows name the route too', () {
    testWidgets('Deliveries', (tester) async {
      await _pumpList(tester, const DeliveriesScreen());
      expect(find.byType(RouteSummary), findsWidgets);
      final summary = tester.widget<RouteSummary>(
        find.byType(RouteSummary).first,
      );
      expect(summary.from, 'Algiers');
      expect(summary.to, 'Paris');
    });

    testWidgets('Deliveries in Arabic reads right to left', (tester) async {
      await _pumpList(
        tester,
        const DeliveriesScreen(),
        locale: const Locale('ar'),
      );
      expect(find.byType(RouteSummary), findsWidgets);
      final summary = tester.widget<RouteSummary>(
        find.byType(RouteSummary).first,
      );
      expect(summary.from, 'Algiers');
      expect(summary.to, 'Paris');
      final algiersPos = tester.getTopLeft(find.text('Algiers'));
      final parisPos = tester.getTopLeft(find.text('Paris'));
      expect(
        algiersPos.dx > parisPos.dx,
        isTrue,
        reason: 'Origin (Algiers) appears on the right in Arabic RTL',
      );
    });

    testWidgets('Home', (tester) async {
      await _pumpList(tester, const HomeScreen());
      expect(find.byType(RouteSummary), findsWidgets);
      final summary = tester.widget<RouteSummary>(
        find.byType(RouteSummary).first,
      );
      expect(summary.from, 'Algiers');
      expect(summary.to, 'Paris');
    });
  });

  // -------------------------------------------------------------------------
  group('a Journey leg needs an arrival', () {
    const copy = (
      departRequired: 'depart-required',
      departNotAfterPrevious: 'depart-order',
      departBeforePreviousArrival: 'depart-before-arrival',
      arriveRequired: 'arrive-required',
      arriveBeforeDepart: 'arrive-order',
      capacityInvalid: 'capacity',
      required: 'required',
    );

    CanonicalPlace place(Map<String, dynamic> json) =>
        CanonicalPlace.fromJson(json);

    JourneyRouteDraft draft() {
      final d = JourneyRouteDraft()
        ..setOrigin(place(_alg))
        ..setDestination(
          place(
            _airport(
              44,
              'Charles de Gaulle',
              'CDG',
              'FR',
              servedId: 22,
              servedName: 'Paris',
            ),
          ),
        );
      d.setSegmentDeparture(0, DateTime(2026, 10, 2, 10));
      d.segments[0].capacity.text = '10';
      d.segments[0].flightNumber.text = 'AH1000';
      return d;
    }

    test('without one the leg is not valid, and says why', () {
      final d = draft();
      expect(d.issuesFor(0, copy).arrive, 'arrive-required');
      expect(d.isValid(copy), isFalse);
    });

    test('with one the leg is valid', () {
      final d = draft()..setSegmentArrival(0, DateTime(2026, 10, 2, 13));
      expect(d.issuesFor(0, copy).arrive, isNull);
      expect(d.isValid(copy), isTrue);
    });

    test('an arrival before departure is still its own message', () {
      final d = draft()..setSegmentArrival(0, DateTime(2026, 10, 2, 9));
      expect(d.issuesFor(0, copy).arrive, 'arrive-order');
    });

    testWidgets('the server refusal for an arrival-less leg is explained', (
      tester,
    ) async {
      await pumpApp(tester, const SizedBox());
      final context = tester.element(find.byType(SizedBox));
      final l = L.of(context);
      final error = ApiException(
        kind: ApiFailureKind.conflict,
        statusCode: 409,
        code: const ApiErrorCode('journey_leg_arrival_required'),
        serverDetail: 'Leg 0 needs an arrival time before publication.',
      );
      expect(
        journeyRouteFailure(context, error),
        l.journeyErrorLegArrivalRequired,
      );
    });
  });
}
