/// Phase J4 — the Find Travelers contract, pinned from the client side.
///
/// The fixture below is a byte-for-byte copy of what
/// `GET /api/matches/find-travelers` produced for the canonical
/// Paris · CDG → Algiers · ALG → Jijel world in
/// `apps/matching/tests/test_phase_j4_find_travelers.py`. Both halves of the
/// seam are therefore pinned: the server suite asserts it still *sends* this
/// shape, and this suite asserts the decoder still *reads* it.
///
/// That double pinning is the J1.2 lesson. Find Travelers drew a route line of
/// unlabelled dots for a fortnight because the server sent canonical places
/// under one key pair and the client read the other — and every test on both
/// sides passed throughout.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/transport_mode.dart';

/// One candidate exactly as the server sends it.
Map<String, dynamic> serverPayload() => {
  'state': 'results',
  'sort': 'best_match',
  'page': {
    'limit': 10,
    'offset': 0,
    'total': 1,
    'has_more': false,
    'next_offset': null,
  },
  // Explicitly `dynamic`-valued so a test can null a field out. Without the
  // annotation Dart infers `Map<String, Object>` from the literal and setting
  // a key to null throws at runtime rather than exercising the decoder.
  'results': <Map<String, dynamic>>[
    <String, dynamic>{
      'journey_id': 1,
      'traveler': {
        'id': 2,
        'display_name': 'Yacine',
        'avatar_url': null,
        'identity_verified': true,
        'rating': {'state': 'new', 'average': null, 'count': 0},
        'completed_deliveries': 0,
      },
      'route': {
        'stops': [
          {
            'place_id': 1,
            'label': 'Paris',
            'country_code': 'FR',
            'airport_iata': 'CDG',
            'arrive_at': null,
            'depart_at': '2026-09-18T01:15:02.749723+00:00',
          },
          {
            'place_id': 3,
            'label': 'Algiers',
            'country_code': 'DZ',
            'airport_iata': 'ALG',
            'arrive_at': '2026-09-18T04:15:02.749723+00:00',
            'depart_at': '2026-09-18T05:15:02.749723+00:00',
          },
          {
            'place_id': 4,
            'label': 'Jijel',
            'country_code': 'DZ',
            'airport_iata': null,
            'arrive_at': '2026-09-18T10:15:02.749723+00:00',
            'depart_at': null,
          },
        ],
        'segments': [
          {
            'journey_leg_id': 1,
            'mode': 'FLIGHT',
            'depart_at': '2026-09-18T01:15:02.749723+00:00',
            'arrive_at': '2026-09-18T04:15:02.749723+00:00',
          },
          {
            'journey_leg_id': 2,
            'mode': 'DRIVE',
            'depart_at': '2026-09-18T05:15:02.749723+00:00',
            'arrive_at': '2026-09-18T10:15:02.749723+00:00',
          },
        ],
        'continues_before': false,
        'continues_after': false,
      },
      'route_fit': 'excellent',
      'timing_fit': 'fits',
      'departs_at': '2026-09-18T01:15:02.749723+00:00',
      'arrives_at': '2026-09-18T10:15:02.749723+00:00',
      'transfers': 1,
      'primary_mode': 'FLIGHT',
      'match_reasons': [
        {
          'code': 'picks_up_in',
          'params': {'place': 'Paris'},
        },
        {
          'code': 'arrives_in',
          'params': {'place': 'Jijel'},
        },
        {
          'code': 'transfers',
          'params': {'count': 1},
        },
        {'code': 'whole_trip_matches', 'params': {}},
        {
          'code': 'arrives_before_deadline',
          'params': {
            'arrives_at': '2026-09-18T10:15:02.749723+00:00',
            'deadline_at': '2026-09-18T17:15:02.749723+00:00',
          },
        },
        {
          'code': 'has_room_for',
          'params': {'weight_kg': '2.00'},
        },
        {'code': 'identity_verified', 'params': {}},
        {'code': 'flight_proof_approved', 'params': {}},
      ],
      'caveats': [],
      'economics': {
        'currency': 'EUR',
        'minimum_reward_eur_cents': 2100,
        'minimum_economics': {
          'traveler_reward_minor': 2100,
          'commission_rate_bps': 2500,
          'platform_fee_minor': 525,
          'sender_total_minor': 2625,
        },
        'recommended_reward_eur_cents': 2850,
        'recommended_economics': {
          'traveler_reward_minor': 2850,
          'commission_rate_bps': 2500,
          'platform_fee_minor': 713,
          'sender_total_minor': 3563,
        },
      },
      'proposal': {'journey_id': 1, 'start_leg_id': 1, 'end_leg_id': 2},
      'actions': [
        {'code': 'view_journey', 'available': true, 'reason': null},
        {'code': 'propose_offer', 'available': true, 'reason': null},
      ],
    },
  ],
  'request': {
    'id': 1,
    'actual_weight_kg': '2.00',
    'volumetric_weight_kg': '0.600',
    'chargeable_weight_kg': '2.000',
    'ready_window_start': '2026-09-18T00:15:02.749723+00:00',
    'ready_window_end': '2026-09-18T02:15:02.749723+00:00',
    'deadline_at': '2026-09-18T17:15:02.749723+00:00',
    'chosen_reward_eur_cents': 3000,
    'boost_eur_cents': 0,
    'total_offered_reward_eur_cents': 3000,
  },
};

