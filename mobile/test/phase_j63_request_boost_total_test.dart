/// Phase J6.3: the posting screen's total is the total the Deal will freeze.
///
/// **The defect.** With a €30.00 reward and a +€5.00 Boost, the request
/// creation card said "Traveler receives €35.00" but "Total sender cost
/// €37.50": the base total, with neither the Boost nor its fee. The Deal would
/// be €43.75. The quote now publishes `chosen_terms` — the same fields an Offer
/// and a Deal carry — and the card prints them. Nothing in Dart adds a Boost.
///
/// **Refresh.** Changing the Boost or the reward re-reads the quote; typing is
/// debounced, a slower earlier answer can never overwrite a newer one, and a
/// figure that no longer matches the form is marked as updating rather than
/// read as the total.
///
/// **Deposit.** The deposit screen's ceiling, "pay in full" and remaining
/// balance are measured from the server's Boost-inclusive obligation, not from
/// the recommendation's base total.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/design/components/money.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/domain/pricing.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _quotePath = '/api/parcels/pricing-quote';

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

/// The quote the fake server gives for one (reward, Boost) pair.
Map<String, dynamic> _answerFor(int? reward, int boost) {
  if (reward == null) return _quote(boost: boost, terms: _unavailable());
  return switch ((reward, boost)) {
    (3000, 0) => _quote(chosen: 3000, terms: _zeroBoost),
    (3000, 500) => _quote(chosen: 3000, boost: 500, terms: _fiveBoost),
    // A Boost commission of 15%, not 25%: a client that priced the Boost
    // itself at the delivery rate would print €2.50 and €50.00 here.
    (3000, 1000) => _quote(
      chosen: 3000,
      boost: 1000,
      terms: _terms(
        reward: 3000,
        fee: 750,
        baseTotal: 3750,
        boost: 1000,
        boostFee: 150,
        travelerTotal: 4000,
        senderTotal: 4900,
      ),
    ),
    (4000, 500) => _quote(
      chosen: 4000,
      boost: 500,
      terms: _terms(
        reward: 4000,
        fee: 1000,
        baseTotal: 5000,
        boost: 500,
        boostFee: 125,
        travelerTotal: 4500,
        senderTotal: 5625,
      ),
    ),
    _ => throw StateError('no fixture for reward $reward, boost $boost'),
  };
}

int? _rewardOf(RecordedRequest r) => r.body['chosen_reward_eur_cents'] as int?;
int _boostOf(RecordedRequest r) => (r.body['boost_eur_cents'] as int?) ?? 0;

FakeBackend _pricingBackend({
  Completer<void>? holdFiveBoost,
  Map<String, dynamic> Function(int?, int)? answers,
}) {
  final answer = answers ?? _answerFor;
  return FakeBackend()..handle('POST', _quotePath, (request) async {
    final reward = _rewardOf(request);
    final boost = _boostOf(request);
    if (boost == 500 && holdFiveBoost != null) await holdFiveBoost.future;
    return FakeResponse(200, answer(reward, boost));
  });
}

CanonicalPlace _place(int id, String name, String country) =>
    CanonicalPlace.fromJson({
      'id': id,
      'country_code': country,
      'place_type': 'locality',
      'name': name,
      'display_label': name,
      'parent_name': '',
      'matching_locality': {'id': id, 'name': name},
    });

RequestCreatePricingSeed _seed() {
  final start = DateTime.now().add(const Duration(days: 1));
  return RequestCreatePricingSeed(
    pickup: _place(101, 'Paris', 'FR'),
    delivery: _place(202, 'Algiers', 'DZ'),
    weightKg: '2.50',
    readyStart: start,
    readyEnd: start.add(const Duration(hours: 2)),
    deadline: start.add(const Duration(days: 2)),
  );
}

Future<L> _pumpCreate(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
  bool settle = true,
}) async {
  await pumpApp(
    tester,
    RequestCreateScreen(debugPricingSeed: _seed()),
    container: containerFor(backend),
    locale: locale,
    device: device,
  );
  if (settle) await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(RequestCreateScreen)));
}

Future<void> _reveal(WidgetTester tester, Finder target) async {
  await tester.scrollUntilVisible(
    target,
    160,
    scrollable: find.byType(Scrollable).first,
    maxScrolls: 60,
  );
  await tester.pumpAndSettle();
}

