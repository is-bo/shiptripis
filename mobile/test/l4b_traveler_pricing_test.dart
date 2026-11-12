/// L4B: a traveller's price, from the editor to a sent offer.
///
/// The app does no price arithmetic, so what is asserted is what the screens
/// show of the server's numbers and what reaches Django: the price goes with a
/// route write (and is never dropped by one), the listed price is one tap from
/// an offer, a different amount is still possible, and a switched-off policy
/// hides every field while leaving a stored price untouched.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/journey.dart';
import 'package:shiptrip/domain/public_discovery.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/features/journeys/journey_edit_screen.dart';
import 'package:shiptrip/features/journeys/journey_price.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'phase8fa_journey_screens_test.dart' show journeyFixture;
import 'phase_j5_find_travelers_test.dart' show candidateFixture, pageFixture;
import 'support/discovery_harness.dart';
import 'support/fake_api.dart';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

Map<String, dynamic> _policy({bool enabled = true}) => {
  'enabled': enabled,
  'currency': 'EUR',
  'max_price_per_kg_eur_cents': enabled ? 10000 : null,
  'max_min_price_eur_cents': enabled ? 50000 : null,
};

Map<String, dynamic> _listed({int reward = 2400, String basis = 'per_kg'}) => {
  'reward_eur_cents': reward,
  'economics': {
    'traveler_reward_minor': reward,
    'commission_rate_bps': 1000,
    'platform_fee_minor': 240,
    'sender_total_minor': reward + 240,
  },
  'price_per_kg_eur_cents': 1200,
  'min_price_eur_cents': 1500,
  'basis': basis,
};

Map<String, dynamic> _economics({Map<String, dynamic>? listed}) => {
  'currency': 'EUR',
  'minimum_reward_eur_cents': 1800,
  'minimum_economics': {
    'traveler_reward_minor': 1800,
    'platform_fee_minor': 180,
    'sender_total_minor': 1980,
  },
  'recommended_reward_eur_cents': 3500,
  'recommended_economics': {
    'traveler_reward_minor': 3500,
    'platform_fee_minor': 350,
    'sender_total_minor': 3850,
  },
  'listed': ?listed,
};

Map<String, dynamic> _ownJourney({
  Map<String, dynamic>? price,
  String status = 'draft',
  bool editable = true,
}) => {
  'id': 9,
  'traveler_id': 42,
  'traveler_name': 'Amina Bouzid',
  'status': status,
  'notes': '',
  'editable': editable,
  'start_place': discoveryPlace(1, 'Paris'),
  'destination_place': discoveryPlace(2, 'Algiers', 'DZ'),
  'legs': [
    {
      'id': 100,
      'position': 0,
      'mode': 'DRIVE',
      'origin_place': discoveryPlace(1, 'Paris'),
      'destination_place': discoveryPlace(2, 'Algiers', 'DZ'),
      'depart_at': '2026-12-02T10:00:00Z',
      'arrive_at': '2026-12-02T13:00:00Z',
      'capacity_kg': '10.00',
      'flight_number': '',
      'proof_required': false,
      'proof_state': 'not_required',
      'proofs': const <Object>[],
      'distance_meters': 1500000,
    },
  ],
  'price': price,
};

const _price = {'price_per_kg_eur_cents': 1200, 'min_price_eur_cents': 1500};

FakeBackend _backend({bool policyEnabled = true}) => discoveryBackend()
  ..on(
    'GET',
    '/api/journeys/pricing-policy',
    FakeResponse(200, _policy(enabled: policyEnabled)),
  );

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

Future<void> _findTravelers(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
}) async {
  await pumpDiscovery(
    tester,
    const DiscoveryScreen(requestId: 5),
    backend,
    locale: locale,
    extraRoutes: [marker(Routes.negotiation, '/matches/:id')],
  );
}

