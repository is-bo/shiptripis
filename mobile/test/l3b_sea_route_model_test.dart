/// L3B: sea legs, stop options and "what I carry" on the route model, with no
/// widget in sight.
///
/// The rule under test is who decides. The server owns the list of ferry
/// lines, so the draft offers Sea only for a pair that list joins while the
/// owner's switch is on, never rewrites a ferry leg the traveller already has
/// because that list changed, and never lets a failed list stop anyone editing
/// a flight or a road leg.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart' show TransportModeDraft;
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/delivery_request.dart' show ItemCategory;
import 'package:shiptrip/domain/journey.dart';
import 'package:shiptrip/domain/sea_crossings.dart';
import 'package:shiptrip/domain/transport_mode.dart';
import 'package:shiptrip/domain/transport_rules.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';

int _nextId = 100;

CanonicalPlace _city(String name, String country) {
  final id = _nextId++;
  return CanonicalPlace(
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
}

CanonicalPlace _airport(String name, String iata, CanonicalPlace serves) =>
    CanonicalPlace(
      id: _nextId++,
      countryCode: serves.countryCode,
      type: CanonicalPlaceType.airport,
      name: name,
      displayLabel: '$name ($iata)',
      parentName: serves.name,
      parentAdminLevel: '',
      iataCode: iata,
      matchingLocalityId: serves.matchingLocalityId,
      matchingLocalityName: serves.name,
    );

late CanonicalPlace marseille;
late CanonicalPlace algiers;
late CanonicalPlace lille;
late CanonicalPlace constantine;
late CanonicalPlace algAirport;

SeaCrossings _lines({bool enabled = true}) => SeaCrossings(
  enabled: enabled,
  lines: {(marseille.id, algiers.id), (algiers.id, marseille.id)},
);

const RouteCopy _copy = (
  departRequired: 'depart-required',
  departNotAfterPrevious: 'depart-order',
  departBeforePreviousArrival: 'depart-before-arrival',
  arriveRequired: 'arrive-required',
  arriveBeforeDepart: 'arrive-order',
  capacityInvalid: 'capacity',
  volumeInvalid: 'volume',
  parcelsInvalid: 'parcels',
  windowIncomplete: 'window-incomplete',
  windowOrder: 'window-order',
  windowOutside: 'window-outside',
  required: 'required',
);

void _complete(JourneyRouteDraft draft) {
  final start = DateTime(2026, 10, 1, 8);
  for (var i = 0; i < draft.segments.length; i++) {
    draft.setSegmentDeparture(i, start.add(Duration(hours: i * 6)));
    draft.setSegmentArrival(i, start.add(Duration(hours: i * 6 + 3)));
    draft.segments[i].capacity.text = '10.00';
    if (draft.segments[i].mode.isFlight) {
      draft.segments[i].flightNumber.text = 'AH1006';
    }
  }
}

/// Lille → Marseille by road, Marseille → Algiers by ferry, Algiers →
/// Constantine by road: the journey this package exists to make possible.
JourneyRouteDraft _lilleToConstantine({SeaCrossings? crossings}) {
  final draft = JourneyRouteDraft()
    ..setSeaCrossings(crossings ?? _lines())
    ..setOrigin(lille)
    ..setDestination(constantine)
    ..insertStopAfter(0, marseille)
    ..insertStopAfter(1, algiers);
  // The crossing is the sensible way over the water; a switch that is off
  // leaves the derived flight in place.
  if (draft.modesFor(1).contains(LegMode.sea)) {
    draft.setSegmentMode(1, LegMode.sea);
  }
  return draft;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() {
    marseille = _city('Marseille', 'FR');
    algiers = _city('Algiers', 'DZ');
    lille = _city('Lille', 'FR');
    constantine = _city('Constantine', 'DZ');
    algAirport = _airport('Houari Boumediene', 'ALG', algiers);
  });

  group('the wire speaks SEA', () {
    test('parses and prints in uppercase like the other modes', () {
      expect(TransportMode.parse('SEA'), TransportMode.sea);
      expect(TransportMode.sea.wire, 'SEA');
      expect(TransportModeDraft.sea.wire, 'SEA');
    });

    test('a leg reads its ticket need from the server, not from its mode', () {
      final sea = JourneyLeg.fromJson({
        'id': 1,
        'position': 0,
        'mode': 'SEA',
        'proof_required': true,
        'proof_state': 'pending',
        'capacity_volume_l': 120,
        'capacity_parcels': 4,
      });
      expect(sea.mode, TransportMode.sea);
      expect(sea.proofRequired, isTrue);
      expect(sea.proofState, LegProofState.pending);
      expect(sea.needsProof, isTrue);
      expect(sea.capacityVolumeLitres, 120);
      expect(sea.capacityParcels, 4);

      // Missing fields mean "not required": a road leg never blocks publishing.
      final road = JourneyLeg.fromJson({
        'id': 2,
        'position': 1,
        'mode': 'DRIVE',
      });
      expect(road.proofRequired, isFalse);
      expect(road.needsProof, isFalse);

      final approved = JourneyLeg.fromJson({
        'id': 3,
        'position': 2,
        'mode': 'SEA',
        'proof_required': true,
        'proof_state': 'approved',
      });
      expect(approved.needsProof, isFalse);
    });

    test('a proof state this build has never heard of is not approval', () {
      expect(
        LegProofState.parse('under_review_by_aliens'),
        LegProofState.unknown,
      );
      final leg = JourneyLeg.fromJson({
        'id': 1,
        'position': 0,
        'mode': 'SEA',
        'proof_required': true,
        'proof_state': 'under_review_by_aliens',
      });
      expect(leg.needsProof, isTrue);
    });

    test('a journey carries its stops, refusals and pause', () {
      final journey = Journey.fromJson({
        'id': 9,
        'traveler_id': 1,
        'status': 'active',
        'legs': const [],
        'stops': [
          {
            'position': 2,
            'accepts_pickup': false,
            'accepts_dropoff': true,
            'handover_note': 'Café by the terminal',
            'window_start': '2026-10-01T10:00:00Z',
            'window_end': '2026-10-01T11:00:00Z',
          },
          {'position': 0, 'accepts_pickup': true, 'accepts_dropoff': false},
        ],
        'refused_categories': ['electronics', 'clothing'],
        'accepts_fragile': false,
        'pause': {
          'paused': true,
          'paused_at': '2026-10-02T09:00:00Z',
          'paused_by_staff': true,
        },
      });
      expect(journey.stops.map((s) => s.position), [0, 2]);
      expect(journey.stops.last.acceptsPickup, isFalse);
      expect(journey.stops.last.hasHandoverDetail, isTrue);
      expect(journey.refusedCategories, ['electronics', 'clothing']);
      expect(journey.acceptsFragile, isFalse);
      expect(journey.isPaused, isTrue);
      expect(journey.isPausedByStaff, isTrue);
    });

    test('a journey that says nothing about any of it takes everything', () {
      final journey = Journey.fromJson({
        'id': 9,
        'traveler_id': 1,
        'status': 'draft',
        'legs': const [],
      });
      expect(journey.stops, isEmpty);
      expect(journey.refusedCategories, isEmpty);
      expect(journey.acceptsFragile, isTrue);
      expect(journey.isPaused, isFalse);
    });
  });

  group('the ferry lines', () {
    test('read as ordered pairs, one per direction', () {
      final lines = SeaCrossings.fromJson({
        'enabled': true,
        'crossings': [
          {
            'origin': {'id': 1},
            'destination': {'id': 2},
          },
        ],
      });
      expect(lines.offers(1, 2), isTrue);
      expect(lines.offers(2, 1), isFalse, reason: 'the return is its own row');
    });

    test('a switch that is off offers nothing but still knows the line', () {
      final lines = _lines(enabled: false);
      expect(lines.offers(marseille.id, algiers.id), isFalse);
      expect(lines.hasLine(marseille.id, algiers.id), isTrue);
    });
  });

  group('when Sea is offered', () {
    test('only for a listed pair of cities while the switch is on', () {
      expect(availableModes(marseille, algiers, crossings: _lines()), {
        LegMode.flight,
        LegMode.sea,
      });
      expect(
        availableModes(marseille, algiers, crossings: _lines(enabled: false)),
        {LegMode.flight},
      );
      expect(availableModes(lille, constantine, crossings: _lines()), {
        LegMode.flight,
      });
    });

    test('never for an airport, whatever the list says', () {
      expect(
        availableModes(marseille, algAirport, crossings: _lines()),
        isNot(contains(LegMode.sea)),
      );
    });

    test(
      'not before the list is known, and flight and road never wait for it',
      () {
        expect(availableModes(marseille, algiers), {LegMode.flight});
        expect(availableModes(lille, marseille), {
          LegMode.flight,
          LegMode.drive,
        });
      },
    );

    test('Lille to Constantine builds: road, ferry, road', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);

      // Marseille → Algiers offers Sea next to Flight; the French road leg
      // and the Algerian road leg keep what they were derived as.
      expect(draft.modesFor(0), {LegMode.flight, LegMode.drive});
      expect(draft.modesFor(1), {LegMode.flight, LegMode.sea});
      expect(draft.modesFor(2), {LegMode.flight, LegMode.drive});
      draft.setSegmentMode(1, LegMode.sea);
      expect(draft.segments[1].mode, LegMode.sea);
      expect(draft.segments[0].mode, LegMode.drive);
    });

    test(
      'the one reason worth a line: the switch is the only thing missing',
      () {
        final draft = _lilleToConstantine(crossings: _lines(enabled: false));
        addTearDown(draft.dispose);
        expect(draft.seaSwitchedOffFor(1), isTrue);
        expect(
          draft.seaSwitchedOffFor(0),
          isFalse,
          reason: 'no line, nothing to explain',
        );
      },
    );
  });

  group('a ferry leg is never silently turned into something else', () {
    test('a list that arrives late does not rewrite the leg', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);

      draft.setSeaCrossings(null);
      expect(draft.segments[1].mode, LegMode.sea);
      expect(draft.modesFor(1), contains(LegMode.sea));
      expect(draft.seaProblemFor(1), isNull, reason: 'unknown is not refusal');
    });

    test(
      'a switch turned off shows its reason on the leg and keeps the leg',
      () {
        final draft = _lilleToConstantine();
        addTearDown(draft.dispose);
        draft.setSegmentMode(1, LegMode.sea);

        draft.setSeaCrossings(_lines(enabled: false));
        expect(draft.segments[1].mode, LegMode.sea);
        expect(draft.seaProblemFor(1), SeaRefusal.switchedOff);
        _complete(draft);
        expect(draft.isValid(_copy), isFalse, reason: 'it would be refused');
      },
    );

    test('a deactivated line shows the server reason on that leg', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);

      draft.setSeaCrossings(const SeaCrossings(enabled: true, lines: {}));
      expect(draft.seaProblemFor(1), SeaRefusal.noCrossing);
    });

    test("the server's own reason is kept until something changes", () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);

      draft.markSeaRefused(1, 'sea_endpoint_not_port_city');
      expect(draft.seaProblemFor(1), SeaRefusal.notPortCity);

      draft.setSegmentMode(1, LegMode.flight);
      expect(draft.seaProblemFor(1), isNull);
    });

    test('a reason this build does not know changes nothing', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);
      draft.markSeaRefused(1, 'something_new');
      expect(draft.seaProblemFor(1), isNull);
    });

    test('moving an end to an airport takes the ferry off that leg', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);

      draft.setStop(2, algAirport);

      expect(draft.segments[1].mode, isNot(LegMode.sea));
    });
  });

  group('what is sent for a ferry leg', () {
    test('its cities, not the airports the stops were reached by', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);
      _complete(draft);

      final legs = draft.toLegDrafts();
      expect(legs[1].mode, TransportModeDraft.sea);
      expect(legs[1].originPlaceId, marseille.id);
      expect(legs[1].destinationPlaceId, algiers.id);
      expect(legs[1].flightNumber, isEmpty);
    });

    test('optional limits go as numbers, and as null when empty', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setSegmentMode(1, LegMode.sea);
      _complete(draft);
      draft.segments[1].volume.text = '120';
      draft.segments[1].parcels.text = '4';

      final legs = draft.toLegDrafts();
      expect(legs[1].toJson()['capacity_volume_l'], 120);
      expect(legs[1].toJson()['capacity_parcels'], 4);
      expect(legs[0].toJson()['capacity_volume_l'], isNull);
      expect(legs[0].toJson().containsKey('capacity_volume_l'), isTrue);
    });

    test('limits that are not whole numbers in range block the form', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      _complete(draft);
      expect(draft.isValid(_copy), isTrue);

      draft.segments[0].volume.text = '0';
      expect(draft.isValid(_copy), isFalse);
      draft.segments[0].volume.text = '200001';
      expect(draft.isValid(_copy), isFalse);
      draft.segments[0].volume.text = '200000';
      draft.segments[0].parcels.text = '10001';
      expect(draft.isValid(_copy), isFalse);
      draft.segments[0].parcels.text = '10000';
      expect(draft.isValid(_copy), isTrue);
    });

    test('the weight ceiling is the server\'s 20,000 kg', () {
      expect(maxJourneyLegCapacityKg, 20000);
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      _complete(draft);
      draft.segments[0].capacity.text = '20000.00';
      expect(draft.isValid(_copy), isTrue);
      draft.segments[0].capacity.text = '20000.01';
      expect(draft.isValid(_copy), isFalse);
    });
  });

  group('stop options', () {
    test('a route nobody configured sends no stops at all', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      expect(draft.toStopDrafts(), isEmpty);
    });

    test('only a stop that differs from the default is sent', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      draft.setStopOptions(1, acceptsPickup: false);
      draft.stops[2].note.text = '  Café by the terminal ';

      final sent = draft.toStopDrafts();
      expect(sent.map((s) => s.position), [1, 2]);
      expect(sent[0].acceptsPickup, isFalse);
      expect(sent[0].acceptsDropoff, isTrue);
      expect(sent[1].handoverNote, 'Café by the terminal');
    });

    test(
      'the first stop follows its pickup switch and the last its drop-off',
      () {
        final draft = _lilleToConstantine();
        addTearDown(draft.dispose);
        draft.setStopOptions(0, acceptsPickup: false);
        draft.setStopOptions(3, acceptsDropoff: false);

        final sent = {for (final s in draft.toStopDrafts()) s.position: s};
        expect(sent[0]!.acceptsPickup, isFalse);
        expect(
          sent[0]!.acceptsDropoff,
          isFalse,
          reason: 'never a contradiction',
        );
        expect(sent[3]!.acceptsPickup, isFalse);
        expect(sent[3]!.acceptsDropoff, isFalse);
        expect(draft.stopAcceptsDropoff(0), isFalse);
        expect(draft.stopAcceptsPickup(3), isFalse);
      },
    );

    test('a window needs both ends, in order, inside the stop\'s own time', () {
      final draft = _lilleToConstantine();
      addTearDown(draft.dispose);
      _complete(draft);
      // Stop 1 is reached at 11:00 and left at 14:00.
      expect(draft.stopIssuesFor(1, _copy).window, isNull);

      draft.setStopOptions(1, windowStart: DateTime(2026, 10, 1, 11, 30));
      expect(draft.stopIssuesFor(1, _copy).window, 'window-incomplete');

      draft.setStopOptions(1, windowEnd: DateTime(2026, 10, 1, 11, 0));
      expect(draft.stopIssuesFor(1, _copy).window, 'window-order');

      draft.setStopOptions(1, windowEnd: DateTime(2026, 10, 1, 15, 0));
      expect(draft.stopIssuesFor(1, _copy).window, 'window-outside');
      expect(draft.isValid(_copy), isFalse);

      draft.setStopOptions(1, windowEnd: DateTime(2026, 10, 1, 13, 30));
      expect(draft.stopIssuesFor(1, _copy).window, isNull);
      expect(draft.isValid(_copy), isTrue);

      draft.setStopOptions(1, clearWindow: true);
      expect(draft.toStopDrafts(), isEmpty);
    });

    test('an edit starts from what the journey already says', () {
      final journey = Journey.fromJson({
        'id': 1,
        'traveler_id': 1,
        'status': 'draft',
        'start_place': _json(lille),
        'destination_place': _json(marseille),
        'legs': [
          {
            'id': 11,
            'position': 0,
            'mode': 'DRIVE',
            'origin_place': _json(lille),
            'destination_place': _json(marseille),
            'depart_at': '2026-10-01T08:00:00Z',
            'arrive_at': '2026-10-01T14:00:00Z',
            'capacity_kg': '10.00',
            'capacity_volume_l': 80,
          },
        ],
        'stops': [
          {
            'position': 1,
            'accepts_pickup': true,
            'accepts_dropoff': false,
            'handover_note': 'Gate B',
          },
        ],
        'refused_categories': ['electronics'],
        'accepts_fragile': false,
      });
      final draft = JourneyRouteDraft.fromJourney(journey);
      addTearDown(draft.dispose);

      expect(draft.segments[0].volume.text, '80');
      expect(draft.stops[1].acceptsDropoff, isFalse);
      expect(draft.stops[1].note.text, 'Gate B');
      expect(draft.refusedCategories, {ItemCategory.electronics});
      expect(draft.acceptsFragile, isFalse);
      expect(draft.refusedCategoryWire, ['electronics']);
    });
  });

  group('what I carry', () {
    test('everything is on until something is switched off', () {
      final draft = JourneyRouteDraft();
      addTearDown(draft.dispose);
      expect(draft.refusedCategoryWire, isEmpty);
      expect(draft.acceptsFragile, isTrue);
    });

    test('a refusal goes as the server spells it', () {
      final draft = JourneyRouteDraft();
      addTearDown(draft.dispose);
      draft
        ..setCarries(ItemCategory.smallBox, carries: false)
        ..setCarries(ItemCategory.electronics, carries: false);
      expect(draft.refusedCategoryWire, ['small_box', 'electronics']);
      draft.setCarries(ItemCategory.smallBox, carries: true);
      expect(draft.refusedCategoryWire, ['electronics']);
    });

    test('the last category cannot be switched off', () {
      final draft = JourneyRouteDraft();
      addTearDown(draft.dispose);
      for (final category in carryableCategories) {
        draft.setCarries(category, carries: false);
      }
      expect(
        draft.refusedCategories,
        hasLength(carryableCategories.length - 1),
      );
      expect(
        draft.refusedCategories,
        isNot(contains(carryableCategories.last)),
      );
    });
  });
}

Map<String, dynamic> _json(CanonicalPlace p) => {
  'id': p.id,
  'name': p.name,
  'display_label': p.displayLabel,
  'place_type': 'locality',
  'country_code': p.countryCode,
  'parent_name': '',
  'matching_locality_id': p.matchingLocalityId,
  'matching_locality_name': p.name,
};