void main() {
  group('the page envelope', () {
    test('decodes the state, the sort and the page window', () {
      final page = FindTravelersPage.fromJson(serverPayload());

      expect(page.state, DiscoveryState.results);
      expect(page.sort, 'best_match');
      expect(page.page.limit, 10);
      expect(page.page.total, 1);
      expect(page.page.hasMore, isFalse);
      expect(page.page.nextOffset, isNull);
      expect(page.candidates, hasLength(1));
      expect(page.reason, isNull);
    });

    test('carries the sender request once, not once per row', () {
      final page = FindTravelersPage.fromJson(serverPayload());

      expect(page.request, isNotNull);
      expect(page.request!.id, 1);
      expect(page.request!.totalOfferedRewardEurCents, 3000);
      expect(page.request!.isVolumetric, isFalse);
    });

    test('an empty result set is a state, not an error', () {
      final payload = serverPayload()
        ..['state'] = 'no_candidates'
        ..['results'] = []
        ..['page'] = {
          'limit': 10,
          'offset': 0,
          'total': 0,
          'has_more': false,
          'next_offset': null,
        };

      final page = FindTravelersPage.fromJson(payload);
      expect(page.state, DiscoveryState.noCandidates);
      expect(page.candidates, isEmpty);
    });

    test('an ineligible request names why, and sends no request block', () {
      final page = FindTravelersPage.fromJson({
        'state': 'request_ineligible',
        'sort': 'best_match',
        'reason': 'awaiting_deposit',
        'request_status': 'awaiting_deposit',
        'page': {
          'limit': 10,
          'offset': 0,
          'total': 0,
          'has_more': false,
          'next_offset': null,
        },
        'results': [],
      });

      expect(page.state, DiscoveryState.requestIneligible);
      expect(page.reason, IneligibleReason.awaitingDeposit);
      expect(page.requestStatus, 'awaiting_deposit');
      expect(page.request, isNull);
    });

    test(
      'the next page offset comes from the server, never from arithmetic',
      () {
        final payload = serverPayload()
          ..['page'] = {
            'limit': 10,
            'offset': 0,
            'total': 23,
            'has_more': true,
            'next_offset': 10,
          };

        expect(FindTravelersPage.fromJson(payload).page.nextOffset, 10);
      },
    );
  });

  group('the route', () {
    test('reads as ordered stops with the airport as a facet of the city', () {
      final route = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.route;

      expect(route.stops.map((stop) => stop.label), [
        'Paris',
        'Algiers',
        'Jijel',
      ]);
      expect(route.stops[0].airportIata, 'CDG');
      expect(route.stops[1].airportIata, 'ALG');
      expect(route.stops[2].airportIata, isNull);
      expect(route.segments.map((segment) => segment.mode), [
        TransportMode.flight,
        TransportMode.drive,
      ]);
      // N segments, N+1 stops — exactly what a route line draws.
      expect(route.stops.length, route.segments.length + 1);
    });

    test('says whether the trip continues without saying where', () {
      final payload = serverPayload();
      (payload['results'] as List).first['route']['continues_before'] = true;
      (payload['results'] as List).first['route']['continues_after'] = true;

      final route = FindTravelersPage.fromJson(payload).candidates.single.route;
      expect(route.continuesBefore, isTrue);
      expect(route.continuesAfter, isTrue);
    });

    test('the first stop has no arrival and the last has no departure', () {
      final stops = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.route.stops;

      expect(stops.first.arriveAt, isNull);
      expect(stops.first.departAt, isNotNull);
      expect(stops.last.arriveAt, isNotNull);
      expect(stops.last.departAt, isNull);
    });
  });

  group('fit', () {
    test('route fit is a closed vocabulary', () {
      expect(RouteFit.parse('excellent'), RouteFit.excellent);
      expect(RouteFit.parse('good'), RouteFit.good);
      expect(RouteFit.parse('compatible'), RouteFit.compatible);
    });

    test('an unseen classification degrades one badge, not the screen', () {
      final payload = serverPayload();
      (payload['results'] as List).first['route_fit'] = 'transcendent';

      final candidate = FindTravelersPage.fromJson(payload).candidates.single;
      expect(candidate.routeFit, RouteFit.unknown);
      // Everything else on the row still decoded.
      expect(candidate.traveler.displayName, 'Yacine');
      expect(candidate.route.stops, hasLength(3));
    });

    test('timing fit is optional and absent reads as absent', () {
      final payload = serverPayload();
      (payload['results'] as List).first['timing_fit'] = null;

      expect(
        FindTravelersPage.fromJson(payload).candidates.single.timingFit,
        isNull,
      );
      expect(
        FindTravelersPage.fromJson(serverPayload()).candidates.single.timingFit,
        TimingFit.fits,
      );
    });
  });

  group('the traveller', () {
    test('is a first name, a verification flag and a history', () {
      final traveler = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.traveler;

      expect(traveler.displayName, 'Yacine');
      expect(traveler.identityVerified, isTrue);
      expect(traveler.completedDeliveries, 0);
      expect(traveler.avatarUrl, isNull);
    });

    test('an unrated traveller is never given a score', () {
      final rating = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.traveler.rating;

      expect(rating.state, TravelerRatingState.unrated);
      expect(rating.average, isNull);
      expect(rating.count, 0);
      expect(rating.hasScore, isFalse);
    });

    test('a rated traveller carries the average and the count', () {
      final payload = serverPayload();
      (payload['results'] as List).first['traveler']['rating'] = {
        'state': 'rated',
        'average': 4.5,
        'count': 12,
      };

      final rating = FindTravelersPage.fromJson(
        payload,
      ).candidates.single.traveler.rating;
      expect(rating.state, TravelerRatingState.rated);
      expect(rating.average, 4.5);
      expect(rating.count, 12);
      expect(rating.hasScore, isTrue);
    });

    test('a nameless traveller reads as empty, never as an email', () {
      final payload = serverPayload();
      (payload['results'] as List).first['traveler']['display_name'] = '';

      expect(
        FindTravelersPage.fromJson(
          payload,
        ).candidates.single.traveler.displayName,
        isEmpty,
      );
    });
  });

  group('actions and proposing', () {
    test('availability comes from the server, never from local state', () {
      final candidate = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single;

      expect(candidate.can(CandidateAction.viewJourney), isTrue);
      expect(candidate.can(CandidateAction.proposeOffer), isTrue);
    });

    test('a refused action is refused, and says so in a machine code', () {
      final payload = serverPayload();
      (payload['results'] as List).first['actions'] = [
        {'code': 'view_journey', 'available': true, 'reason': null},
        {
          'code': 'propose_offer',
          'available': false,
          'reason': 'leg_range_unresolved',
        },
      ];
      (payload['results'] as List).first['proposal'] = null;

      final candidate = FindTravelersPage.fromJson(payload).candidates.single;
      expect(candidate.can(CandidateAction.proposeOffer), isFalse);
      expect(candidate.proposal, isNull);
      expect(
        candidate.actions
            .firstWhere((action) => action.code == CandidateAction.proposeOffer)
            .reason,
        'leg_range_unresolved',
      );
    });

    test(
      'an action the client has never heard of is not assumed available',
      () {
        final payload = serverPayload();
        (payload['results'] as List).first['actions'] = [
          {'code': 'teleport', 'available': true, 'reason': null},
        ];

        final candidate = FindTravelersPage.fromJson(payload).candidates.single;
        expect(candidate.can(CandidateAction.proposeOffer), isFalse);
        expect(candidate.actions.single.code, CandidateAction.unknown);
      },
    );

    test('the proposal echoes the server leg range unchanged', () {
      final proposal = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.proposal;

      expect(proposal, isNotNull);
      expect(proposal!.journeyId, 1);
      expect(proposal.startLegId, 1);
      expect(proposal.endLegId, 2);
    });
  });

  group('the match explanation', () {
    test('is codes and parameters, never a sentence from the server', () {
      final reasons = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.matchReasons;

      expect(reasons.map((reason) => reason.code), [
        'picks_up_in',
        'arrives_in',
        'transfers',
        'whole_trip_matches',
        'arrives_before_deadline',
        'has_room_for',
        'identity_verified',
        'flight_proof_approved',
      ]);
      expect(reasons[0].place, 'Paris');
      expect(reasons[1].place, 'Jijel');
      expect(reasons[2].count, 1);
      expect(reasons[5].weightKg, '2.00');
      expect(reasons[4].arrivesAt, isNotNull);
      expect(reasons[4].deadlineAt, isNotNull);
    });
  });

  group('economics', () {
    test('carries the four numbers the propose sheet renders, and no more', () {
      final economics = FindTravelersPage.fromJson(
        serverPayload(),
      ).candidates.single.economics;

      expect(economics, isNotNull);
      expect(economics!.currency, 'EUR');
      expect(economics.minimumReward, 2100);
      expect(economics.recommendedReward, 2850);
      expect(economics.minimumEconomics?['sender_total_minor'], 2625);
      expect(economics.recommendedEconomics?['sender_total_minor'], 3563);
    });
  });

  group('nothing here implies distance', () {
    test('the contract has no detour, radius or matched-distance field', () {
      final blob = serverPayload().toString().toLowerCase();

      for (final forbidden in [
        'detour',
        'radius',
        'distance',
        'proximity',
        'latitude',
        'longitude',
        'corridor',
      ]) {
        expect(blob.contains(forbidden), isFalse, reason: forbidden);
      }
    });
  });
}
