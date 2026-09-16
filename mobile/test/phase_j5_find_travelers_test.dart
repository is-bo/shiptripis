import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';
import 'support/harness.dart';

class FakeMatchingRepository implements MatchingRepository {
  FakeMatchingRepository({this.findTravelersHandler, this.proposeHandler});

  Future<FindTravelersPage> Function({
    required int parcelId,
    int? limit,
    int? offset,
    String? sort,
    CancelToken? cancelToken,
  })?
  findTravelersHandler;

  Future<Offer> Function({
    required int parcelId,
    required int journeyId,
    required int startLegId,
    required int endLegId,
    required int travelerRewardEurCents,
    String note,
  })?
  proposeHandler;

  @override
  Future<FindTravelersPage> findTravelers({
    required int parcelId,
    int? limit,
    int? offset,
    String? sort,
    CancelToken? cancelToken,
  }) async {
    if (findTravelersHandler != null) {
      return findTravelersHandler!(
        parcelId: parcelId,
        limit: limit,
        offset: offset,
        sort: sort,
        cancelToken: cancelToken,
      );
    }
    throw UnimplementedError();
  }

  @override
  Future<Offer> propose({
    required int parcelId,
    required int journeyId,
    required int startLegId,
    required int endLegId,
    required int travelerRewardEurCents,
    String note = '',
  }) async {
    if (proposeHandler != null) {
      return proposeHandler!(
        parcelId: parcelId,
        journeyId: journeyId,
        startLegId: startLegId,
        endLegId: endLegId,
        travelerRewardEurCents: travelerRewardEurCents,
        note: note,
      );
    }
    throw UnimplementedError();
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

Map<String, dynamic> candidateFixture({
  int journeyId = 101,
  String travelerName = 'Karim',
  bool identityVerified = true,
  String ratingState = 'rated',
  double? averageRating = 4.8,
  int ratingCount = 24,
  int completedDeliveries = 12,
  String? avatarUrl,
  String routeFit = 'excellent',
  String? timingFit = 'comfortable',
  int transfers = 0,
  String primaryMode = 'FLIGHT',
  List<Map<String, dynamic>>? stops,
  List<Map<String, dynamic>>? segments,
  bool continuesBefore = false,
  bool continuesAfter = false,
  List<Map<String, dynamic>>? matchReasons,
  List<Map<String, dynamic>>? actions,
  Map<String, dynamic>? economics,
  Map<String, dynamic>? proposal,
}) {
  return {
    'journey_id': journeyId,
    'traveler': {
      'id': 200 + journeyId,
      'display_name': travelerName,
      'identity_verified': identityVerified,
      'rating': {
        'state': ratingState,
        'count': ratingCount,
        'average': averageRating,
      },
      'completed_deliveries': completedDeliveries,
      'avatar_url': avatarUrl,
    },
    'route': {
      'stops':
          stops ??
          [
            {
              'place_id': 1,
              'label': 'Paris',
              'country_code': 'FR',
              'airport_iata': 'CDG',
            },
            {
              'place_id': 2,
              'label': 'Algiers',
              'country_code': 'DZ',
              'airport_iata': 'ALG',
            },
          ],
      'segments':
          segments ??
          [
            {'journey_leg_id': 1, 'mode': primaryMode},
          ],
      'continues_before': continuesBefore,
      'continues_after': continuesAfter,
    },
    'route_fit': routeFit,
    'timing_fit': timingFit,
    'departs_at': '2026-09-20T10:00:00Z',
    'arrives_at': '2026-09-20T14:00:00Z',
    'transfers': transfers,
    'primary_mode': primaryMode,
    'match_reasons':
        matchReasons ??
        [
          {
            'code': 'picks_up_in',
            'params': {'place': 'Paris'},
          },
          {
            'code': 'arrives_in',
            'params': {'place': 'Algiers'},
          },
          {'code': 'direct_leg', 'params': <String, dynamic>{}},
          {'code': 'identity_verified', 'params': <String, dynamic>{}},
        ],
    'caveats': <String>[],
    'economics':
        economics ??
        {
          'currency': 'EUR',
          'minimum_reward_eur_cents': 2000,
          'recommended_reward_eur_cents': 3500,
        },
    'proposal':
        proposal ??
        {'journey_id': journeyId, 'start_leg_id': 1, 'end_leg_id': 1},
    'actions':
        actions ??
        [
          {'code': 'view_journey', 'available': true},
          {'code': 'propose_offer', 'available': true},
        ],
  };
}

Map<String, dynamic> pageFixture({
  String state = 'results',
  String sort = 'best_match',
  List<Map<String, dynamic>>? candidates,
  String? reason,
  String? requestStatus,
  Map<String, dynamic>? request,
  int limit = 10,
  int offset = 0,
  int total = 1,
  bool hasMore = false,
  int? nextOffset,
}) {
  return {
    'state': state,
    'sort': sort,
    'reason': reason,
    'request_status': requestStatus,
    'request':
        request ??
        {
          'id': 5,
          'chosen_reward_eur_cents': 3000,
          'boost_eur_cents': 500,
          'total_offered_reward_eur_cents': 3500,
          'actual_weight_kg': 2.0,
          'chargeable_weight_kg': 2.0,
          'deadline_at': '2026-09-25T18:00:00Z',
        },
    'page': {
      'limit': limit,
      'offset': offset,
      'total': total,
      'has_more': hasMore,
      'next_offset': nextOffset,
    },
    'results': candidates ?? [candidateFixture()],
  };
}

void main() {
  group('InlineRoute component', () {
    testWidgets('renders 2 stops with airport IATA', (tester) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: InlineRoute(
            stops: [
              InlineRouteStop(label: 'Paris', airportIata: 'CDG'),
              InlineRouteStop(label: 'Algiers', airportIata: 'ALG'),
            ],
          ),
        ),
      );

      expect(find.text('Paris · CDG'), findsOneWidget);
      expect(find.text('Algiers · ALG'), findsOneWidget);
      expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
    });

    testWidgets('renders 3 stops', (tester) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: InlineRoute(
            stops: [
              InlineRouteStop(label: 'Paris', airportIata: 'CDG'),
              InlineRouteStop(label: 'Algiers', airportIata: 'ALG'),
              InlineRouteStop(label: 'Oran'),
            ],
          ),
        ),
      );

