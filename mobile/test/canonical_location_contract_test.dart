library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/domain/location.dart';

import 'support/fake_api.dart';

void main() {
  test('airport place parses the backend-owned matching locality', () {
    final place = CanonicalPlace.fromJson({
      'id': 9001,
      'country_code': 'FR',
      'place_type': 'airport',
      'name': 'Paris Charles de Gaulle',
      'display_label': 'Paris Charles de Gaulle',
      'parent_name': '',
      'iata_code': 'CDG',
      'latitude': '49.009700',
      'longitude': '2.547900',
      'matching_locality': {'id': 75056, 'name': 'Paris'},
    });

    expect(place.isAirport, isTrue);
    expect(place.iataCode, 'CDG');
    expect(place.matchingLocalityId, 75056);
    expect(place.matchingLocalityName, 'Paris');
  });

  test('Sender draft can stay flexible or include scoped preferred points', () {
    final base = DeliveryRequestDraft(
      pickupPlaceId: 101,
      deliveryPlaceId: 202,
      readyWindowStart: DateTime.utc(2026, 9, 3, 10),
      readyWindowEnd: DateTime.utc(2026, 9, 3, 12),
      deadlineAt: DateTime.utc(2026, 9, 5),
      actualWeightKg: 2,
      declaredValueEurCents: 10000,
      senderProposedRewardEurCents: 2000,
      title: 'Documents',
      description: 'Sealed documents',
      category: ItemCategory.documents,
      acknowledgements: const SafetyAcknowledgements(
        descriptionIsAccurate: true,
        itemIsLegal: true,
        noProhibitedGoods: true,
        declaredValueIsAccurate: true,
        customsResponsibilitiesUnderstood: true,
      ),
    );
    final selected = DeliveryRequestDraft(
      pickupPlaceId: 101,
      deliveryPlaceId: 202,
      pickupLocationId: 11,
      deliveryLocationId: 22,
      readyWindowStart: base.readyWindowStart,
      readyWindowEnd: base.readyWindowEnd,
      deadlineAt: base.deadlineAt,
      actualWeightKg: base.actualWeightKg,
      declaredValueEurCents: base.declaredValueEurCents,
      senderProposedRewardEurCents: base.senderProposedRewardEurCents,
      title: base.title,
      description: base.description,
      category: base.category,
      acknowledgements: base.acknowledgements,
    );

    expect(base.toJson()['pickup_place_id'], 101);
    expect(base.toJson().containsKey('pickup_location_id'), isFalse);
    expect(selected.toJson()['pickup_location_id'], 11);
    expect(selected.toJson()['delivery_location_id'], 22);
  });

  test(
    'Traveler JourneyLeg sends canonical endpoints, order, mode and capacity',
    () {
      final draft = JourneyLegDraft(
        position: 1,
        mode: TransportModeDraft.drive,
        originPlaceId: 301,
        destinationPlaceId: 302,
        departAt: DateTime.utc(2026, 9, 4, 8),
        arriveAt: DateTime.utc(2026, 9, 4, 12),
        capacityKg: 8.5,
      );

      expect(draft.toJson(), containsPair('origin_place_id', 301));
      expect(draft.toJson(), containsPair('destination_place_id', 302));
      expect(draft.toJson(), containsPair('position', 1));
      expect(draft.toJson(), containsPair('mode', 'DRIVE'));
    },
  );

  test(
    'preferred point write carries canonical context, never a city identity',
    () async {
      final backend = FakeBackend()
        ..on(
          'POST',
          '/api/locations',
          const FakeResponse(201, {
            'id': 11,
            'kind': 'map_point',
            'public_label': 'Paris, FR',
            'private_label': 'University entrance',
            'city': 'Paris',
            'region': 'Île-de-France',
            'country_code': 'FR',
            'latitude': '48.856600',
            'longitude': '2.352200',
            'precision': 'rooftop',
            'coordinates_trusted': false,
            'canonical_place': 101,
          }),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);

      final point = await container
          .read(locationRepositoryProvider)
          .create(
            kind: LocationKind.mapPoint,
            normalizedLabel: 'University entrance',
            privateLabel: 'University entrance',
            city: 'Paris',
            countryCode: 'FR',
            latitude: 48.8566,
            longitude: 2.3522,
            canonicalPlaceId: 101,
          );

      expect(point.canonicalPlaceId, 101);
      final body = backend.lastTo('POST', '/api/locations')!.body;
      expect(body['canonical_place'], 101);
      expect(body.containsKey('pickup_city'), isFalse);
      expect(body.containsKey('public_label'), isFalse);
    },
  );
}
