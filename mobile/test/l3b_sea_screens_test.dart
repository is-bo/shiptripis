/// L3B through real screens, over the real client.
///
/// What is asserted is what a traveller experiences and what reaches Django:
/// Lille → Constantine can be built on a 360 px phone in Arabic with a ferry
/// in the middle, a failed list of ferry lines never stops anyone editing a
/// flight or a road leg, a refused ferry leg shows the server's reason on that
/// leg, and a staff pause never explains itself to the traveller.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/transport_rules.dart';
import 'package:shiptrip/features/journeys/journey_create_screen.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';
import 'package:shiptrip/features/journeys/leg_proof_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const _phone360 = DeviceProfile(
  name: 'phone (360x640)',
  size: Size(360, 640),
  viewPadding: EdgeInsets.only(top: 24, bottom: 24),
);

CanonicalPlace _city(int id, String name, String country) => CanonicalPlace(
  id: id,
  countryCode: country,
  type: CanonicalPlaceType.locality,
  name: name,
  displayLabel: name,
  parentName: '',
  parentAdminLevel: '',
  matchingLocalityId: id,
  matchingLocalityName: name,
);

final _lille = _city(1, 'Lille', 'FR');
final _marseille = _city(2, 'Marseille', 'FR');
final _algiers = _city(3, 'Algiers', 'DZ');
final _constantine = _city(4, 'Constantine', 'DZ');

Map<String, dynamic> _placeJson(CanonicalPlace p) => {
  'id': p.id,
  'name': p.name,
  'display_label': p.displayLabel,
  'place_type': 'locality',
  'country_code': p.countryCode,
  'parent_name': '',
  'matching_locality_id': p.matchingLocalityId,
  'matching_locality_name': p.name,
};

Map<String, dynamic> _crossings({bool enabled = true}) => {
  'enabled': enabled,
  'crossings': [
    {
      'origin': {'id': _marseille.id},
      'destination': {'id': _algiers.id},
    },
    {
      'origin': {'id': _algiers.id},
      'destination': {'id': _marseille.id},
    },
  ],
};

/// Lille → Marseille → Algiers → Constantine, every field filled so the form is
/// valid the moment the ferry is chosen.
JourneyRouteDraft _draft() {
  final draft = JourneyRouteDraft()
    ..setOrigin(_lille)
    ..setDestination(_constantine)
    ..insertStopAfter(0, _marseille)
    ..insertStopAfter(1, _algiers);
  final start = DateTime(2026, 10, 1, 8);
  for (var i = 0; i < draft.segments.length; i++) {
    draft.setSegmentDeparture(i, start.add(Duration(hours: i * 8)));
    draft.setSegmentArrival(i, start.add(Duration(hours: i * 8 + 4)));
    draft.segments[i].capacity.text = '10.00';
    if (draft.segments[i].mode.isFlight) {
      draft.segments[i].flightNumber.text = 'AH1006';
    }
  }
  return draft;
}

Map<String, dynamic> _leg(
  int id,
  int position,
  String mode,
  CanonicalPlace from,
  CanonicalPlace to, {
  String proofState = 'not_required',
  bool proofRequired = false,
}) => {
  'id': id,
  'position': position,
  'mode': mode,
  'origin_place': _placeJson(from),
  'destination_place': _placeJson(to),
  'depart_at': '2026-10-01T${8 + position * 4}:00:00Z',
  'arrive_at': '2026-10-01T${10 + position * 4}:00:00Z',
  'capacity_kg': '10.00',
  'capacity_volume_l': position == 1 ? 120 : null,
  'capacity_parcels': position == 1 ? 3 : null,
  'flight_number': mode == 'FLIGHT' ? 'AH1006' : '',
  'has_approved_proof': proofState == 'approved',
  'proof_required': proofRequired,
  'proof_state': proofState,
  'distance_meters': 100000,
  'proofs': const <Object>[],
};

