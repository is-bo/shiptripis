/// L2B: the wire contract of `/api/discovery/*`, asserted on what leaves the
/// client. A stubbed repository would prove none of it.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/data/discovery_repository.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/public_discovery.dart';

import 'support/fake_api.dart';

({DiscoveryRepository repo, FakeBackend backend}) _setup(
  void Function(FakeBackend) routes,
) {
  final backend = FakeBackend()..emptyDiscovery();
  routes(backend);
  final api = apiClientFor(backend);
  addTearDown(() => api.raw.close(force: true));
  return (repo: DiscoveryRepository(api), backend: backend);
}

const _paris = PlaceRef(placeId: 1, label: 'Paris', countryCode: 'FR');
const _algiers = PlaceRef(placeId: 2, label: 'Algiers', countryCode: 'DZ');

void main() {
  group('lists', () {
    test('a plain list sends only the page size', () async {
      final t = _setup((_) {});

      await t.repo.trips();

      final sent = t.backend.lastTo('GET', '/api/discovery/trips')!;
      expect(sent.query, {'limit': browsePageSize});
    });

    test(
      'filters are sent by name, and offset only past the first page',
      () async {
        final t = _setup((_) {});

        await t.repo.trips(
          filter: BrowseFilter(
            originCountry: 'FR',
            destinationCountry: 'DZ',
            origin: _paris,
            destination: _algiers,
          ),
          offset: 40,
        );

        final sent = t.backend.lastTo('GET', '/api/discovery/trips')!;
        expect(sent.query['origin_country'], 'FR');
        expect(sent.query['destination_country'], 'DZ');
        expect(sent.query['origin_place_id'], 1);
        expect(sent.query['destination_place_id'], 2);
        expect(sent.query['offset'], 40);
      },
    );

    test(
      'a date means the start of that local day, sent as a UTC instant',
      () async {
        final t = _setup((_) {});

        await t.repo.requests(
          filter: BrowseFilter(departingAfter: DateTime(2026, 12, 5, 17, 30)),
        );

        final sent = t.backend.lastTo('GET', '/api/discovery/requests')!;
        final instant = DateTime.parse(sent.query['departing_after'] as String);
        expect(instant.isUtc, isTrue);
        expect(instant, DateTime(2026, 12, 5).toUtc());
      },
    );

    test('people are asked for by the viewer\'s own role', () async {
      final t = _setup((_) {});

      await t.repo.people(viewerIsSender: true);
      await t.repo.people(viewerIsSender: false, limit: 10);

      final sent = t.backend.to('GET', '/api/discovery/people');
      expect(sent.first.query['role'], 'sender');
      expect(sent.last.query['role'], 'traveler');
      expect(sent.last.query['limit'], 10);
    });

    test('matches ask per role, one call each', () async {
      final t = _setup((_) {});

      await t.repo.senderMatches();
      await t.repo.travelerMatches();

      final sent = t.backend.to('GET', '/api/discovery/matches');
      expect([for (final r in sent) r.query['role']], ['sender', 'traveler']);
    });

    test('a page carries the server\'s cursor and its tier state', () async {
      final t = _setup(
        (b) => b
          ..on(
            'GET',
            '/api/discovery/trips',
            discoveryPage([tripCardFixture(1)], next: 20),
          )
          ..on(
            'GET',
            '/api/discovery/requests',
            const FakeResponse(200, {
              'state': 'disabled',
              'results': <Object>[],
            }),
          ),
      );

      final trips = await t.repo.trips();
      final requests = await t.repo.requests();

      expect(trips.nextOffset, 20);
      expect(trips.state, DiscoveryTierState.results);
      expect(requests.isDisabled, isTrue);
      expect(requests.hasMore, isFalse);
    });
  });

  group('my profile and alerts', () {
    test('a write sends only what was changed', () async {
      final t = _setup(
        (b) => b.handle(
          'PUT',
          '/api/discovery/profile/me',
          (_) => FakeResponse(
            200,
            ownProfileFixture(state: 'visible', discoverable: true),
          ),
        ),
      );

      final profile = await t.repo.updateOwnProfile(isDiscoverable: true);
      await t.repo.updateOwnProfile(promptDismissed: true);
      await t.repo.updateOwnProfile(
        usualRoutes: [(originPlaceId: 1, destinationPlaceId: 2)],
      );

      final sent = t.backend.to('PUT', '/api/discovery/profile/me');
      expect(sent[0].body, {'is_discoverable': true});
      expect(sent[1].body, {'prompt_dismissed': true});
      expect(sent[2].body, {
        'usual_routes': [
          {'origin_place_id': 1, 'destination_place_id': 2},
        ],
      });
      expect(profile.state, OwnProfileState.visible);
    });

    test(
      'an alert is created with ids, and following a person adds theirs',
      () async {
        final t = _setup(
          (b) => b.on(
            'POST',
            '/api/discovery/alerts',
            FakeResponse(201, alertFixture(5, watches: 'requests')),
          ),
        );

        final alert = await t.repo.createAlert(
          watches: AlertWatch.requests,
          originPlaceId: 1,
          destinationPlaceId: 2,
          subjectProfileId: 'p-9',
        );
        await t.repo.createAlert(
          watches: AlertWatch.trips,
          originPlaceId: 1,
          destinationPlaceId: 2,
        );

        final sent = t.backend.to('POST', '/api/discovery/alerts');
        expect(sent.first.body, {
          'watches': 'requests',
          'origin_place_id': 1,
          'destination_place_id': 2,
          'subject_profile_id': 'p-9',
        });
        expect(sent.last.body.containsKey('subject_profile_id'), isFalse);
        expect(alert.watches, AlertWatch.requests);
      },
    );

    test('deleting an alert is a DELETE on its id', () async {
      final t = _setup(
        (b) => b.on(
          'DELETE',
          '/api/discovery/alerts/5',
          const FakeResponse(204, {}),
        ),
      );

      await t.repo.deleteAlert(5);

      expect(t.backend.to('DELETE', '/api/discovery/alerts/5'), hasLength(1));
    });

    test('an alert the client cannot read is dropped, not thrown', () async {
      final t = _setup(
        (b) => b.on(
          'GET',
          '/api/discovery/alerts',
          FakeResponse(200, {
            'results': [
              alertFixture(1),
              {
                'id': 2,
                'watches': 'something-new',
                'origin': discoveryPlace(1, 'A'),
                'destination': discoveryPlace(2, 'B'),
              },
            ],
          }),
        ),
      );

      final alerts = await t.repo.alerts();

      expect(alerts.map((a) => a.id), [1]);
    });
  });

  group('"I can carry this"', () {
    test('sends the journey and nothing that looks like an offer', () async {
      final t = _setup(
        (b) => b.on(
          'POST',
          '/api/discovery/requests/9/interest',
          const FakeResponse(201, {
            'request_id': 9,
            'journey_id': 3,
            'created': true,
            'sent_at': '2026-11-12T09:00:00Z',
          }),
        ),
      );

      final result = await t.repo.sendInterest(requestId: 9, journeyId: 3);

      expect(
        t.backend.lastTo('POST', '/api/discovery/requests/9/interest')!.body,
        {'journey_id': 3},
      );
      expect(result.created, isTrue);
    });

    test(
      'a repeat is not "created" and an incompatible pair carries the server\'s codes',
      () async {
        final t = _setup(
          (b) => b
            ..on(
              'POST',
              '/api/discovery/requests/9/interest',
              const FakeResponse(200, {
                'request_id': 9,
                'journey_id': 3,
                'created': false,
              }),
            )
            ..on(
              'POST',
              '/api/discovery/requests/8/interest',
              const FakeResponse(409, {
                'code': 'incompatible_candidate',
                'rejection_codes': ['delivery_before_deadline'],
              }),
            ),
        );

        expect(
          (await t.repo.sendInterest(requestId: 9, journeyId: 3)).created,
          isFalse,
        );
        await expectLater(
          t.repo.sendInterest(requestId: 8, journeyId: 3),
          throwsA(
            isA<ApiException>()
                .having(
                  (e) => e.code,
                  'code',
                  ApiErrorCode.incompatibleCandidate,
                )
                .having((e) => e.stringListExtra('rejection_codes'), 'codes', [
                  'delivery_before_deadline',
                ]),
          ),
        );
      },
    );
  });

  group('decoding', () {
    test(
      'a closed vocabulary degrades to unknown and a bad weight to none',
      () {
        final card = TripCard.fromJson({
          ...tripCardFixture(1),
          'free_weight_kg': 'lots',
          'legs': [
            {'mode': 'teleport'},
          ],
        });

        expect(card.freeWeightKg, isNull);
        expect(card.modes, isEmpty, reason: 'an unknown leg mode is dropped');
        expect(
          DiscoveryTierState.parse('brand_new'),
          DiscoveryTierState.unknown,
        );
        expect(OwnProfileState.parse('weird'), OwnProfileState.unknown);
      },
    );

    test('a person with no rating has none, never zero', () {
      final person = PublicPerson.fromJson(discoveryPersonFields(rating: null));

      expect(person.hasRating, isFalse);
    });

    test(
      'a profile that was never saved has no id and does not invent one',
      () {
        final own = OwnProfile.fromJson({
          ...ownProfileFixture(),
          'card': {...profileCardFixture(), 'id': null},
        });

        expect(own.card.id, isNull);
      },
    );

    test('a card has no field for what the server never sends', () {
      // The allowlist is the server's; the client has nothing to fall back on.
      final json = {
        ...tripCardFixture(1),
        'traveler': {
          ...discoveryPersonFields(),
          'phone': '+213555',
          'last_name': 'Haddad',
          'email': 'x@y.z',
        },
      };

      final card = TripCard.fromJson(json);

      expect(card.traveler.displayName, 'Samira');
      expect('${card.traveler.runtimeType}', 'PublicPerson');
    });

    test('place identity: an airport pick stands for the city it serves', () {
      final place = PlaceRef.fromCanonical(
        const CanonicalPlace(
          id: 44,
          countryCode: 'fr',
          type: CanonicalPlaceType.airport,
          name: 'Charles de Gaulle',
          displayLabel: 'Charles de Gaulle (CDG)',
          parentName: '',
          parentAdminLevel: '',
          matchingLocalityId: 22,
          matchingLocalityName: 'Paris',
        ),
      );

      expect(
        place.placeId,
        22,
        reason: 'the matching locality, not the airport',
      );
      expect(place.label, 'Paris');
      expect(place.countryCode, 'FR');
    });

    test('filters are keyed by value', () {
      expect(const BrowseFilter(), const BrowseFilter());
      expect(
        Corridor.launchCorridors.first.filter,
        Corridor.launchCorridors.first.filter,
      );
      expect(
        const BrowseFilter(originCountry: 'FR') ==
            const BrowseFilter(originCountry: 'DZ'),
        isFalse,
      );
      expect({const BrowseFilter(): 1}[const BrowseFilter()], 1);
    });
  });
}
