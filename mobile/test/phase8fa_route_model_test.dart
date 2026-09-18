/// Phase 8F-A: the route model, without a widget in sight.
///
/// The finding these exist for is a single sentence: a traveller with
/// Jijel → Paris who wanted Jijel → Algiers → Paris had to delete Paris to get
/// there. So the first group is that exact sequence, asserted on the model
/// rather than described in a comment.
///
/// The mode group is written as country pairs on purpose. The rule is about
/// road networks, not about Algeria being special, and the same code has to
/// keep France ↔ Germany driveable while refusing Jijel ↔ Marseille.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart' show TransportModeDraft;
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/journey.dart';
import 'package:shiptrip/domain/transport_rules.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';

// ---------------------------------------------------------------------------
// Catalogue fixtures
// ---------------------------------------------------------------------------

int _nextId = 1;

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

/// An airport resolves to the city it serves, which is what makes
/// "CDG then Paris" the same stop twice rather than a leg.
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

late CanonicalPlace jijel;
late CanonicalPlace algiers;
late CanonicalPlace oran;
late CanonicalPlace paris;
late CanonicalPlace marseille;
late CanonicalPlace madrid;
late CanonicalPlace berlin;
late CanonicalPlace gjl;
late CanonicalPlace alg;
late CanonicalPlace cdg;
late CanonicalPlace mad;

void _buildCatalogue() {
  jijel = _city('Jijel', 'DZ');
  algiers = _city('Algiers', 'DZ');
  oran = _city('Oran', 'DZ');
  paris = _city('Paris', 'FR');
  marseille = _city('Marseille', 'FR');
  madrid = _city('Madrid', 'ES');
  berlin = _city('Berlin', 'DE');
  gjl = _airport('Jijel Ferhat Abbas', 'GJL', jijel);
  alg = _airport('Houari Boumediene', 'ALG', algiers);
  cdg = _airport('Charles de Gaulle', 'CDG', paris);
  mad = _airport('Barajas', 'MAD', madrid);
}

const RouteCopy _copy = (
  departRequired: 'depart-required',
  departNotAfterPrevious: 'depart-order',
  departBeforePreviousArrival: 'depart-before-arrival',
  arriveRequired: 'arrive-required',
  arriveBeforeDepart: 'arrive-order',
  capacityInvalid: 'capacity',
  required: 'required',
);

/// Fills in everything a segment needs so validation is about the route,
/// not about blank fields.
void _completeSegments(JourneyRouteDraft draft, {DateTime? from}) {
  final start = from ?? DateTime(2026, 10, 1, 8);
  for (var i = 0; i < draft.segments.length; i++) {
    final segment = draft.segments[i];
    draft.setSegmentDeparture(i, start.add(Duration(hours: i * 6)));
    draft.setSegmentArrival(i, start.add(Duration(hours: i * 6 + 3)));
    segment.capacity.text = '10.00';
    if (segment.mode.isFlight) segment.flightNumber.text = 'AH1006';
  }
}