      expect(find.text('Paris · CDG'), findsOneWidget);
      expect(find.text('Algiers · ALG'), findsOneWidget);
      expect(find.text('Oran'), findsOneWidget);
      expect(find.byIcon(Icons.arrow_forward_rounded), findsNWidgets(2));
    });

    testWidgets('renders continues before and after indicators', (
      tester,
    ) async {
      await pumpApp(
        tester,
        const Scaffold(
          body: InlineRoute(
            stops: [
              InlineRouteStop(label: 'Marseille'),
              InlineRouteStop(label: 'Algiers'),
            ],
            continuesBefore: true,
            continuesAfter: true,
          ),
        ),
      );

      expect(find.text('Marseille'), findsOneWidget);
      expect(find.text('Algiers'), findsOneWidget);
      expect(find.text('…'), findsNWidgets(2));
    });

    testWidgets(
      'in RTL text direction, arrow points backward preserving logical flow',
      (tester) async {
        await pumpApp(
          tester,
          const Directionality(
            textDirection: TextDirection.rtl,
            child: Scaffold(
              body: InlineRoute(
                stops: [
                  InlineRouteStop(label: 'Paris'),
                  InlineRouteStop(label: 'Algiers'),
                ],
              ),
            ),
          ),
          locale: const Locale('ar'),
        );

        // In RTL, the mirrored arrow points back (leftwards) so Stop 0 on the right flows to Stop 1 on the left
        expect(find.byIcon(Icons.arrow_back_rounded), findsOneWidget);
        expect(find.byIcon(Icons.arrow_forward_rounded), findsNothing);
      },
    );
  });

  group('Traveler candidate card', () {
    testWidgets('rated traveler renders rating score and star icon', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  candidates: [
                    candidateFixture(
                      ratingState: 'rated',
                      averageRating: 4.8,
                      ratingCount: 24,
                    ),
                  ],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('4.8'), findsOneWidget);
      expect(find.byIcon(Icons.star_rounded), findsOneWidget);
    });

    testWidgets('unrated traveler renders New badge and no fabricated score', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  candidates: [
                    candidateFixture(
                      ratingState: 'unrated',
                      averageRating: null,
                      ratingCount: 0,
                      completedDeliveries: 0,
                    ),
                  ],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('New'), findsOneWidget);
      expect(find.text('0.0'), findsNothing);
      expect(find.text('5.0'), findsNothing);
    });

    testWidgets(
      'verified identity badge renders when identity_verified is true',
      (tester) async {
        final repo = FakeMatchingRepository(
          findTravelersHandler:
              ({required parcelId, limit, offset, sort, cancelToken}) async {
                return FindTravelersPage.fromJson(
                  pageFixture(
                    candidates: [candidateFixture(identityVerified: true)],
                  ),
                );
              },
        );

        final container = ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        );

        await pumpApp(
          tester,
          const DiscoveryScreen(requestId: 5),
          container: container,
        );
        await tester.pumpAndSettle();

        expect(find.byIcon(Icons.verified_rounded), findsOneWidget);
      },
    );

    testWidgets('completed deliveries count renders when greater than zero', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  candidates: [candidateFixture(completedDeliveries: 12)],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.textContaining('12'), findsWidgets);
    });

    testWidgets('initials fallback renders when avatarUrl is null', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  candidates: [
                    candidateFixture(
                      travelerName: 'Amina Bouzid',
                      avatarUrl: null,
                    ),
                  ],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      // Avatar fallback initial for "Amina Bouzid" is "A"
      expect(find.text('A'), findsOneWidget);
    });

    testWidgets(
      'route fit badges render correctly for excellent, good, compatible',
      (tester) async {
        final repo = FakeMatchingRepository(
          findTravelersHandler:
              ({required parcelId, limit, offset, sort, cancelToken}) async {
                return FindTravelersPage.fromJson(
                  pageFixture(
                    candidates: [
                      candidateFixture(journeyId: 1, routeFit: 'excellent'),
                      candidateFixture(journeyId: 2, routeFit: 'good'),
                      candidateFixture(journeyId: 3, routeFit: 'compatible'),
                    ],
                    total: 3,
                  ),
                );
              },
        );

        final container = ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        );

        await pumpApp(
          tester,
          const DiscoveryScreen(requestId: 5),
          container: container,
        );
        await tester.pumpAndSettle();

        expect(find.text('Excellent route match'), findsOneWidget);
        expect(find.text('Good route match'), findsOneWidget);
        expect(find.text('Compatible route'), findsOneWidget);
      },
    );
  });

  group('Density & Viewport layout (390x844 target)', () {
    testWidgets(
      '4 candidate cards fit visible at 390x844 with compact height',
      (tester) async {
        final candidates = List.generate(
          4,
          (i) =>
              candidateFixture(journeyId: i + 1, travelerName: 'Traveler $i'),
        );

        final repo = FakeMatchingRepository(
          findTravelersHandler:
              ({required parcelId, limit, offset, sort, cancelToken}) async {
                return FindTravelersPage.fromJson(
                  pageFixture(candidates: candidates, total: 4),
                );
              },
        );

        final container = ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        );

        await pumpApp(
          tester,
          const DiscoveryScreen(requestId: 5),
          device: DeviceProfile.iphone, // 390x844
          container: container,
        );
        await tester.pumpAndSettle();

        // Verify all 4 candidate cards are found in the widget tree
        for (int i = 0; i < 4; i++) {
          expect(find.text('Traveler $i'), findsOneWidget);
        }

        // Verify no RenderFlex overflow on iPhone 390x844
        expect(tester.takeException(), isNull);
      },
    );
  });

  group('Screen states', () {
    testWidgets('no_candidates state strictly does NOT show Boost CTA', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(state: 'no_candidates', candidates: [], total: 0),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      // Must show no candidates copy
      expect(find.text('No travellers going your way yet'), findsOneWidget);
      // Safe CTAs must be present
      expect(find.text('Back'), findsOneWidget);
      expect(find.text('Refresh'), findsOneWidget);

      // STRICTLY VERIFY BOOST IS NOT OFFERED ON ZERO-CANDIDATES
      expect(
        find.textContaining(RegExp(r'Boost', caseSensitive: false)),
        findsNothing,
      );
    });

    testWidgets('ineligible state awaitingDeposit offers Continue CTA', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  state: 'request_ineligible',
                  reason: 'awaiting_deposit',
                  candidates: [],
                  total: 0,
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Publish your request'), findsOneWidget);
      expect(find.text('Continue'), findsOneWidget);
    });

    testWidgets('ineligible state alreadyMatched offers Back CTA', (
      tester,
    ) async {
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  state: 'request_ineligible',
                  reason: 'already_matched',
                  candidates: [],
                  total: 0,
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('This parcel already has a traveller.'), findsOneWidget);
      expect(find.text('Back'), findsOneWidget);
    });

    testWidgets('initial error state allows retry', (tester) async {
      var callCount = 0;
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              callCount++;
              if (callCount == 1) {
                throw Exception('Network error');
              }
              return FindTravelersPage.fromJson(pageFixture());
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      // Retry button is available
      expect(find.text('Try again'), findsOneWidget);

      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();

      expect(callCount, 2);
      expect(find.text('Karim'), findsOneWidget);
    });
  });

  group('Pagination and Sorting', () {
    testWidgets('switching sort reloads from offset 0', (tester) async {
      var queriedSort = '';
      var queriedOffset = -1;

      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              queriedSort = sort ?? '';
              queriedOffset = offset ?? -1;
              return FindTravelersPage.fromJson(
                pageFixture(
                  sort: sort ?? 'best_match',
                  candidates: [candidateFixture(travelerName: 'Sort-$sort')],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(queriedSort, 'best_match');
      expect(queriedOffset, 0);
      expect(find.text('Sort-best_match'), findsOneWidget);

      // Tap the Soonest trip pill
      await tester.tap(find.text('Soonest trip'));
      await tester.pumpAndSettle();

      expect(queriedSort, 'soonest_departure');
      expect(queriedOffset, 0);
      expect(find.text('Sort-soonest_departure'), findsOneWidget);
    });

    test('loadMore deduplicates incoming candidates by journeyId', () async {
      var call = 0;
      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              call++;
              if (call == 1) {
                return FindTravelersPage.fromJson(
                  pageFixture(
                    candidates: [
                      candidateFixture(
                        journeyId: 10,
                        travelerName: 'Traveler Ten',
                      ),
                    ],
                    hasMore: true,
                    nextOffset: 1,
                    total: 2,
                  ),
                );
              } else {
                // Returns duplicate candidate 10 plus new candidate 20
                return FindTravelersPage.fromJson(
                  pageFixture(
                    candidates: [
                      candidateFixture(
                        journeyId: 10,
                        travelerName: 'Traveler Ten',
                      ),
                      candidateFixture(
                        journeyId: 20,
                        travelerName: 'Traveler Twenty',
                      ),
                    ],
                    hasMore: false,
                    nextOffset: null,
                    total: 2,
                  ),
                );
              }
            },
      );

      final controller = FindTravelersController(
        requestId: 5,
        repository: repo,
      );
      // Wait for initial load
      await Future<void>.delayed(const Duration(milliseconds: 50));

      expect(controller.state?.candidates.length, 1);

      await controller.loadMore();

      // Only candidate 20 added, total length is 2, no duplicate journeyId 10
      expect(controller.state?.candidates.length, 2);
      expect(controller.state?.candidates.map((c) => c.journeyId).toList(), [
        10,
        20,
      ]);
    });
  });

  group('Match reasons and detail sheet', () {
    testWidgets('detail sheet maps all backend match reason codes accurately', (
      tester,
    ) async {
      final reasons = [
        {
          'code': 'picks_up_in',
          'params': {'place': 'Paris'},
        },
        {
          'code': 'arrives_in',
          'params': {'place': 'Algiers'},
        },
        {'code': 'direct_leg', 'params': <String, dynamic>{}},
        {
          'code': 'transfers',
          'params': {'count': 1},
        },
        {'code': 'whole_trip_matches', 'params': <String, dynamic>{}},
        {
          'code': 'arrives_before_deadline',
          'params': {
            'arrives_at': '2026-09-20T14:00:00Z',
            'deadline_at': '2026-09-22T18:00:00Z',
          },
        },
        {
          'code': 'has_room_for',
          'params': {'weight_kg': '2.5'},
        },
        {'code': 'identity_verified', 'params': <String, dynamic>{}},
        {'code': 'flight_proof_approved', 'params': <String, dynamic>{}},
        {'code': 'unknown_future_code', 'params': <String, dynamic>{}},
      ];

      final repo = FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async {
              return FindTravelersPage.fromJson(
                pageFixture(
                  candidates: [candidateFixture(matchReasons: reasons)],
                ),
              );
            },
      );

      final container = ProviderContainer(
        overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
      );

      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: container,
      );
      await tester.pumpAndSettle();

      // Tap the card to open Trip Detail Sheet
      await tester.tap(find.text('Karim'));
      await tester.pumpAndSettle();

      expect(find.text('View trip'), findsWidgets);
      expect(find.text('Why this trip fits'), findsOneWidget);

      // Verify each reason code copy is rendered
      expect(find.text('Picks up in Paris'), findsOneWidget);
      expect(find.text('Arrives in Algiers'), findsOneWidget);
      expect(find.text('Carried in one leg'), findsOneWidget);
      expect(find.text('1 transfer'), findsOneWidget);
      expect(find.text('This whole trip is your route'), findsOneWidget);
      expect(find.textContaining('before your'), findsOneWidget);
      expect(find.text('Has room for 2.5 kg'), findsOneWidget);
      expect(find.text('Identity verified'), findsWidgets);
      expect(find.text('Flight ticket verified'), findsOneWidget);

      // Confirm no radius or distance language exists anywhere in the sheet
      expect(
        find.textContaining(RegExp(r'km away', caseSensitive: false)),
        findsNothing,
      );
      expect(
        find.textContaining(RegExp(r'detour', caseSensitive: false)),
        findsNothing,
      );
      expect(
        find.textContaining(RegExp(r'nearby', caseSensitive: false)),
        findsNothing,
      );
    });

    testWidgets(
      'propose offer action is disabled when server actions do not permit it',
      (tester) async {
        final repo = FakeMatchingRepository(
          findTravelersHandler:
              ({required parcelId, limit, offset, sort, cancelToken}) async {
                return FindTravelersPage.fromJson(
                  pageFixture(
                    candidates: [
                      candidateFixture(
                        actions: [
                          {'code': 'view_journey', 'available': true},
                          {
                            'code': 'propose_offer',
                            'available': false,
                            'reason': 'already_requested',
                          },
                        ],
                      ),
                    ],
                  ),
                );
              },
        );

        final container = ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        );

        await pumpApp(
          tester,
          const DiscoveryScreen(requestId: 5),
          container: container,
        );
        await tester.pumpAndSettle();

        // Tap the card to open Trip Detail Sheet
        await tester.tap(find.text('Karim'));
        await tester.pumpAndSettle();

        // On sheet, Propose button is disabled
        final proposeButtonFinder = find.widgetWithText(
          FilledButton,
          'Make an offer',
        );
        expect(proposeButtonFinder, findsOneWidget);
        final button = tester.widget<FilledButton>(proposeButtonFinder);
        expect(button.onPressed, isNull);
      },
    );
  });

  group('Device responsiveness', () {
    for (final profile in [
      DeviceProfile.smallAndroid,
      DeviceProfile.android,
      DeviceProfile.iphone,
      DeviceProfile.landscape,
      DeviceProfile.largeText,
    ]) {
      testWidgets(
        'discovery screen renders without overflow on ${profile.name}',
        (tester) async {
          final repo = FakeMatchingRepository(
            findTravelersHandler:
                ({required parcelId, limit, offset, sort, cancelToken}) async {
                  return FindTravelersPage.fromJson(
                    pageFixture(
                      candidates: [
                        candidateFixture(
                          journeyId: 1,
                          travelerName: 'Traveler 1',
                        ),
                        candidateFixture(
                          journeyId: 2,
                          travelerName: 'Traveler 2',
                        ),
                      ],
                    ),
                  );
                },
          );

          final container = ProviderContainer(
            overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
          );

          await pumpApp(
            tester,
            const DiscoveryScreen(requestId: 5),
            device: profile,
            container: container,
          );
          await tester.pumpAndSettle();

          final err = tester.takeException();
          expect(err, isNull);
        },
      );
    }
  });
}