Map<String, dynamic> _journey({
  String status = 'active',
  Map<String, dynamic>? pause,
  String ferryProof = 'approved',
  String secondMode = 'SEA',
}) => {
  'id': 7,
  'traveler_id': 42,
  'traveler_name': 'Amina Bouzid',
  'status': status,
  'notes': '',
  'editable': false,
  'edit_blocked_code': 'journey_not_editable',
  'start_place': _placeJson(_lille),
  'destination_place': _placeJson(_constantine),
  'legs': [
    _leg(100, 0, 'DRIVE', _lille, _marseille),
    _leg(
      101,
      1,
      secondMode,
      _marseille,
      _algiers,
      proofRequired: secondMode != 'DRIVE',
      proofState: secondMode == 'DRIVE' ? 'not_required' : ferryProof,
    ),
    _leg(102, 2, 'DRIVE', _algiers, _constantine),
  ],
  'stops': [
    {
      'position': 1,
      'accepts_pickup': true,
      'accepts_dropoff': false,
      'handover_note': 'Café by the terminal',
      'window_start': '2026-10-01T12:00:00Z',
      'window_end': '2026-10-01T13:00:00Z',
    },
  ],
  'refused_categories': ['electronics'],
  'accepts_fragile': false,
  'pause': ?pause,
};

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

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

/// The create screen over the real client, with a draft already built.
Future<(FakeBackend, JourneyRouteDraft)> _pumpCreate(
  WidgetTester tester, {
  required FakeResponse crossings,
  Locale locale = const Locale('en'),
  DeviceProfile device = _phone360,
}) async {
  final backend = FakeBackend()
    ..on('GET', '/api/geography/sea-crossings', crossings);
  final container = await _signedIn(tester, backend);
  // The screen owns the draft it is handed and disposes it with itself.
  final draft = _draft();
  await pumpApp(
    tester,
    JourneyCreateScreen(debugDraft: draft, debugNow: () => DateTime(2026, 9)),
    container: container,
    locale: locale,
    device: device,
    routed: true,
    extraRoutes: [
      GoRoute(
        name: Routes.journeyDetail,
        path: '/journeys/:id',
        builder: (_, _) => const Scaffold(body: Text('detail')),
      ),
    ],
  );
  await tester.pumpAndSettle();
  return (backend, draft);
}

Future<void> _scrollTo(WidgetTester tester, Finder finder) async {
  await tester.scrollUntilVisible(
    finder,
    200,
    scrollable: find.byType(Scrollable).first,
  );
  await tester.pump();
}

