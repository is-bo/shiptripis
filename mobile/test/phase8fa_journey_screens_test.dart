/// Phase 8F-A through real screens, over the real client.
///
/// These deliberately do not stub repositories. What Phase 8F-A can get wrong
/// is the wire — a PATCH that never leaves, a leg sent without its id, an
/// idempotency key that changes on every retry — and a stubbed repository
/// proves none of it. So [FakeBackend] sits underneath the production
/// `ApiClient`, and every assertion is on the JSON that would have reached
/// Django.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/features/journeys/journey_edit_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

Map<String, dynamic> _place(
  int id,
  String name,
  String country, {
  String? iata,
  int? matching,
}) => {
  'id': id,
  'name': name,
  'display_label': iata == null ? name : '$name ($iata)',
  'place_type': iata == null ? 'locality' : 'airport',
  'iata_code': ?iata,
  'country_code': country,
  'parent_name': '',
  'matching_locality_id': matching ?? id,
  'matching_locality_name': name,
};

const _jijelId = 1;
const _algiersId = 2;
const _parisId = 3;
const _algId = 11;
const _cdgId = 12;

/// Jijel → Algiers by road, then Algiers → Paris by air, with the flight
/// proven. The shape the owner actually built on the device.
Map<String, dynamic> journeyFixture({
  bool editable = true,
  String? editBlockedCode,
  String status = 'draft',
  List<Map<String, dynamic>> proofs = const [],
}) => {
  'id': 7,
  'traveler_id': 42,
  'traveler_name': 'Amina Bouzid',
  'status': status,
  'notes': 'Driving to Algiers first',
  'editable': editable,
  'edit_blocked_code': editBlockedCode,
  'published_at': null,
  'start_place': _place(_jijelId, 'Jijel', 'DZ'),
  'destination_place': _place(_parisId, 'Paris', 'FR'),
  'start_location': null,
  'destination_location': null,
  'legs': [
    {
      'id': 101,
      'position': 0,
      'mode': 'DRIVE',
      'origin_place': _place(_jijelId, 'Jijel', 'DZ'),
      'destination_place': _place(
        _algId,
        'Houari Boumediene',
        'DZ',
        iata: 'ALG',
        matching: _algiersId,
      ),
      'depart_at': '2026-10-01T08:00:00Z',
      'arrive_at': '2026-10-01T13:00:00Z',
      'capacity_kg': '12.00',
      'flight_number': '',
      'has_approved_proof': false,
      'distance_meters': 300000,
      'proofs': const [],
    },
    {
      'id': 102,
      'position': 1,
      'mode': 'FLIGHT',
      'origin_place': _place(
        _algId,
        'Houari Boumediene',
        'DZ',
        iata: 'ALG',
        matching: _algiersId,
      ),
      'destination_place': _place(
        _cdgId,
        'Charles de Gaulle',
        'FR',
        iata: 'CDG',
        matching: _parisId,
      ),
      'depart_at': '2026-10-01T15:00:00Z',
      'arrive_at': '2026-10-01T18:00:00Z',
      'capacity_kg': '12.00',
      'flight_number': 'AH1006',
      'has_approved_proof': proofs.any((p) => p['status'] == 'approved'),
      'distance_meters': 1500000,
      'proofs': proofs,
    },
  ],
};

Map<String, dynamic> _approvedProof() => {
  'id': 900,
  'kind': 'boarding_pass',
  'content_type': 'image/png',
  'bytes': 2048,
  'status': 'approved',
  'reviewed_at': '2026-09-20T09:00:00Z',
  'rejection_reason': '',
};

/// Signs the fake session in, exactly as a cold start would.
Future<ProviderContainer> _signedIn(
  WidgetTester tester,
  FakeBackend backend,
) async {
  backend.on('GET', '/api/me', FakeResponse(200, meFixture()));
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  return container;
}

