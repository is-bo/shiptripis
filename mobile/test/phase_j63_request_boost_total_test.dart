/// Phase J6.3: the Boost-inclusive totals are the server's, and nothing is
/// recomputed in Dart.
///
/// **The defect.** With a €30.00 reward and a +€5.00 Boost, a screen said
/// "Traveler receives €35.00" but "Total sender cost €37.50": the base total,
/// with neither the Boost nor its fee. The Deal would be €43.75. The quote now
/// publishes `chosen_terms` — the same fields an Offer and a Deal carry — and
/// screens print them.
///
/// **Deposit.** The deposit screen's ceiling, "pay in full" and remaining
/// balance are measured from the server's Boost-inclusive obligation, not from
/// the recommendation's base total.
///
/// **What moved out of this file (J7A).** The request *creation* screen used to
/// carry Boost chips, and this file drove them to prove the refresh, the
/// stale-response guard and the itemised card. Creation no longer offers a
/// Boost at all, so those cases would be testing a control that is gone. The
/// refresh, the debounce and the latest-answer-wins guard are asserted against
/// the offer itself in `phase_j7a_request_create_ux_test.dart`; the itemised
/// Boost reading is asserted where a Boost can exist, on the Offer and Deal
/// surfaces in `phase_j61_offer_boost_projection_test.dart` and
/// `phase_j62_boost_copy_offer_refresh_test.dart`.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/domain/pricing.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures — server answers, written out literally. The fake server does no
// arithmetic either, so a test can tell a read value from a computed one.
// ---------------------------------------------------------------------------

Map<String, dynamic> _terms({
  required int reward,
  required int fee,
  required int baseTotal,
  int boost = 0,
  int boostFee = 0,
  required int travelerTotal,
  required int senderTotal,
  String status = 'provisional',
}) => {
  'terms_status': status,
  'currency': 'EUR',
  'traveler_reward_minor': reward,
  'commission_rate_bps': 2500,
  'platform_fee_minor': fee,
  'sender_total_minor': baseTotal,
  'boost_economics_version': 'additive_commission_v2',
  'boost_amount_minor': boost,
  'boost_traveler_bonus_minor': boost,
  'boost_platform_fee_minor': boostFee,
  'traveler_total_minor': travelerTotal,
  'sender_total_with_boost_minor': senderTotal,
};

final _zeroBoost = _terms(
  reward: 3000,
  fee: 750,
  baseTotal: 3750,
  travelerTotal: 3000,
  senderTotal: 3750,
);

final _fiveBoost = _terms(
  reward: 3000,
  fee: 750,
  baseTotal: 3750,
  boost: 500,
  boostFee: 125,
  travelerTotal: 3500,
  senderTotal: 4375,
);

Map<String, dynamic> _unavailable() => {
  'terms_status': 'unavailable',
  'currency': 'EUR',
  for (final key in [
    'traveler_reward_minor',
    'commission_rate_bps',
    'platform_fee_minor',
    'sender_total_minor',
    'boost_economics_version',
    'boost_amount_minor',
    'boost_traveler_bonus_minor',
    'boost_platform_fee_minor',
    'traveler_total_minor',
    'sender_total_with_boost_minor',
  ])
    key: null,
};

Map<String, dynamic> _quote({
  int? chosen,
  int boost = 0,
  required Map<String, dynamic> terms,
}) => {
  'currency': 'EUR',
  'minimum_reward_eur_cents': 2000,
  'recommended_reward_eur_cents': 3000,
  'chosen_reward_eur_cents': chosen,
  'minimum_economics': {
    'traveler_reward_minor': 2000,
    'platform_fee_minor': 500,
    'sender_total_minor': 2500,
  },
  'recommended_economics': {
    'traveler_reward_minor': 3000,
    'platform_fee_minor': 750,
    'sender_total_minor': 3750,
  },
  'chosen_economics': chosen == null
      ? null
      : {
          'traveler_reward_minor': terms['traveler_reward_minor'],
          'platform_fee_minor': terms['platform_fee_minor'],
          'sender_total_minor': terms['sender_total_minor'],
        },
  'chosen_is_below_minimum': false,
  'chosen_is_below_recommended': false,
  'commission_rate_bps': 2500,
  'pricing_version': 'v1',
  'business_settings_version': 7,
  'boost': {
    'economics_version': 'additive_commission_v2',
    'currency': 'EUR',
    'boost_eur_cents': boost,
    'boost_commission_rate_bps': 2500,
    'boost_traveler_bonus_eur_cents': boost,
    'boost_platform_fee_eur_cents': terms['boost_platform_fee_minor'] ?? 0,
    'boost_sender_cost_eur_cents': boost == 0 ? 0 : 625,
    'base_reward_eur_cents': ?chosen,
    if (chosen != null)
      'total_offered_reward_eur_cents': terms['traveler_total_minor'],
  },
  'chosen_terms': terms,
  'deposit': {
    'currency': 'EUR',
    'required': true,
    'recommended_eur_cents': 375,
    'minimum_eur_cents': 300,
    'percent_bps': 1000,
    'recommendation_basis_eur_cents': 3750,
    'maximum_eur_cents': terms['sender_total_with_boost_minor'],
    'is_flexible': true,
  },
};