List<String> _stopNames(JourneyRouteDraft draft) =>
    draft.stops.map((s) => s.place.name).toList();

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(_buildCatalogue);

  // -------------------------------------------------------------------------
  group('the finding: inserting a stop between two others', () {
    test('Jijel to Paris starts as one segment', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);

      expect(_stopNames(draft), ['Jijel', 'Paris']);
      expect(draft.segments, hasLength(1));
      addTearDown(draft.dispose);
    });

    test('Algiers goes in the middle without Paris coming out', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);

      draft.insertStopAfter(0, algiers);

      expect(_stopNames(draft), ['Jijel', 'Algiers', 'Paris']);
      // The destination is untouched — the whole point of the change.
      expect(draft.destination!.place.name, 'Paris');
      expect(draft.segments, hasLength(2));
      addTearDown(draft.dispose);
    });

    test('a second stop goes in without disturbing the first', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);

      draft.insertStopAfter(1, oran);

      expect(_stopNames(draft), ['Jijel', 'Algiers', 'Oran', 'Paris']);
      expect(draft.segments, hasLength(3));
      addTearDown(draft.dispose);
    });

    test('order follows where the stop was inserted, not when', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, oran);

      // Inserted before Oran, though added after it.
      draft.insertStopAfter(0, algiers);

      expect(_stopNames(draft), ['Jijel', 'Algiers', 'Oran', 'Paris']);
      addTearDown(draft.dispose);
    });

    test('removing a middle stop rejoins the route', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);

      draft.removeStop(1);

      expect(_stopNames(draft), ['Jijel', 'Paris']);
      expect(draft.segments, hasLength(1));
      addTearDown(draft.dispose);
    });

    test('an endpoint is not removable as if it were a stopover', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);

      draft
        ..removeStop(0)
        ..removeStop(2);

      expect(_stopNames(draft), ['Jijel', 'Algiers', 'Paris']);
      addTearDown(draft.dispose);
    });

    test('changing a middle stop leaves both ends alone', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);

      draft.setStop(1, oran);

      expect(_stopNames(draft), ['Jijel', 'Oran', 'Paris']);
      addTearDown(draft.dispose);
    });

    test('an intermediate stop can be reordered', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);
      draft.insertStopAfter(1, oran);

      draft.moveStop(2, earlier: true);

      expect(_stopNames(draft), ['Jijel', 'Oran', 'Algiers', 'Paris']);
      addTearDown(draft.dispose);
    });

    test('a reorder cannot push an endpoint out of position', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);

      draft.moveStop(1, earlier: true);

      expect(_stopNames(draft), ['Jijel', 'Algiers', 'Paris']);
      addTearDown(draft.dispose);
    });

    test('the leg chain is always connected end to end', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);
      draft.setStopAirport(1, alg);
      draft.setStopAirport(2, cdg);
      _completeSegments(draft);

      final legs = draft.toLegDrafts();

      expect(legs.map((l) => l.position), [0, 1]);
      for (var i = 0; i < legs.length - 1; i++) {
        expect(legs[i].destinationPlaceId, legs[i + 1].originPlaceId);
      }
      addTearDown(draft.dispose);
    });
  });

  // -------------------------------------------------------------------------
  group('modes follow what is physically possible', () {
    test('Algeria to France cannot be driven', () {
      expect(driveIsAvailable('DZ', 'FR'), isFalse);
      expect(availableModes(jijel, marseille), {LegMode.flight});
    });

    test('France to Algeria cannot be driven either', () {
      expect(availableModes(paris, algiers), {LegMode.flight});
    });

    test('Algerian domestic legs can be driven', () {
      expect(availableModes(jijel, algiers), {LegMode.flight, LegMode.drive});
    });

    test('France to Germany and France to Spain stay driveable', () {
      expect(availableModes(paris, berlin), contains(LegMode.drive));
      expect(availableModes(marseille, madrid), contains(LegMode.drive));
    });

    test('an undeclared country fails closed', () {
      expect(driveIsAvailable('DZ', 'MA'), isFalse);
      expect(driveIsAvailable('', 'FR'), isFalse);
    });

    test('the editor will not accept a drive across the boundary', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(marseille);

      draft.setSegmentMode(0, LegMode.drive);

      expect(draft.segments.first.mode, LegMode.flight);
      expect(draft.segmentMustFly(0), isTrue);
      addTearDown(draft.dispose);
    });

    test('a domestic segment accepts a drive', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(algiers);

      draft.setSegmentMode(0, LegMode.drive);

      expect(draft.segments.first.mode, LegMode.drive);
      expect(draft.segmentMustFly(0), isFalse);
      addTearDown(draft.dispose);
    });

    test('defaults help without inventing an impossible mode', () {
      expect(defaultModeFor(jijel, algiers), LegMode.drive);
      expect(defaultModeFor(paris, berlin), LegMode.drive);
      expect(defaultModeFor(alg, cdg), LegMode.flight);
      expect(defaultModeFor(jijel, paris), LegMode.flight);
    });

    test('a stop change that crosses the boundary re-derives the mode', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(algiers);
      draft.setSegmentMode(0, LegMode.drive);
      expect(draft.segments.first.mode, LegMode.drive);

      // Same journey, new destination — and now it cannot be driven.
      draft.setDestination(marseille);

      expect(draft.segments.first.mode, LegMode.flight);
      addTearDown(draft.dispose);
    });

    test('inserting a stop splits one flight into a drive and a flight', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      expect(draft.segments.first.mode, LegMode.flight);
      draft.segments.first.flightNumber.text = 'AH1006';

      draft.insertStopAfter(0, algiers);

      expect(draft.segments[0].mode, LegMode.drive);
      expect(draft.segments[1].mode, LegMode.flight);
      // The number belongs to the half that still flies, so it is carried
      // rather than retyped.
      expect(draft.segments[0].flightNumber.text, isEmpty);
      expect(draft.segments[1].flightNumber.text, 'AH1006');
      addTearDown(draft.dispose);
    });
  });

  // -------------------------------------------------------------------------
  group('a flight needs airports, and says so', () {
    test(
      'two cities across the boundary are flagged, not silently changed',
      () {
        final draft = JourneyRouteDraft()
          ..setOrigin(jijel)
          ..setDestination(paris);
        _completeSegments(draft);

        final issues = draft.issuesFor(0, _copy);

        expect(issues.needsAirports, isTrue);
        expect(draft.isValid(_copy), isFalse);
        // The cities are untouched: nothing became an airport behind the
        // traveller's back.
        expect(draft.stops.first.place.name, 'Jijel');
        expect(draft.stops.first.airport, isNull);
        addTearDown(draft.dispose);
      },
    );

    test('choosing an airport keeps the city as the stop', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);

      draft.setStopAirport(1, cdg);

      expect(draft.stops[1].place.name, 'Paris');
      expect(draft.stops[1].airport?.iataCode, 'CDG');
      expect(draft.stops[1].endpoint.iataCode, 'CDG');
      addTearDown(draft.dispose);
    });

    test('with both airports chosen the flight validates', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.setStopAirport(0, gjl);
      draft.setStopAirport(1, cdg);
      _completeSegments(draft);

      expect(draft.issuesFor(0, _copy).needsAirports, isFalse);
      expect(draft.isValid(_copy), isTrue);
      addTearDown(draft.dispose);
    });

    test('the airport is what the leg carries; the city is the journey', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);
      draft.setStopAirport(1, alg);
      draft.setStopAirport(2, cdg);
      _completeSegments(draft);

      final legs = draft.toLegDrafts();

      expect(legs[0].originPlaceId, jijel.id);
      expect(legs[0].destinationPlaceId, alg.id);
      expect(legs[1].originPlaceId, alg.id);
      expect(legs[1].destinationPlaceId, cdg.id);
      // The journey still starts in Jijel and ends in Paris.
      expect(draft.startPlaceId, jijel.id);
      expect(draft.destinationPlaceId, paris.id);
      addTearDown(draft.dispose);
    });

    test('changing the city drops an airport that no longer serves it', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.setStopAirport(1, cdg);
      expect(draft.stops[1].airport, isNotNull);

      draft.setStop(1, madrid);

      expect(draft.stops[1].airport, isNull);
      addTearDown(draft.dispose);
    });

    test('an airport chosen directly as a stop stands for itself', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(alg)
        ..setDestination(cdg);

      expect(draft.stops.first.resolvesToAirport, isTrue);
      expect(draft.stops.first.airport, isNull);
      expect(draft.segments.first.mode, LegMode.flight);
      addTearDown(draft.dispose);
    });
  });

  // -------------------------------------------------------------------------
  group('two stops in one city are not a leg', () {
    test('an airport and the city it serves are the same stop', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(cdg)
        ..setDestination(paris);
      _completeSegments(draft);

      expect(draft.issuesFor(0, _copy).stopsAreTheSamePlace, isTrue);
      expect(draft.isValid(_copy), isFalse);
      addTearDown(draft.dispose);
    });

    test('two different cities are a leg', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(algiers);
      _completeSegments(draft);

      expect(draft.issuesFor(0, _copy).stopsAreTheSamePlace, isFalse);
      expect(draft.isValid(_copy), isTrue);
      addTearDown(draft.dispose);
    });
  });

  // -------------------------------------------------------------------------
  group('reopening a saved journey', () {
    Journey savedJourney() => Journey.fromJson({
      'id': 7,
      'traveler_id': 42,
      'traveler_name': 'Amina',
      'status': 'draft',
      'notes': 'Driving to Algiers first',
      'editable': true,
      'start_place': {
        'id': jijel.id,
        'name': 'Jijel',
        'display_label': 'Jijel',
        'place_type': 'locality',
        'country_code': 'DZ',
        'matching_locality_id': jijel.matchingLocalityId,
      },
      'destination_place': {
        'id': paris.id,
        'name': 'Paris',
        'display_label': 'Paris',
        'place_type': 'locality',
        'country_code': 'FR',
        'matching_locality_id': paris.matchingLocalityId,
      },
      'legs': [
        {
          'id': 101,
          'position': 0,
          'mode': 'DRIVE',
          'origin_place': {
            'id': jijel.id,
            'name': 'Jijel',
            'display_label': 'Jijel',
            'place_type': 'locality',
            'country_code': 'DZ',
            'matching_locality_id': jijel.matchingLocalityId,
          },
          'destination_place': {
            'id': alg.id,
            'name': 'Houari Boumediene',
            'display_label': 'Houari Boumediene (ALG)',
            'place_type': 'airport',
            'iata_code': 'ALG',
            'country_code': 'DZ',
            'matching_locality_id': algiers.matchingLocalityId,
          },
          'depart_at': '2026-10-01T08:00:00Z',
          'arrive_at': '2026-10-01T13:00:00Z',
          'capacity_kg': '12.00',
          'flight_number': '',
          'proofs': const [],
        },
        {
          'id': 102,
          'position': 1,
          'mode': 'FLIGHT',
          'origin_place': {
            'id': alg.id,
            'name': 'Houari Boumediene',
            'display_label': 'Houari Boumediene (ALG)',
            'place_type': 'airport',
            'iata_code': 'ALG',
            'country_code': 'DZ',
            'matching_locality_id': algiers.matchingLocalityId,
          },
          'destination_place': {
            'id': cdg.id,
            'name': 'Charles de Gaulle',
            'display_label': 'Charles de Gaulle (CDG)',
            'place_type': 'airport',
            'iata_code': 'CDG',
            'country_code': 'FR',
            'matching_locality_id': paris.matchingLocalityId,
          },
          'depart_at': '2026-10-01T15:00:00Z',
          'arrive_at': '2026-10-01T18:00:00Z',
          'capacity_kg': '12.00',
          'flight_number': 'AH1006',
          'proofs': const [],
        },
      ],
    });

    test('every stop, mode, time and capacity is prepopulated', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      expect(draft.stops, hasLength(3));
      expect(draft.segments, hasLength(2));
      expect(draft.segments[0].mode, LegMode.drive);
      expect(draft.segments[1].mode, LegMode.flight);
      expect(draft.segments[1].flightNumber.text, 'AH1006');
      expect(draft.segments[0].capacity.text, '12.00');
      expect(draft.segments[0].departAt, isNotNull);
      addTearDown(draft.dispose);
    });

    test('the last stop reads as the city, reached via its airport', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      expect(draft.stops.last.place.name, 'Paris');
      expect(draft.stops.last.airport?.iataCode, 'CDG');
      addTearDown(draft.dispose);
    });

    test('leg identity survives so proof can survive with it', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      expect(draft.segments.map((s) => s.id), [101, 102]);
      expect(draft.toLegDrafts().map((l) => l.id), [101, 102]);
      addTearDown(draft.dispose);
    });

    test('inserting a stop makes the split half a new leg, not the old one', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      draft.insertStopAfter(0, oran);

      // The flight is untouched and keeps its identity — and therefore its
      // reviewed proof. Neither half of the split drive does: a leg's identity
      // is the pair of places it joins, and both halves join a new pair.
      expect(draft.segments.last.id, 102);
      expect(draft.segments[0].id, isNull);
      expect(draft.segments[1].id, isNull);
      addTearDown(draft.dispose);
    });

    test('changing a stop drops the identity of the legs it touches', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      draft.setStop(1, oran);

      expect(draft.segments[0].id, isNull);
      expect(draft.segments[1].id, isNull);
      addTearDown(draft.dispose);
    });

    test('an untouched route sends every leg back with its id', () {
      final draft = JourneyRouteDraft.fromJourney(savedJourney());

      final legs = draft.toLegDrafts();

      expect(legs[0].id, 101);
      expect(legs[1].id, 102);
      expect(legs[1].mode, TransportModeDraft.flight);
      expect(legs[1].flightNumber, 'AH1006');
      addTearDown(draft.dispose);
    });
  });

  // -------------------------------------------------------------------------
  group('validation before the round trip', () {
    test('a segment with no departure is not submittable', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(algiers);
      draft.segments.first.capacity.text = '10.00';

      expect(draft.issuesFor(0, _copy).depart, 'depart-required');
      expect(draft.isValid(_copy), isFalse);
      addTearDown(draft.dispose);
    });

    test('a flight with no number is not submittable', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(gjl)
        ..setDestination(cdg);
      _completeSegments(draft);
      draft.segments.first.flightNumber.text = '';

      expect(draft.issuesFor(0, _copy).flightNumber, 'required');
      addTearDown(draft.dispose);
    });

    test('capacity that rounds to zero is refused', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(algiers);
      _completeSegments(draft);
      draft.segments.first.capacity.text = '0.004';

      expect(draft.issuesFor(0, _copy).capacity, 'capacity');
      addTearDown(draft.dispose);
    });

    test('legs must depart in order', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);
      draft.setStopAirport(1, alg);
      draft.setStopAirport(2, cdg);
      _completeSegments(draft);
      draft.setSegmentDeparture(1, DateTime(2026, 9, 1, 8));

      expect(draft.issuesFor(1, _copy).depart, isNotNull);
      addTearDown(draft.dispose);
    });

    test('a full valid route submits every leg in order', () {
      final draft = JourneyRouteDraft()
        ..setOrigin(jijel)
        ..setDestination(paris);
      draft.insertStopAfter(0, algiers);
      draft.setStopAirport(1, alg);
      draft.setStopAirport(2, cdg);
      _completeSegments(draft);

      expect(draft.isValid(_copy), isTrue);
      final legs = draft.toLegDrafts();
      expect(legs, hasLength(2));
      expect(legs[0].mode, TransportModeDraft.drive);
      expect(legs[1].mode, TransportModeDraft.flight);
      expect(legs[0].departAt.isBefore(legs[1].departAt), isTrue);
      addTearDown(draft.dispose);
    });
  });
}