void main() {
  // -------------------------------------------------------------------------
  group('the contract', () {
    test('a journey, a trip card and a candidate read the price block', () {
      final journey = Journey.fromJson({..._ownJourney(price: _price)});
      expect(
        journey.price,
        const JourneyPrice(perKgEurCents: 1200, minimumEurCents: 1500),
      );
      expect(Journey.fromJson(_ownJourney()).price, isNull);

      final card = TripCard.fromJson(tripCardFixture(1, price: _price));
      expect(card.price?.perKgEurCents, 1200);

      final economics = CandidateEconomics.maybe(
        _economics(listed: _listed(basis: 'wassla_minimum')),
      )!;
      expect(economics.listed?.reward, 2400);
      expect(economics.listed?.basis, ListedBasis.wasslaMinimum);
      expect(CandidateEconomics.maybe(_economics())!.listed, isNull);
    });

    test('half a price is no price, and an unknown basis degrades', () {
      expect(JourneyPrice.maybe({'price_per_kg_eur_cents': 1200}), isNull);
      expect(ListedBasis.parse('something_new'), ListedBasis.unknown);
    });
  });

  // -------------------------------------------------------------------------
  group('the draft', () {
    test('empty is valid, half is not, both is, and the ceiling applies', () {
      const policy = TravelerPricingPolicy(
        enabled: true,
        maxPerKgEurCents: 10000,
        maxMinimumEurCents: 50000,
      );
      final draft = JourneyPriceDraft();
      addTearDown(draft.dispose);

      expect(draft.isValid(policy), isTrue);
      expect(draft.price, isNull);

      draft.perKg.text = '12.00';
      expect(draft.isValid(policy), isFalse);
      expect(draft.check(policy).minimum?.kind, PriceIssueKind.incomplete);

      draft.minimum.text = '15.5';
      expect(draft.isValid(policy), isTrue);
      expect(
        draft.price,
        const JourneyPrice(perKgEurCents: 1200, minimumEurCents: 1550),
      );

      draft.perKg.text = '100.01';
      expect(draft.check(policy).perKg?.kind, PriceIssueKind.aboveMaximum);
      draft.perKg.text = '0';
      expect(draft.check(policy).perKg?.kind, PriceIssueKind.notPositive);
      draft.perKg.text = '1.234';
      expect(draft.check(policy).perKg?.kind, PriceIssueKind.precision);
    });

    test('a server refusal sits on its field until the value changes', () {
      final draft = JourneyPriceDraft();
      addTearDown(draft.dispose);
      final shown = draft.showRefusal(
        ApiException(
          kind: ApiFailureKind.validation,
          statusCode: 400,
          code: const ApiErrorCode('journey_price_invalid'),
          extras: const {
            'reason': ['min_price_above_maximum'],
            'max_min_price_eur_cents': ['50000'],
          },
        ),
      );
      expect(shown, isTrue);
      expect(draft.minimumRefusal?.maximumEurCents, 50000);
      expect(draft.perKgRefusal, isNull);
      draft.minimum.text = '10';
      expect(draft.minimumRefusal, isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('Find Travelers and the propose sheet', () {
    FakeBackend backend0({Map<String, dynamic>? listed, int count = 1}) =>
        _backend()
          ..on(
            'GET',
            '/api/matches/find-travelers',
            FakeResponse(
              200,
              pageFixture(
                total: count,
                candidates: [
                  for (var i = 0; i < count; i++)
                    candidateFixture(
                      journeyId: 101 + i,
                      travelerName: 'Karim${i == 0 ? '' : ' $i'}',
                      economics: _economics(listed: listed),
                    ),
                ],
              ),
            ),
          )
          ..handle(
            'POST',
            '/api/matches/propose',
            (_) => FakeResponse(201, {'id': 1, 'match': 77}),
          );

    testWidgets('the card shows the listed price, and the sort is offered', (
      tester,
    ) async {
      final backend = backend0(listed: _listed());
      await _findTravelers(tester, backend);
      final l = _l(tester);

      expect(find.text(l.findTravelersListedPrice('€24.00')), findsOneWidget);
      await tester.tap(find.text(l.findTravelersSortPrice));
      await tester.pumpAndSettle();
      expect(
        backend.to('GET', '/api/matches/find-travelers').last.query['sort'],
        'listed_price',
      );
    });

    testWidgets('no price: no price line, and no sort that does nothing', (
      tester,
    ) async {
      final backend = _backend(policyEnabled: false)
        ..on(
          'GET',
          '/api/matches/find-travelers',
          FakeResponse(200, pageFixture(candidates: [candidateFixture()])),
        );
      await _findTravelers(tester, backend);
      final l = _l(tester);
      expect(
        find.textContaining(RegExp(r'^€\d+\.\d\d for this parcel')),
        findsNothing,
      );
      expect(find.text(l.findTravelersSortPrice), findsNothing);
    });

    testWidgets('a trip card to a sent offer at the listed price: three taps', (
      tester,
    ) async {
      final backend = backend0(listed: _listed());
      await _findTravelers(tester, backend);
      final l = _l(tester);

      await tester.tap(find.text('Karim')); // 1: the card
      await tester.pumpAndSettle();
      await tester.tap(
        find.widgetWithText(FilledButton, l.offerProposeTitle),
      ); // 2
      await tester.pumpAndSettle();

      // The listed price, its fee and the sender's total, all the server's.
      expect(find.text(l.offerListedLabel), findsOneWidget);
      expect(find.text('€24.00'), findsWidgets);
      expect(find.text('€26.40'), findsOneWidget);
      expect(find.byType(AppAmountField), findsNothing);

      await tester.tap(
        find.widgetWithText(FilledButton, l.offerSendListed('€24.00')),
      ); // 3
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/matches/propose')!.body;
      expect(sent['traveler_reward_eur_cents'], 2400);
      expect(sent['journey_id'], 101);
    });

    testWidgets('"Offer a different amount" opens the field with the minimum', (
      tester,
    ) async {
      final backend = backend0(listed: _listed());
      await _findTravelers(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text('Karim'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, l.offerProposeTitle));
      await tester.pumpAndSettle();

      await tester.tap(find.text(l.offerDifferentAmount));
      await tester.pumpAndSettle();

      // The server's minimum is on screen, and the field starts on the listed
      // price so going lower is an edit, not a retype.
      expect(find.text(l.offerBelowMinimum('€18.00')), findsOneWidget);
      expect(
        tester.widget<TextField>(find.byType(TextField).first).controller!.text,
        '24.00',
      );

      await tester.enterText(find.byType(TextField).first, '20');
      await tester.pumpAndSettle();
      expect(find.text(l.offerBelowListedNote), findsOneWidget);

      await tester.tap(find.widgetWithText(FilledButton, l.offerSend));
      await tester.pumpAndSettle();
      expect(
        backend
            .lastTo('POST', '/api/matches/propose')!
            .body['traveler_reward_eur_cents'],
        2000,
      );
    });

    testWidgets('without a price the sheet is exactly what it was', (
      tester,
    ) async {
      final backend = backend0();
      await _findTravelers(tester, backend);
      final l = _l(tester);
      await tester.tap(find.text('Karim'));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(FilledButton, l.offerProposeTitle));
      await tester.pumpAndSettle();

      expect(find.byType(AppAmountField), findsOneWidget);
      expect(find.text(l.offerSend), findsOneWidget);
      expect(find.text(l.offerDifferentAmount), findsNothing);
    });

    testWidgets(
      'a listed price that fell under the minimum moves to the field',
      (tester) async {
        final backend = backend0(listed: _listed())
          ..handle(
            'POST',
            '/api/matches/propose',
            (_) => FakeResponse(409, {
              'code': 'reward_below_minimum',
              'minimum_reward_eur_cents': 2600,
            }),
          );
        await _findTravelers(tester, backend);
        final l = _l(tester);
        await tester.tap(find.text('Karim'));
        await tester.pumpAndSettle();
        await tester.tap(
          find.widgetWithText(FilledButton, l.offerProposeTitle),
        );
        await tester.pumpAndSettle();
        await tester.tap(
          find.widgetWithText(FilledButton, l.offerSendListed('€24.00')),
        );
        await tester.pumpAndSettle();

        expect(find.text(l.offerBelowMinimum('€26.00')), findsWidgets);
        expect(find.byType(AppAmountField), findsOneWidget);
      },
    );
  });

  // -------------------------------------------------------------------------
  group('trip cards', () {
    testWidgets('a priced trip says "from X per kg, minimum Y"', (
      tester,
    ) async {
      final backend = _backend()
        ..handle(
          'GET',
          '/api/discovery/trips',
          (_) => discoveryPage([
            tripCardFixture(1, name: 'Priced', price: _price),
            tripCardFixture(2, name: 'Plain'),
          ]),
        );
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);
      final l = _l(tester);
      expect(
        find.text(l.tripPriceFrom('€12.00', '€15.00')),
        findsOneWidget,
        reason: 'only the priced trip says it',
      );
    });

    testWidgets('the trip preview carries the same price', (tester) async {
      final backend = _backend()
        ..handle(
          'GET',
          '/api/discovery/trips',
          (_) => discoveryPage([
            tripCardFixture(1, name: 'Priced', price: _price),
          ]),
        );
      await pumpDiscovery(tester, const BrowseTripsScreen(), backend);
      final l = _l(tester);
      await tester.tap(find.text('Priced'));
      await tester.pumpAndSettle();
      expect(find.text(l.tripPrice), findsOneWidget);
      // The card underneath and the preview on top.
      expect(find.text(l.tripPriceFrom('€12.00', '€15.00')), findsNWidgets(2));
    });
  });

  // -------------------------------------------------------------------------
  group('the editor', () {
    Future<FakeBackend> pumpEdit(
      WidgetTester tester, {
      bool policyEnabled = true,
      Map<String, dynamic>? price,
      Locale locale = const Locale('en'),
    }) async {
      final backend = _backend(policyEnabled: policyEnabled)
        ..on(
          'GET',
          '/api/journeys/7',
          FakeResponse(200, {...journeyFixture(), 'price': price}),
        )
        ..on(
          'GET',
          '/api/geography/sea-crossings',
          const FakeResponse(200, {'enabled': false, 'crossings': <Object>[]}),
        );
      await pumpDiscovery(
        tester,
        const JourneyEditScreen(journeyId: 7),
        backend,
        locale: locale,
        extraRoutes: const [],
      );
      return backend;
    }

    testWidgets('a route edit resends the stored price', (tester) async {
      final backend = await pumpEdit(tester, price: _price);
      final l = _l(tester);
      await tester.scrollUntilVisible(
        find.text(l.journeyPriceTitle),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text(l.journeyPriceTitle), findsOneWidget);

      backend.handle(
        'PATCH',
        '/api/journeys/7',
        (_) => FakeResponse(200, {...journeyFixture(), 'price': _price}),
      );
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('PATCH', '/api/journeys/7')!.body;
      expect(sent['price_per_kg_eur_cents'], 1200);
      expect(sent['min_price_eur_cents'], 1500);
    });

    testWidgets(
      'with pricing off the fields hide but the price still goes back',
      (tester) async {
        final backend = await pumpEdit(
          tester,
          policyEnabled: false,
          price: _price,
        );
        final l = _l(tester);
        expect(find.text(l.journeyPriceTitle), findsNothing);

        backend.handle(
          'PATCH',
          '/api/journeys/7',
          (_) => FakeResponse(200, {...journeyFixture(), 'price': _price}),
        );
        await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
        await tester.pumpAndSettle();
        final sent = backend.lastTo('PATCH', '/api/journeys/7')!.body;
        expect(sent['price_per_kg_eur_cents'], 1200);
        expect(sent['min_price_eur_cents'], 1500);
      },
    );

    testWidgets('half a price stops the save with a message on the field', (
      tester,
    ) async {
      final backend = await pumpEdit(tester);
      final l = _l(tester);
      final perKg = find.widgetWithText(
        AppAmountField,
        l.journeyPricePerKgLabel,
      );
      await tester.scrollUntilVisible(
        perKg,
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.enterText(
        find.descendant(of: perKg, matching: find.byType(TextField)),
        '12',
      );
      await tester.tap(find.widgetWithText(AppButton, l.journeySaveChanges));
      await tester.pumpAndSettle();
      expect(find.text(l.journeyPriceErrorBoth), findsOneWidget);
      expect(backend.to('PATCH', '/api/journeys/7'), isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  group('the journey page', () {
    Future<FakeBackend> pumpDetail(
      WidgetTester tester, {
      Map<String, dynamic>? price,
      bool policyEnabled = true,
      String status = 'active',
      Locale locale = const Locale('en'),
    }) async {
      final backend = _backend(policyEnabled: policyEnabled)
        ..on(
          'GET',
          '/api/journeys/9',
          FakeResponse(
            200,
            _ownJourney(price: price, status: status, editable: false),
          ),
        )
        ..on(
          'GET',
          '/api/matches/compatible-requests',
          FakeResponse(200, {'candidates': <Object>[]}),
        );
      await pumpDiscovery(
        tester,
        const JourneyDetailScreen(journeyId: 9),
        backend,
        locale: locale,
      );
      return backend;
    }

    testWidgets('shows the price and changes it on its own endpoint', (
      tester,
    ) async {
      final backend = await pumpDetail(tester, price: _price);
      final l = _l(tester);
      await tester.scrollUntilVisible(
        find.text(l.journeyPriceChange),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text(l.journeyPricePerKgValue('€12.00')), findsOneWidget);
      expect(find.text(l.journeyPriceMinimumValue('€15.00')), findsOneWidget);

      await tester.tap(find.text(l.journeyPriceChange));
      await tester.pumpAndSettle();
      backend.handle(
        'PATCH',
        '/api/journeys/9/pricing',
        (_) => FakeResponse(200, _ownJourney(price: _price)),
      );
      await tester.enterText(find.byType(TextField).first, '13.50');
      await tester.tap(find.widgetWithText(AppButton, l.journeyPriceSave));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('PATCH', '/api/journeys/9/pricing')!.body;
      expect(sent, {
        'price_per_kg_eur_cents': 1350,
        'min_price_eur_cents': 1500,
      });
    });

    testWidgets('removing the price sends two nulls', (tester) async {
      final backend = await pumpDetail(tester, price: _price);
      final l = _l(tester);
      await tester.scrollUntilVisible(
        find.text(l.journeyPriceChange),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text(l.journeyPriceChange));
      await tester.pumpAndSettle();
      backend.handle(
        'PATCH',
        '/api/journeys/9/pricing',
        (_) => FakeResponse(200, _ownJourney()),
      );
      await tester.tap(find.widgetWithText(AppButton, l.journeyPriceRemove));
      await tester.pumpAndSettle();
      expect(backend.lastTo('PATCH', '/api/journeys/9/pricing')!.body, {
        'price_per_kg_eur_cents': null,
        'min_price_eur_cents': null,
      });
    });

    testWidgets('a ceiling refusal shows on the field it names', (
      tester,
    ) async {
      final backend = await pumpDetail(tester);
      final l = _l(tester);
      await tester.scrollUntilVisible(
        find.text(l.journeyPriceSet),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      await tester.tap(find.text(l.journeyPriceSet));
      await tester.pumpAndSettle();
      backend.handle(
        'PATCH',
        '/api/journeys/9/pricing',
        (_) => FakeResponse(400, {
          'code': 'journey_price_invalid',
          'reason': 'price_per_kg_above_maximum',
          'max_price_per_kg_eur_cents': 10000,
        }),
      );
      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), '99');
      await tester.enterText(fields.at(1), '20');
      await tester.tap(find.widgetWithText(AppButton, l.journeyPriceSave));
      await tester.pumpAndSettle();
      expect(find.text(l.journeyPriceErrorMaximum('€100.00')), findsOneWidget);
    });

    testWidgets('switched off with no price: no card at all', (tester) async {
      await pumpDetail(tester, policyEnabled: false);
      final l = _l(tester);
      expect(find.text(l.journeyPriceTitle), findsNothing);
    });

    testWidgets('a finished journey shows its price but cannot change it', (
      tester,
    ) async {
      await pumpDetail(tester, price: _price, status: 'completed');
      final l = _l(tester);
      await tester.scrollUntilVisible(
        find.text(l.journeyPriceTitle),
        200,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text(l.journeyPriceChange), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  group('the repository', () {
    test(
      'a whole-route write always carries the price, null included',
      () async {
        final backend = FakeBackend()
          ..on('PATCH', '/api/journeys/9', FakeResponse(200, _ownJourney()))
          ..on('POST', '/api/journeys', FakeResponse(201, _ownJourney()));
        final container = discoveryContainer(backend);
        addTearDown(container.dispose);
        final repo = container.read(journeyRepositoryProvider);

        await repo.update(
          id: 9,
          startPlaceId: 1,
          destinationPlaceId: 2,
          legs: const [],
        );
        expect(
          backend.lastTo('PATCH', '/api/journeys/9')!.body,
          containsPair('price_per_kg_eur_cents', null),
        );

        await repo.create(
          startPlaceId: 1,
          destinationPlaceId: 2,
          legs: const [],
        );
        expect(
          backend
              .lastTo('POST', '/api/journeys')!
              .body
              .containsKey('price_per_kg_eur_cents'),
          isFalse,
          reason: 'a new journey with no price simply has none',
        );
      },
    );
  });
}