Future<void> _reveal(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    160,
    scrollable: find.byType(Scrollable).first,
    maxScrolls: 60,
  );
  await tester.pumpAndSettle();
}

void main() {
  // -------------------------------------------------------------------------
  group('the pricing contract carries the Boost-inclusive totals', () {
    test('zero Boost: the total is the base total, and no Boost is named', () {
      final quote = PostingPricingQuote.fromJson(
        _quote(chosen: 3000, terms: _zeroBoost),
      );
      final terms = quote.chosenTerms;
      expect(terms.hasTotals, isTrue);
      expect(terms.hasBoost, isFalse);
      expect(terms.travelerTotal, Money.eurCents(3000));
      expect(terms.platformFee, Money.eurCents(750));
      expect(terms.senderTotalWithBoost, Money.eurCents(3750));
      expect(quote.deposit.maximumDeposit, Money.eurCents(3750));
    });

    test('+€5 Boost: Traveler total, Boost fee and sender total are read', () {
      final quote = PostingPricingQuote.fromJson(
        _quote(chosen: 3000, boost: 500, terms: _fiveBoost),
      );
      final terms = quote.chosenTerms;
      expect(terms.hasBoost, isTrue);
      expect(terms.baseReward, Money.eurCents(3000));
      expect(terms.boostAmount, Money.eurCents(500));
      expect(terms.travelerTotal, Money.eurCents(3500));
      expect(terms.boostFee, Money.eurCents(125));
      // The base total keeps its meaning and is not the obligation.
      expect(terms.baseSenderTotal, Money.eurCents(3750));
      expect(terms.senderTotalWithBoost, Money.eurCents(4375));
      expect(quote.chosenEconomics?.senderTotal, Money.eurCents(3750));
      expect(quote.deposit.maximumDeposit, Money.eurCents(4375));
    });

    test('a custom Boost at a different rate is whatever the server says', () {
      // €7.77 at 15%: ceil(116.55) = 117. Written out, not derived.
      final terms = ChosenTerms.fromJson(
        _terms(
          reward: 3001,
          fee: 751,
          baseTotal: 3752,
          boost: 777,
          boostFee: 117,
          travelerTotal: 3778,
          senderTotal: 4646,
        ),
      );
      expect(terms.boostFee, Money.eurCents(117));
      expect(terms.travelerTotal, Money.eurCents(3778));
      expect(terms.senderTotalWithBoost, Money.eurCents(4646));
    });

    test(
      'nothing is recomputed: an inconsistent server answer is shown as is',
      () {
        // Deliberately not base + Boost + fee. A client that added the parts
        // up would print €43.75 and €35.00.
        final terms = ChosenTerms.fromJson(
          _terms(
            reward: 3000,
            fee: 750,
            baseTotal: 3750,
            boost: 500,
            boostFee: 125,
            travelerTotal: 1234,
            senderTotal: 9999,
          ),
        );
        expect(terms.travelerTotal, Money.eurCents(1234));
        expect(terms.senderTotalWithBoost, Money.eurCents(9999));
      },
    );

    test('no chosen reward, or no block at all, publishes no totals', () {
      expect(ChosenTerms.fromJson(_unavailable()).hasTotals, isFalse);
      expect(ChosenTerms.fromJson(null).hasTotals, isFalse);
      final quote = PostingPricingQuote.fromJson(
        _quote(boost: 500, terms: _unavailable()),
      );
      expect(quote.chosenTerms.hasTotals, isFalse);
      expect(quote.boost.totalOfferedReward, isNull);
      expect(quote.deposit.maximumDeposit, isNull);
    });

    test('the recommendation clamp is never read as the deposit ceiling', () {
      final pricing = PostingDepositQuote.fromJson(const {
        'recommended_eur_cents': 375,
        'max_eur_cents': 700,
      });
      expect(pricing.maximumDeposit, isNull);
      final deposit = DepositQuote.maybe(const {
        'amount_eur_cents': 375,
        'max_eur_cents': 700,
        'clamped': '',
      })!;
      expect(deposit.maximum, isNull);
      expect(
        DepositQuote.maybe(const {
          'max_eur_cents': 700,
          'maximum_eur_cents': 4375,
          'clamped': '',
        })!.maximum,
        Money.eurCents(4375),
      );
    });

    test('the Boost block reads the keys the server actually sends', () {
      final boost = PricingBoostQuote.fromJson(
        _quote(chosen: 3000, boost: 500, terms: _fiveBoost)['boost']
            as Map<String, dynamic>,
      );
      expect(boost.amount, Money.eurCents(500));
      expect(boost.travelerBonus, Money.eurCents(500));
      expect(boost.commissionFee, Money.eurCents(125));
      expect(boost.senderCost, Money.eurCents(625));
      expect(boost.totalOfferedReward, Money.eurCents(3500));
    });
  });

  // -------------------------------------------------------------------------
  group('the deposit is measured against the Boost-inclusive obligation', () {
    FakeBackend depositBackend({required int maximum}) => FakeBackend()
      ..on(
        'GET',
        '/api/parcels/42/posting-deposit',
        FakeResponse(200, {
          'timing_mode': 'posting_deposit',
          'deposit_required': true,
          'request_status': 'awaiting_deposit',
          'quote': {
            'amount_eur_cents': 375,
            'recommended_eur_cents': 375,
            'currency': 'EUR',
            'percent_bps': 1000,
            'min_eur_cents': 300,
            'minimum_eur_cents': 300,
            // The recommendation clamp and the recommended base total: neither
            // is a ceiling.
            'max_eur_cents': 700,
            'estimated_sender_total_eur_cents': 2500,
            'maximum_eur_cents': maximum,
            'clamped': '',
          },
        }),
      );

    Future<L> pumpDeposit(WidgetTester tester, int maximum) async {
      await pumpApp(
        tester,
        const DepositScreen(requestId: 42),
        container: containerFor(depositBackend(maximum: maximum)),
      );
      await tester.pumpAndSettle();
      return L.of(tester.element(find.byType(DepositScreen)));
    }

    testWidgets('pay in full is €43.75, not the €25.00 suggested base', (
      tester,
    ) async {
      final l = await pumpDeposit(tester, 4375);

      expect(find.text(l.depositWholeAmount), findsOneWidget);
      expect(find.text(l.depositPresetFull('€43.75')), findsOneWidget);
      expect(find.text(l.depositPresetFull('€25.00')), findsNothing);
      // The recommended deposit leaves the obligation less the deposit.
      await _reveal(tester, find.text(l.depositRemainingBalance));
      expect(find.text('€40.00'), findsOneWidget);
    });

    testWidgets('a Boost change moves the ceiling the field enforces', (
      tester,
    ) async {
      final l = await pumpDeposit(tester, 3750);
      await tester.ensureVisible(find.text(l.depositPresetCustom));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.depositPresetCustom));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byType(TextField).first);
      await tester.enterText(find.byType(TextField).first, '40.00');
      await tester.pumpAndSettle();
      expect(find.text(l.depositAboveMaximum('€37.50')), findsOneWidget);
    });

    testWidgets('with a Boost priced in, €40.00 is within the ceiling', (
      tester,
    ) async {
      final l = await pumpDeposit(tester, 4375);
      await tester.ensureVisible(find.text(l.depositPresetCustom));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.depositPresetCustom));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byType(TextField).first);
      await tester.enterText(find.byType(TextField).first, '40.00');
      await tester.pumpAndSettle();
      expect(find.textContaining('€43.75'), findsWidgets);
      expect(find.text(l.depositAboveMaximum('€43.75')), findsNothing);
    });
  });
}
