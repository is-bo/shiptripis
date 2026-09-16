/// Phase J6.1: an offer's money includes the Boost, and the server says so.
///
/// Before J6.1 an Offer carried the base reward and nothing else, so a
/// Traveler with a €30.00 base and a €5.00 Boost read "You receive €30.00" at
/// the moment they decided whether to accept €35.00. The server now publishes
/// the Boost and the totals that include it, under the names a Deal's terms
/// already use. These tests hold the client to rendering those — never adding
/// them up — and to sending back what it showed when accepting.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/money.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/domain/money_perspective.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'phase_j5_find_travelers_test.dart' as j5;
import 'support/fake_api.dart';
import 'support/harness.dart';

const _viewerId = 42;
const _otherPartyId = 99;
const _en = Locale('en');

String _eur(int cents) => Money.eurCents(cents).format(_en);

/// An offer as the J6.1 server publishes it. Base €30.00 at a 25% commission;
/// [boost] is added on top with its own 25% commission. The totals below are
/// fixture data standing in for the server — the app under test never
/// computes them.
Map<String, dynamic> _offer({
  int id = 1,
  int boost = 500,
  int boostFee = 125,
  String status = 'pending',
  String boostTermsStatus = 'provisional',
  bool viewerProposed = false,
  bool viewerIsSender = false,
  List<String> allowedActions = const ['accept', 'counter', 'decline'],
  int? travelerTotal,
  int? senderTotal,
}) {
  final available = boostTermsStatus != 'unavailable';
  final proposerIsSender = viewerProposed == viewerIsSender;
  return {
    'id': id,
    'match': 77,
    'parent_offer': null,
    'proposed_by': proposerIsSender ? 'sender' : 'traveler',
    'proposer_id': viewerProposed ? _viewerId : _otherPartyId,
    'economics_version': 'v1_eur',
    'currency': 'EUR',
    'traveler_reward_minor': 3000,
    'commission_rate_bps': 2500,
    'platform_fee_minor': 750,
    'sender_total_minor': 3750,
    'boost_terms_status': boostTermsStatus,
    'boost_economics_version': available ? 'additive_commission_v2' : null,
    'boost_amount_minor': available ? boost : null,
    'boost_traveler_bonus_minor': available ? boost : null,
    'boost_platform_fee_minor': available ? boostFee : null,
    'traveler_total_minor': available ? (travelerTotal ?? 3000 + boost) : null,
    'sender_total_with_boost_minor': available
        ? (senderTotal ?? 3750 + boost + boostFee)
        : null,
    'status': status,
    'note': '',
    'awaiting_party': status == 'pending'
        ? (proposerIsSender ? 'traveler' : 'sender')
        : null,
    'awaiting_user_id': status == 'pending'
        ? (viewerProposed ? _otherPartyId : _viewerId)
        : null,
    'allowed_actions': allowedActions,
  };
}

Map<String, dynamic> _match({
  required bool viewerIsSender,
  required Map<String, dynamic> latestOffer,
}) => {
  'id': 77,
  'parcel_id': 12,
  'journey_id': 21,
  'start_leg_id': 31,
  'end_leg_id': 32,
  'sender_id': viewerIsSender ? _viewerId : _otherPartyId,
  'traveler_id': viewerIsSender ? _otherPartyId : _viewerId,
  'sender_name': viewerIsSender ? 'Amina' : 'Karim',
  'traveler_name': viewerIsSender ? 'Karim' : 'Amina',
  'status': 'pending',
  'latest_offer': latestOffer,
  'parcel': {
    'id': 12,
    'kind': 'delivery',
    'actual_weight_kg': '2.50',
    'origin': {'id': 1, 'name': 'Paris', 'country_code': 'FR'},
    'destination': {'id': 2, 'name': 'Alger', 'country_code': 'DZ'},
  },
};

FakeBackend _backend({
  required bool viewerIsSender,
  required Map<String, dynamic> Function() latest,
  List<Map<String, dynamic>> Function()? history,
}) => FakeBackend()
  ..on('GET', '/api/me', FakeResponse(200, meFixture()))
  ..handle(
    'GET',
    '/api/matches/77',
    (_) => FakeResponse(
      200,
      _match(viewerIsSender: viewerIsSender, latestOffer: latest()),
    ),
  )
  ..handle(
    'GET',
    '/api/matches/77/offers',
    (_) => FakeResponse(200, history?.call() ?? [latest()]),
  );

Future<L> _pump(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = _en,
  DeviceProfile device = DeviceProfile.android,
}) async {
  await pumpApp(
    tester,
    const NegotiationScreen(matchId: 77),
    container: containerFor(backend),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(NegotiationScreen)));
}