void main() {
  // -------------------------------------------------------------------------
  group('building Lille to Constantine', () {
    for (final locale in const ['en', 'ar']) {
      testWidgets('on a 360 px phone in $locale, with the ferry in the middle', (
        tester,
      ) async {
        final (backend, draft) = await _pumpCreate(
          tester,
          crossings: FakeResponse(200, _crossings()),
          locale: Locale(locale),
        );
        final l = _l(tester);

        // The ferry is offered on the Marseille → Algiers leg, next to flight.
        final ferry = find.text(l.journeyModeSea);
        await _scrollTo(tester, ferry);
        expect(ferry, findsOneWidget);
        await tester.tap(ferry);
        await tester.pumpAndSettle();
        expect(draft.segments[1].mode, LegMode.sea);
        expect(find.text(l.routeSeaTicketNote), findsOneWidget);

        // Nothing overflows and nothing scrolls sideways, all the way down.
        for (var i = 0; i < 12; i++) {
          await tester.drag(
            find.byType(Scrollable).first,
            const Offset(0, -400),
          );
          await tester.pump();
        }
        await tester.pumpAndSettle();
        expect(tester.takeException(), isNull);
        expect(
          find.byWidgetPredicate(
            // A text field scrolls its own line sideways; the page must not.
            (w) =>
                w is Scrollable &&
                w.axis == Axis.horizontal &&
                w.restorationId != 'editable',
          ),
          findsNothing,
        );

        // The last field clears the pinned Save button.
        final notes = find.byType(AppTextField).last;
        final save = find.widgetWithText(AppButton, l.journeySaveDraft);
        expect(
          tester.getRect(notes).bottom,
          lessThanOrEqualTo(tester.getRect(save).top + 0.5),
        );

        // And the save puts the ferry on the wire with its cities.
        backend.handle(
          'POST',
          '/api/journeys',
          (_) => FakeResponse(201, _journey()),
        );
        await tester.tap(save);
        await tester.pumpAndSettle();
        final sent = backend.lastTo('POST', '/api/journeys')!.body;
        final legs = (sent['legs'] as List).cast<Map<String, dynamic>>();
        expect(legs.map((x) => x['mode']), ['DRIVE', 'SEA', 'DRIVE']);
        expect(legs[1]['origin_place_id'], _marseille.id);
        expect(legs[1]['destination_place_id'], _algiers.id);
        expect(legs[1]['flight_number'], '');
        expect(sent['stops'], isEmpty);
        expect(sent['refused_categories'], isEmpty);
        expect(sent['accepts_fragile'], isTrue);
      });
    }

    testWidgets(
      'a switch that is off says so in one line and offers no ferry',
      (tester) async {
        await _pumpCreate(
          tester,
          crossings: FakeResponse(200, _crossings(enabled: false)),
        );
        final l = _l(tester);

        await _scrollTo(tester, find.text(l.routeSeaSwitchedOff));
        expect(find.text(l.routeSeaSwitchedOff), findsOneWidget);
        expect(find.text(l.journeyModeSea), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('a failed list never blocks the form and can be retried', (
      tester,
    ) async {
      final (backend, draft) = await _pumpCreate(
        tester,
        crossings: const FakeResponse(500, {'detail': 'boom'}),
      );
      final l = _l(tester);

      expect(find.text(l.routeSeaLinesFailedTitle), findsOneWidget);
      // Flight and road legs still edit.
      expect(draft.modesFor(0), {LegMode.flight, LegMode.drive});
      draft.setSegmentMode(0, LegMode.flight);
      expect(draft.segments[0].mode, LegMode.flight);

      backend.on(
        'GET',
        '/api/geography/sea-crossings',
        FakeResponse(200, _crossings()),
      );
      await tester.tap(find.text(l.actionRetry));
      await tester.pumpAndSettle();

      expect(backend.to('GET', '/api/geography/sea-crossings'), hasLength(2));
      expect(find.text(l.routeSeaLinesFailedTitle), findsNothing);
      expect(draft.modesFor(1), contains(LegMode.sea));
    });

    testWidgets('a refused ferry leg shows the server reason on that leg', (
      tester,
    ) async {
      final (backend, draft) = await _pumpCreate(
        tester,
        crossings: FakeResponse(200, _crossings()),
      );
      final l = _l(tester);
      draft.setSegmentMode(1, LegMode.sea);
      await tester.pumpAndSettle();

      // Serializer-raised refusals arrive with every value in a list.
      backend.handle(
        'POST',
        '/api/journeys',
        (_) => const FakeResponse(400, {
          'code': ['journey_leg_mode_unavailable'],
          'detail': ['no active sea crossing joins these two ports'],
          'leg_position': ['1'],
          'declared_mode': ['SEA'],
          'reason': ['sea_crossing_unavailable'],
        }),
      );
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveDraft));
      await tester.pumpAndSettle();

      expect(draft.seaProblemFor(1), SeaRefusal.noCrossing);
      await _scrollTo(tester, find.text(l.routeSeaRefusedNoCrossing));
      expect(find.text(l.routeSeaRefusedNoCrossing), findsOneWidget);
    });

    testWidgets('what I carry and a stop\'s handover options are sent', (
      tester,
    ) async {
      final (backend, draft) = await _pumpCreate(
        tester,
        crossings: FakeResponse(200, _crossings()),
      );
      final l = _l(tester);
      draft.setSegmentMode(1, LegMode.sea);
      draft
        ..setCarries(carryableCategories.first, carries: false)
        ..setAcceptsFragile(false)
        ..setStopOptions(1, acceptsDropoff: false);
      draft.stops[1].note.text = 'Café by the terminal';
      await tester.pumpAndSettle();

      backend.handle(
        'POST',
        '/api/journeys',
        (_) => FakeResponse(201, _journey()),
      );
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveDraft));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/journeys')!.body;
      expect(sent['refused_categories'], ['documents']);
      expect(sent['accepts_fragile'], isFalse);
      final stops = (sent['stops'] as List).cast<Map<String, dynamic>>();
      expect(stops, hasLength(1));
      expect(stops.single['position'], 1);
      expect(stops.single['accepts_dropoff'], isFalse);
      expect(stops.single['handover_note'], 'Café by the terminal');
    });
  });

  // -------------------------------------------------------------------------
  group('the route editor, mode by mode', () {
    testWidgets(
      'road and flight legs offer those two; the water leg adds Ferry',
      (tester) async {
        await _pumpCreate(tester, crossings: FakeResponse(200, _crossings()));
        final l = _l(tester);

        // Lille → Marseille and Algiers → Constantine: road or air, no ferry.
        expect(find.text(l.journeyModeDrive), findsWidgets);
        await _scrollTo(tester, find.text(l.journeyModeSea));
        expect(
          find.text(l.journeyModeSea),
          findsOneWidget,
          reason: 'one water leg',
        );
        expect(find.text(l.journeyModeFlight), findsWidgets);
      },
    );

    testWidgets('the optional limits sit behind "More capacity options"', (
      tester,
    ) async {
      final (_, draft) = await _pumpCreate(
        tester,
        crossings: FakeResponse(200, _crossings()),
      );
      final l = _l(tester);
      expect(find.text(l.routeVolumeLabel), findsNothing);

      final more = find.text(l.routeCapacityMore).first;
      await _scrollTo(tester, more);
      await tester.tap(more);
      await tester.pumpAndSettle();
      expect(find.text(l.routeVolumeLabel), findsOneWidget);
      expect(find.text(l.routeParcelsLabel), findsOneWidget);

      await tester.enterText(
        find.widgetWithText(AppTextField, l.routeVolumeLabel),
        '120',
      );
      expect(draft.segments.first.volume.text, '120');
    });

    testWidgets(
      'a stop\'s handover options open in a sheet and edit the draft',
      (tester) async {
        final (_, draft) = await _pumpCreate(
          tester,
          crossings: FakeResponse(200, _crossings()),
        );
        final l = _l(tester);

        final open = find.text(l.routeHandoverAction).at(1);
        await _scrollTo(tester, open);
        await tester.tap(open);
        await tester.pumpAndSettle();
        expect(
          find.text(l.routeHandoverSheetTitle('Marseille')),
          findsOneWidget,
        );
        expect(find.text(l.routeHandoverNoteSeen), findsOneWidget);

        await tester.tap(find.text(l.routeHandoverPickupLabel));
        await tester.pumpAndSettle();
        expect(draft.stops[1].acceptsPickup, isFalse);

        await tester.tap(find.text(l.actionDone));
        await tester.pumpAndSettle();
        expect(find.text(l.routeHandoverDropoffs), findsWidgets);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets('the last kind of item cannot be switched off', (tester) async {
      final (_, draft) = await _pumpCreate(
        tester,
        crossings: FakeResponse(200, _crossings()),
      );
      final l = _l(tester);
      for (final category in carryableCategories.skip(1)) {
        draft.setCarries(category, carries: false);
      }
      await tester.pumpAndSettle();
      await _scrollTo(tester, find.text(l.routeCarryLastOne));
      expect(find.text(l.routeCarryLastOne), findsOneWidget);
      draft.setCarries(carryableCategories.first, carries: false);
      expect(
        draft.refusedCategories,
        isNot(contains(carryableCategories.first)),
      );
    });
  });

  // -------------------------------------------------------------------------
  group('the ticket screen', () {
    Future<void> pumpProof(
      WidgetTester tester, {
      required int legId,
      String secondMode = 'SEA',
      Locale locale = const Locale('en'),
    }) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(
            200,
            _journey(
              status: 'draft',
              ferryProof: 'missing',
              secondMode: secondMode,
            ),
          ),
        );
      final container = await _signedIn(tester, backend);
      await pumpRouted(
        tester,
        LegProofScreen(journeyId: 7, legId: legId),
        container: container,
        locale: locale,
        device: _phone360,
      );
      await tester.pumpAndSettle();
    }

    testWidgets('a ferry leg asks for a ferry ticket and says what to show', (
      tester,
    ) async {
      await pumpProof(tester, legId: 101);
      final l = _l(tester);
      expect(find.text(l.proofExplainerSea), findsOneWidget);
      expect(find.text(l.proofChecklistSea), findsOneWidget);
      expect(find.text(l.proofExplainerFlight), findsNothing);
      expect(find.text(l.proofStatusMissing), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('a flight leg keeps the boarding-pass copy', (tester) async {
      await pumpProof(tester, legId: 101, secondMode: 'FLIGHT');
      final l = _l(tester);
      expect(find.text(l.proofExplainerFlight), findsOneWidget);
      expect(find.text(l.proofChecklistFlight), findsOneWidget);
      expect(find.text(l.proofExplainerSea), findsNothing);
    });

    testWidgets('a road leg needs nothing, and the server says so', (
      tester,
    ) async {
      await pumpProof(tester, legId: 100);
      final l = _l(tester);
      expect(find.text(l.proofDriveNotRequired), findsOneWidget);
      expect(find.text(l.proofExplainerSea), findsNothing);
    });

    testWidgets('renders in Arabic on a 360 px phone without overflow', (
      tester,
    ) async {
      await pumpProof(tester, legId: 101, locale: const Locale('ar'));
      expect(tester.takeException(), isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('pausing a journey', () {
    Future<FakeBackend> pumpDetail(
      WidgetTester tester, {
      Map<String, dynamic>? pause,
      Locale locale = const Locale('en'),
    }) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(200, _journey(pause: pause)),
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
        locale: locale,
        device: _phone360,
      );
      await tester.pumpAndSettle();
      return backend;
    }

    testWidgets('shows the ferry, the limits and what the owner set', (
      tester,
    ) async {
      await pumpDetail(tester, pause: {'paused': false});
      final l = _l(tester);

      expect(find.textContaining('120 L'), findsOneWidget);
      expect(
        find.textContaining(l.journeyCapacityParcelsValue(3)),
        findsOneWidget,
      );
      await _scrollTo(tester, find.text('Café by the terminal'));
      expect(find.text('Café by the terminal'), findsOneWidget);
      expect(find.text(l.journeyCarryRefuses('Electronics')), findsOneWidget);
      expect(find.text(l.journeyCarryNoFragile), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('the owner pauses after being told what stays as it is', (
      tester,
    ) async {
      final backend = await pumpDetail(tester, pause: {'paused': false});
      final l = _l(tester);
      backend.handle('POST', '/api/journeys/7/pause', (_) {
        backend.on(
          'GET',
          '/api/journeys/7',
          FakeResponse(
            200,
            _journey(
              pause: {
                'paused': true,
                'paused_at': '2026-10-02T09:00:00Z',
                'paused_by_staff': false,
              },
            ),
          ),
        );
        return FakeResponse(200, _journey());
      });

      await _scrollTo(tester, find.text(l.journeyPauseAction));
      await tester.tap(find.text(l.journeyPauseAction));
      await tester.pumpAndSettle();
      expect(find.text(l.journeyPauseConfirmBody), findsOneWidget);
      await tester.tap(find.text(l.journeyPauseAction).last);
      await tester.pumpAndSettle();

      expect(backend.to('POST', '/api/journeys/7/pause'), hasLength(1));
      // The page was scrolled to the button; the banner is at the top.
      await tester.drag(find.byType(Scrollable).first, const Offset(0, 3000));
      await tester.pumpAndSettle();
      expect(find.text(l.journeyPausedBannerTitle), findsOneWidget);
      expect(find.text(l.journeyResumeAction), findsOneWidget);
    });

    testWidgets('a staff pause has no Resume and never gives a reason', (
      tester,
    ) async {
      await pumpDetail(
        tester,
        pause: {
          'paused': true,
          'paused_at': '2026-10-02T09:00:00Z',
          'paused_by_staff': true,
        },
      );
      final l = _l(tester);

      expect(find.text(l.journeyPausedBannerTitle), findsOneWidget);
      expect(find.text(l.journeyPausedStaffBody), findsOneWidget);
      expect(find.text(l.journeyResumeAction), findsNothing);
      expect(find.text(l.journeyPauseAction), findsNothing);
    });

    testWidgets('renders in Arabic on a 360 px phone without overflow', (
      tester,
    ) async {
      await pumpDetail(
        tester,
        pause: {'paused': true, 'paused_by_staff': false},
        locale: const Locale('ar'),
      );
      expect(tester.takeException(), isNull);
    });
  });
}