String _eur(int cents, [Locale locale = const Locale('en')]) =>
    Money.eurCents(cents).format(locale);

/// The label → amount pairs the totals card shows, top to bottom.
List<(String, String)> _cardLines(WidgetTester tester) {
  final breakdown = find.descendant(
    of: find.byKey(const ValueKey('request-pricing-totals')),
    matching: find.byType(MoneyBreakdown),
  );
  if (breakdown.evaluate().isEmpty) return const [];
  final widget = tester.widget<MoneyBreakdown>(breakdown);
  final locale = Localizations.localeOf(tester.element(breakdown));
  return [
    for (final line in widget.lines) (line.label, line.amount.format(locale)),
  ];
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
  group('the request creation card prints the server totals', () {
    testWidgets('zero Boost stays three lines and says €37.50', (tester) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.moneyYouPay));

      expect(_cardLines(tester), [
        (l.moneyTravelerReceives, '€30.00'),
        (l.moneyPlatformFee, '€7.50'),
        (l.moneyYouPay, '€37.50'),
      ]);
      expect(find.text(l.moneyBoostBonus), findsNothing);
      expect(find.text(l.moneyBoostFee), findsNothing);
      // The old base-only label is gone from this card.
      expect(find.text(l.pricingTotalSenderCost), findsNothing);
    });

    testWidgets('+€5 reads base, Boost, Traveler total, both fees, €43.75', (
      tester,
    ) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();

      final sent = backend.lastTo('POST', _quotePath)!;
      expect(_rewardOf(sent), 3000);
      expect(_boostOf(sent), 500);

      await _reveal(tester, find.text(l.moneyYouPay));
      expect(_cardLines(tester), [
        (l.moneyBaseReward, '€30.00'),
        (l.moneyBoostBonus, '€5.00'),
        (l.moneyTravelerReceives, '€35.00'),
        (l.moneyPlatformFee, '€7.50'),
        (l.moneyBoostFee, '€1.25'),
        (l.moneyYouPay, '€43.75'),
      ]);
      expect(find.text('€37.50'), findsNothing);
    });

    testWidgets('+€10 at a 15% Boost rate prints €1.50 and €49.00', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _pricingBackend());
      await _reveal(tester, find.text(l.boostPreset10));
      await tester.tap(find.text(l.boostPreset10));
      await tester.pumpAndSettle();
      await _reveal(tester, find.text(l.moneyYouPay));

      final lines = _cardLines(tester);
      expect(lines, contains((l.moneyBoostFee, '€1.50')));
      expect(lines, contains((l.moneyTravelerReceives, '€40.00')));
      expect(lines.last, (l.moneyYouPay, '€49.00'));
    });

    testWidgets('an inconsistent server total is printed, not corrected', (
      tester,
    ) async {
      final backend = _pricingBackend(
        answers: (reward, boost) => boost == 500
            ? _quote(
                chosen: 3000,
                boost: 500,
                terms: _terms(
                  reward: 3000,
                  fee: 750,
                  baseTotal: 3750,
                  boost: 500,
                  boostFee: 125,
                  travelerTotal: 1234,
                  senderTotal: 9999,
                ),
              )
            : _answerFor(reward, boost),
      );
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      await _reveal(tester, find.text(l.moneyYouPay));

      expect(_cardLines(tester), contains((l.moneyTravelerReceives, '€12.34')));
      expect(_cardLines(tester).last, (l.moneyYouPay, '€99.99'));
      expect(find.text('€43.75'), findsNothing);
      expect(find.text('€35.00'), findsNothing);
    });

    testWidgets('an empty reward is prefilled, then priced once more', (
      tester,
    ) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);

      final calls = backend.to('POST', _quotePath);
      expect(calls.map(_rewardOf).toList(), [null, 3000]);
      await _reveal(tester, find.text(l.moneyYouPay));
      expect(_cardLines(tester).last, (l.moneyYouPay, '€37.50'));
    });
  });

  // -------------------------------------------------------------------------
  group('the quote refreshes when the reward or Boost moves', () {
    testWidgets('removing the Boost re-reads and drops the Boost lines', (
      tester,
    ) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.boostPresetNone));
      await tester.pumpAndSettle();

      expect(backend.to('POST', _quotePath).map(_boostOf).toList(), [
        0,
        0,
        500,
        0,
      ]);
      await _reveal(tester, find.text(l.moneyYouPay));
      expect(_cardLines(tester).last, (l.moneyYouPay, '€37.50'));
      expect(find.text(l.moneyBoostFee), findsNothing);
    });

    testWidgets('re-tapping the chosen Boost costs no read', (tester) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      final before = backend.to('POST', _quotePath).length;
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      expect(backend.to('POST', _quotePath).length, before);
    });

    testWidgets('a slow answer for an older Boost never replaces a newer one', (
      tester,
    ) async {
      final hold = Completer<void>();
      final backend = _pricingBackend(holdFiveBoost: hold);
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));

      await tester.tap(find.text(l.boostPreset5));
      await tester.pump();
      // While +€5 is being priced, the €37.50 on screen is not its total: it
      // is dimmed, hidden from screen readers and marked as updating.
      expect(find.bySemanticsLabel(l.pricingUpdating), findsOneWidget);
      expect(
        find.ancestor(
          of: find.byKey(const ValueKey('request-pricing-totals')),
          matching: find.byType(ExcludeSemantics),
        ),
        findsWidgets,
      );

      // The sender changes their mind before the +€5 answer arrives.
      await tester.tap(find.text(l.boostPresetNone));
      await tester.pump(const Duration(milliseconds: 50));
      hold.complete();
      await tester.pump(const Duration(milliseconds: 50));
      await tester.pumpAndSettle();

      await _reveal(tester, find.text(l.moneyYouPay));
      expect(_cardLines(tester).last, (l.moneyYouPay, '€37.50'));
      expect(find.text('€43.75'), findsNothing);
      expect(find.bySemanticsLabel(l.pricingUpdating), findsNothing);
    });

    testWidgets('typing a reward is debounced into one read', (tester) async {
      final backend = _pricingBackend();
      final l = await _pumpCreate(tester, backend);
      await _reveal(tester, find.text(l.boostPreset5));
      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      final before = backend.to('POST', _quotePath).length;

      // The reward field, by what it holds: the prefilled recommendation.
      final prefilled = find.byWidgetPredicate(
        (w) => w is TextField && w.controller?.text == '30.00',
      );
      await _reveal(tester, prefilled);
      final controller = tester.widget<TextField>(prefilled).controller;
      final field = find.byWidgetPredicate(
        (w) => w is TextField && identical(w.controller, controller),
      );
      for (final text in ['4', '40', '40.', '40.0', '40.00']) {
        await tester.enterText(field, text);
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(backend.to('POST', _quotePath).length, before);
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pumpAndSettle();

      final reads = backend.to('POST', _quotePath).skip(before).toList();
      expect(reads, hasLength(1));
      expect(_rewardOf(reads.single), 4000);
      expect(_boostOf(reads.single), 500);
      await _reveal(tester, find.text(l.moneyYouPay));
      expect(_cardLines(tester), contains((l.moneyTravelerReceives, '€45.00')));
      expect(_cardLines(tester).last, (l.moneyYouPay, '€56.25'));
    });
  });

  // -------------------------------------------------------------------------
  group('French and Arabic', () {
    for (final locale in const [Locale('fr'), Locale('ar')]) {
      testWidgets('+€5 in ${locale.languageCode} on a small phone', (
        tester,
      ) async {
        final l = await _pumpCreate(
          tester,
          _pricingBackend(),
          locale: locale,
          device: DeviceProfile.smallAndroid,
        );
        await _reveal(tester, find.text(l.boostPreset5));
        await tester.tap(find.text(l.boostPreset5));
        await tester.pumpAndSettle();
        await _reveal(tester, find.text(l.moneyYouPay));

        expect(_cardLines(tester), [
          (l.moneyBaseReward, _eur(3000, locale)),
          (l.moneyBoostBonus, _eur(500, locale)),
          (l.moneyTravelerReceives, _eur(3500, locale)),
          (l.moneyPlatformFee, _eur(750, locale)),
          (l.moneyBoostFee, _eur(125, locale)),
          (l.moneyYouPay, _eur(4375, locale)),
        ]);
        expect(find.text(_eur(4375, locale)), findsOneWidget);
        expect(
          Directionality.of(tester.element(find.text(l.moneyYouPay))),
          locale.languageCode == 'ar' ? TextDirection.rtl : TextDirection.ltr,
        );
        expect(tester.takeException(), isNull);
      });
    }
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