void main() {
  group('the offer contract', () {
    test('reads base, Boost and both totals, and chooses only totals', () {
      final offer = Offer.fromJson(_offer());

      expect(offer.travelerReward, Money.eurCents(3000));
      expect(offer.senderTotal, Money.eurCents(3750));
      expect(offer.boostTermsStatus, BoostTermsStatus.provisional);
      expect(offer.boostAmount, Money.eurCents(500));
      expect(offer.boostTravelerBonus, Money.eurCents(500));
      expect(offer.boostPlatformFee, Money.eurCents(125));
      expect(offer.travelerTotal, Money.eurCents(3500));
      expect(offer.senderTotalWithBoost, Money.eurCents(4375));
      expect(offer.hasBoost, isTrue);
      expect(offer.amountFor(MoneyPerspective.traveler), Money.eurCents(3500));
      expect(offer.amountFor(MoneyPerspective.sender), Money.eurCents(4375));
    });

    test('a closed offer has no total and never falls back to the base', () {
      final offer = Offer.fromJson(
        _offer(status: 'countered', boostTermsStatus: 'unavailable'),
      );

      expect(offer.boostTermsStatus, BoostTermsStatus.unavailable);
      expect(offer.travelerReward, Money.eurCents(3000));
      expect(offer.hasTotals, isFalse);
      expect(offer.hasBoost, isFalse);
      // A fallback to the base reward here is the exact understatement J6.1
      // removed, so there is none.
      expect(offer.amountFor(MoneyPerspective.traveler), isNull);
      expect(offer.amountFor(MoneyPerspective.sender), isNull);
    });

    test('an accepted offer states the same totals as the Deal it became', () {
      final offer = Offer.fromJson(
        _offer(status: 'accepted', boostTermsStatus: 'frozen'),
      );
      final terms = DealTerms.maybe({
        'currency': 'EUR',
        'traveler_reward_minor': 3000,
        'commission_rate_bps': 2500,
        'platform_fee_minor': 750,
        'sender_total_minor': 3750,
        'boost_amount_minor': 500,
        'boost_traveler_bonus_minor': 500,
        'boost_platform_fee_minor': 125,
        'traveler_total_minor': 3500,
        'platform_total_minor': 875,
        'sender_total_with_boost_minor': 4375,
        'is_legacy': false,
      })!;

      expect(offer.boostTermsStatus, BoostTermsStatus.frozen);
      for (final perspective in MoneyPerspective.values) {
        expect(offer.amountFor(perspective), terms.totalFor(perspective));
      }
      expect(offer.boostTravelerBonus, terms.boostTravelerBonus);
      expect(offer.boostPlatformFee, terms.boostPlatformFee);
    });
  });

  group('the Traveler deciding on an offer', () {
    testWidgets('sees the total they are paid as the dominant figure', (
      tester,
    ) async {
      final backend = _backend(viewerIsSender: false, latest: _offer);
      final l = await _pump(tester, backend);

      final hero = tester.widget<MoneyHero>(find.byType(MoneyHero));
      expect(hero.amount, Money.eurCents(3500));
      expect(hero.label, l.moneyYouReceive);
      // The base and the Boost sit under it, as a breakdown, not as the hero.
      expect(find.text(l.moneyBaseReward), findsOneWidget);
      expect(find.text(l.moneyBoostBonus), findsOneWidget);
      expect(find.textContaining(_eur(3000)), findsOneWidget);
      expect(find.textContaining(_eur(500)), findsWidgets);
      expect(
        find.text(l.offerBoostIncludedTraveler(_eur(500))),
        findsOneWidget,
      );
      // No checkout framing for the Traveler.
      expect(find.text(l.moneyYouPay), findsNothing);
      expect(find.text(l.moneyPlatformBoostRevenue), findsNothing);
    });

    testWidgets('a zero Boost stays exactly as clean as before', (
      tester,
    ) async {
      final backend = _backend(
        viewerIsSender: false,
        latest: () => _offer(boost: 0, boostFee: 0),
      );
      final l = await _pump(tester, backend);

      final hero = tester.widget<MoneyHero>(find.byType(MoneyHero));
      expect(hero.amount, Money.eurCents(3000));
      expect(find.text(l.moneyBoostBonus), findsNothing);
      expect(find.text(l.moneyBaseReward), findsNothing);
      expect(find.byType(MoneyBreakdown), findsNothing);
      expect(find.textContaining('Boost'), findsNothing);
    });

    testWidgets('confirms and sends back the total it showed', (tester) async {
      final backend = _backend(viewerIsSender: false, latest: _offer)
        ..on(
          'POST',
          '/api/offers/1/accept',
          const FakeResponse(409, {
            'code': 'offer_economics_changed',
            'detail': 'This offer\'s amounts changed.',
          }),
        );
      final l = await _pump(tester, backend);

      await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
      await tester.pumpAndSettle();
      expect(
        find.text(l.offerAcceptTravelerConfirmTitle(_eur(3500))),
        findsOneWidget,
      );
      await tester.tap(find.widgetWithText(TextButton, l.offerAccept));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', '/api/offers/1/accept')!;
      expect(sent.body, {
        'traveler_total_minor': 3500,
        'sender_total_with_boost_minor': 4375,
      });
    });

    testWidgets('a Boost changed underneath refreshes and says so', (
      tester,
    ) async {
      var boost = 500;
      final backend = _backend(
        viewerIsSender: false,
        latest: () => _offer(boost: boost, boostFee: boost == 0 ? 0 : 125),
      );
      backend.handle('POST', '/api/offers/1/accept', (_) {
        // The sender removed their Boost while the dialog was open.
        boost = 0;
        return const FakeResponse(409, {
          'code': 'offer_economics_changed',
          'detail': 'This offer\'s amounts changed.',
          'current_economics': {
            'boost_amount_minor': 0,
            'traveler_total_minor': 3000,
            'sender_total_with_boost_minor': 3750,
          },
        });
      });
      final l = await _pump(tester, backend);
      expect(
        tester.widget<MoneyHero>(find.byType(MoneyHero)).amount,
        Money.eurCents(3500),
      );

      await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, l.offerAccept));
      await tester.pumpAndSettle();

      expect(find.text(l.staleOfferEconomicsChanged), findsOneWidget);
      // The screen re-read the offer rather than keep a figure that no longer
      // binds.
      expect(
        tester.widget<MoneyHero>(find.byType(MoneyHero)).amount,
        Money.eurCents(3000),
      );
      expect(find.text(l.moneyBoostBonus), findsNothing);
    });

    testWidgets(
      'countering names the field as the base, with the Boost on top',
      (tester) async {
        final backend = _backend(viewerIsSender: false, latest: _offer);
        final l = await _pump(tester, backend);

        await tester.tap(find.widgetWithText(AppButton, l.offerCounter));
        await tester.pumpAndSettle();
        final field = find.byType(AppAmountField);
        expect(
          find.descendant(
            of: field,
            matching: find.text(l.offerBaseRewardLabel),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(
            of: field,
            matching: find.text(l.offerSenderBoostAddedOnTop(_eur(500))),
          ),
          findsOneWidget,
        );
        expect(
          find.descendant(of: field, matching: find.text(l.moneyYouReceive)),
          findsNothing,
        );
      },
    );

    testWidgets('a closed offer in the history is named as a base reward', (
      tester,
    ) async {
      final countered = _offer(
        id: 1,
        status: 'countered',
        boostTermsStatus: 'unavailable',
        allowedActions: const [],
      );
      final current = _offer(
        id: 2,
        viewerProposed: true,
        allowedActions: const ['withdraw'],
        travelerTotal: 3700,
        senderTotal: 4625,
      );
      final backend = _backend(
        viewerIsSender: false,
        latest: () => current,
        history: () => [current, countered],
      );
      final l = await _pump(tester, backend);

      expect(
        find.text(
          l.offerHistoryBaseReward(l.offerSenderOfferTitle, _eur(3000)),
        ),
        findsOneWidget,
      );
      expect(find.text(l.offerSenderOffers(_eur(3000))), findsNothing);
    });

    for (final locale in const [Locale('fr'), Locale('ar')]) {
      testWidgets('the Boost breakdown renders in ${locale.languageCode}', (
        tester,
      ) async {
        final backend = _backend(viewerIsSender: false, latest: _offer);
        final l = await _pump(
          tester,
          backend,
          locale: locale,
          device: locale.languageCode == 'ar'
              ? DeviceProfile.largeText
              : DeviceProfile.smallAndroid,
        );

        expect(find.text(l.moneyYouReceive), findsOneWidget);
        expect(find.text(l.moneyBoostBonus), findsOneWidget);
        expect(tester.takeException(), isNull);
        if (locale.languageCode == 'ar') {
          expect(
            Directionality.of(tester.element(find.byType(NegotiationScreen))),
            TextDirection.rtl,
          );
        }
      });
    }
  });

  group('the Sender reviewing an offer', () {
    testWidgets('reads the same Traveler total and the full amount they pay', (
      tester,
    ) async {
      final backend = _backend(
        viewerIsSender: true,
        latest: () => _offer(viewerIsSender: true),
      );
      final l = await _pump(tester, backend);

      expect(find.text(l.moneyBaseReward), findsOneWidget);
      expect(find.text(l.moneyBoostBonus), findsOneWidget);
      expect(find.text(l.moneyTravelerReceives), findsOneWidget);
      expect(find.text(l.moneyPlatformFee), findsOneWidget);
      expect(find.text(l.moneyPlatformBoostRevenue), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsOneWidget);
      // €30.00 + €5.00 = €35.00 for the Traveler, exactly as their own screen
      // says; €43.75 is everything the sender owes.
      expect(find.textContaining(_eur(3500)), findsOneWidget);
      expect(find.textContaining(_eur(4375)), findsOneWidget);
      expect(find.textContaining(_eur(125)), findsOneWidget);
      expect(find.text(l.offerBoostIncludedSender(_eur(500))), findsOneWidget);

      await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
      await tester.pumpAndSettle();
      expect(
        find.text(l.offerAcceptSenderConfirmTitle(_eur(4375))),
        findsOneWidget,
      );
    });

    testWidgets('a zero Boost keeps the original three lines', (tester) async {
      final backend = _backend(
        viewerIsSender: true,
        latest: () => _offer(viewerIsSender: true, boost: 0, boostFee: 0),
      );
      final l = await _pump(tester, backend);

      expect(find.text(l.moneyTravelerReceives), findsOneWidget);
      expect(find.text(l.moneyPlatformFee), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsOneWidget);
      expect(find.text(l.moneyBaseReward), findsNothing);
      expect(find.text(l.moneyBoostBonus), findsNothing);
      expect(find.text(l.moneyPlatformBoostRevenue), findsNothing);
      expect(find.textContaining('Boost'), findsNothing);
    });

    testWidgets('an offer with no published total is labelled as base only', (
      tester,
    ) async {
      final backend = _backend(
        viewerIsSender: true,
        latest: () => _offer(
          viewerIsSender: true,
          status: 'declined',
          boostTermsStatus: 'unavailable',
          allowedActions: const [],
        ),
      );
      final l = await _pump(tester, backend);

      expect(find.text(l.moneyBaseReward), findsOneWidget);
      expect(find.text(l.moneyTotalExcludingBoost), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsNothing);
      expect(find.text(l.moneyTravelerReceives), findsNothing);
    });
  });

  group('the propose sheet agrees with the offer it sends', () {
    Future<L> pumpSheet(WidgetTester tester) async {
      // Server economics for the recommended €35.00 base, which price the base
      // reward alone and so exclude the request's €5.00 Boost.
      final page = j5.pageFixture(
        candidates: [
          j5.candidateFixture(
            economics: {
              'currency': 'EUR',
              'minimum_reward_eur_cents': 2000,
              'recommended_reward_eur_cents': 3500,
              'recommended_economics': {
                'traveler_reward_minor': 3500,
                'platform_fee_minor': 875,
                'sender_total_minor': 4375,
              },
            },
          ),
        ],
      );
      final repo = j5.FakeMatchingRepository(
        findTravelersHandler:
            ({required parcelId, limit, offset, sort, cancelToken}) async =>
                FindTravelersPage.fromJson(page),
      );
      await pumpApp(
        tester,
        const DiscoveryScreen(requestId: 5),
        container: ProviderContainer(
          overrides: [matchingRepositoryProvider.overrideWithValue(repo)],
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('View trip').first);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Make an offer').first);
      await tester.pumpAndSettle();
      return L.of(tester.element(find.byType(DiscoveryScreen)));
    }

    testWidgets('the request total shows only while it describes this offer', (
      tester,
    ) async {
      final l = await pumpSheet(tester);

      // The request posts €30.00 with a €5.00 Boost. On the chosen reward the
      // server's total is exactly what the submitted offer will publish.
      expect(find.text(l.moneyTravelerReceives), findsOneWidget);
      expect(find.text(_eur(3500)), findsWidgets);

      // A different base would make that total wrong, and the client does not
      // add a Boost to a reward, so the box steps aside.
      await tester.enterText(find.byType(TextField).first, '32.00');
      await tester.pumpAndSettle();
      expect(find.text(l.moneyTravelerReceives), findsNothing);
      expect(find.text(l.offerBoostAddedOnTop(_eur(500))), findsOneWidget);
    });

    testWidgets('the base-only build-up is not called what the sender pays', (
      tester,
    ) async {
      final l = await pumpSheet(tester);

      expect(find.text(l.moneyTotalExcludingBoost), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsNothing);
      // Named as the base it is, not as what the Traveler receives.
      expect(find.text(l.moneyTravelerReceives), findsOneWidget);
    });
  });
}