void main() {
  // -------------------------------------------------------------------------
  group('the edit affordance on journey detail', () {
    testWidgets('a draft the server says is editable offers Edit', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/journeys/7', FakeResponse(200, journeyFixture()))
        ..on(
          'GET',
          '/api/matches/compatible-requests',
          FakeResponse(200, {'candidates': []}),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      final button = find.widgetWithText(AppButton, l.journeyEditAction);
      expect(button, findsOneWidget);
      expect(tester.widget<AppButton>(button).onPressed, isNotNull);
    });

    testWidgets('a journey the server refuses shows the reason, not a gap', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(
            200,
            journeyFixture(
              editable: false,
              editBlockedCode: 'journey_not_editable',
              status: 'active',
            ),
          ),
        )
        ..on(
          'GET',
          '/api/matches/compatible-requests',
          FakeResponse(200, {'candidates': []}),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      // Present but inert, with the explanation beside it.
      final button = find.widgetWithText(AppButton, l.journeyEditAction);
      expect(button, findsOneWidget);
      expect(tester.widget<AppButton>(button).onPressed, isNull);
      expect(find.text(l.journeyEditBlockedStatus), findsOneWidget);
    });

    testWidgets('a dependent-state refusal names the sender, not the status', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(
            200,
            journeyFixture(
              editable: false,
              editBlockedCode: 'journey_has_dependent_state',
            ),
          ),
        )
        ..on(
          'GET',
          '/api/matches/compatible-requests',
          FakeResponse(200, {'candidates': []}),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      expect(find.text(l.journeyEditBlockedDependent), findsOneWidget);
    });

    testWidgets('the route summary names its stops', (tester) async {
      // Before Phase 8F-A this read the legacy `Location` fields, which are
      // null on every canonical journey — so the summary rendered blanks.
      final backend = FakeBackend()
        ..on('GET', '/api/journeys/7', FakeResponse(200, journeyFixture()))
        ..on(
          'GET',
          '/api/matches/compatible-requests',
          FakeResponse(200, {'candidates': []}),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Jijel'), findsWidgets);
      expect(find.textContaining('ALG'), findsWidgets);
      expect(find.textContaining('CDG'), findsWidgets);
    });
  });

  // -------------------------------------------------------------------------
  group('the edit screen', () {
    testWidgets('prepopulates every stop from the saved journey', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/journeys/7', FakeResponse(200, journeyFixture()));
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyEditScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Jijel'), findsWidgets);
      // The middle stop reads as the city, reached via its airport.
      expect(find.textContaining('ALG'), findsWidgets);
      expect(find.text('AH1006'), findsWidgets);
    });

    testWidgets('saving sends a PATCH carrying the whole chain with its ids', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/journeys/7', FakeResponse(200, journeyFixture()))
        ..handle(
          'PATCH',
          '/api/journeys/7',
          (_) => FakeResponse(200, {
            ...journeyFixture(),
            'route_change': {
              'legs_created': 0,
              'legs_updated': 2,
              'legs_removed': 0,
              'proofs_reset_for_review': 0,
              'proofs_discarded': 0,
            },
          }),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyEditScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('PATCH', '/api/journeys/7');
      expect(sent, isNotNull);
      expect(sent!.body['start_place_id'], _jijelId);
      expect(sent.body['destination_place_id'], _parisId);
      final legs = (sent.body['legs'] as List).cast<Map<String, dynamic>>();
      expect(legs, hasLength(2));
      // Identity travels, which is what lets the flight keep its proof.
      expect(legs.map((l) => l['id']), [101, 102]);
      expect(legs.map((l) => l['position']), [0, 1]);
      expect(legs[0]['origin_place_id'], _jijelId);
      expect(legs[0]['destination_place_id'], _algId);
      expect(legs[1]['origin_place_id'], _algId);
      expect(legs[1]['destination_place_id'], _cdgId);
      expect(legs[1]['flight_number'], 'AH1006');
    });

    testWidgets('a blocked journey explains itself instead of showing a form', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(
            200,
            journeyFixture(
              editable: false,
              editBlockedCode: 'journey_not_editable',
              status: 'active',
            ),
          ),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyEditScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      expect(find.text(l.journeyEditBlockedTitle), findsOneWidget);
      expect(find.text(l.journeyEditBlockedStatus), findsOneWidget);
      // No save button on a form that cannot be saved.
      expect(
        find.widgetWithText(AppButton, l.journeySaveChanges),
        findsNothing,
      );
    });

    testWidgets('a server refusal is explained, not shrugged at', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/journeys/7', FakeResponse(200, journeyFixture()))
        ..on(
          'PATCH',
          '/api/journeys/7',
          const FakeResponse(400, {
            'code': ['journey_leg_mode_unavailable'],
            'detail': ['Leg 0 cannot be driven between DZ and FR.'],
            'required_mode': ['FLIGHT'],
          }),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyEditScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
      await tester.pumpAndSettle();

      expect(find.textContaining(l.routeErrorModeUnavailable), findsWidgets);
    });

    testWidgets('a proof sent back for review is reported, not hidden', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(200, journeyFixture(proofs: [_approvedProof()])),
        )
        ..handle(
          'PATCH',
          '/api/journeys/7',
          (_) => FakeResponse(200, {
            ...journeyFixture(),
            'route_change': {
              'legs_created': 0,
              'legs_updated': 2,
              'legs_removed': 0,
              'proofs_reset_for_review': 1,
              'proofs_discarded': 0,
            },
          }),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const JourneyEditScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final l = await _catalogue(tester);
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
      await tester.pumpAndSettle();

      expect(
        find.textContaining(l.journeyEditSavedProofReset(1)),
        findsWidgets,
      );
    });
  });
}

/// Reads the English catalogue through a widget tree that is already pumped.
Future<L> _catalogue(WidgetTester tester) async {
  final context = tester.element(find.byType(Scaffold).first);
  return L.of(context);
}
