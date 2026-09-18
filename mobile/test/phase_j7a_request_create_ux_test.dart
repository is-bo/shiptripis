/// Phase J7A: the request form asks for one price, and Boost is not on it.
///
/// **The product rule.** Before a request exists there is nothing to make more
/// attractive, and a sender who wants a traveller to look harder can simply
/// offer more. So creation asks a single question — what are you offering —
/// against the server's minimum and recommendation, and Boost is what a
/// *published* request can be given afterwards. The economics are untouched:
/// J2's Boost is still extra reward the traveller receives in full with its own
/// fee on top, and it is still the server that says what anything costs.
///
/// **The control.** `− [ 30.00 € ] +` was three unrelated widgets in a row
/// aligned on its top edge, so the buttons sat visibly above the digits they
/// changed and drifted further at larger text. It is now one component, and
/// these tests measure that: same vertical centre, matched heights, a tap
/// target at each end, at every size and in every language.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/money.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/features/requests/boost_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/features/requests/request_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _quotePath = '/api/parcels/pricing-quote';
const _createPath = '/api/parcels/delivery/v1';

/// 1.3× text, which the shared profiles do not carry. The reward control has
/// to survive both the modest bump most people actually use and the 1.6×
/// ceiling.
const _text13 = DeviceProfile(
  name: 'medium text (390x844 @1.3)',
  size: Size(390, 844),
  viewPadding: EdgeInsets.only(top: 47, bottom: 34),
  textScale: 1.3,
);

// ---------------------------------------------------------------------------
// The fake server. It does no arithmetic, so a figure on screen is either one
// of these literals or something the client invented.
// ---------------------------------------------------------------------------

Map<String, dynamic> _terms(int reward, int fee) => {
  'terms_status': 'provisional',
  'currency': 'EUR',
  'traveler_reward_minor': reward,
  'commission_rate_bps': 2500,
  'platform_fee_minor': fee,
  'sender_total_minor': reward + fee,
  'boost_economics_version': 'additive_commission_v2',
  'boost_amount_minor': 0,
  'boost_traveler_bonus_minor': 0,
  'boost_platform_fee_minor': 0,
  'traveler_total_minor': reward,
  'sender_total_with_boost_minor': reward + fee,
};

/// Written out per reward rather than computed, so "€7.50" on screen is this
/// table's €7.50 and not a quarter of something the client multiplied.
const _feeFor = <int, int>{
  2000: 500,
  2500: 625,
  2950: 738,
  3000: 750,
  3050: 763,
  3500: 875,
  4000: 1000,
  5000: 1250,
};

Map<String, dynamic> _quote(int? chosen) {
  final fee = chosen == null ? null : _feeFor[chosen];
  if (chosen != null && fee == null) {
    throw StateError('no fee fixture for a reward of $chosen cents');
  }
  return {
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
            'traveler_reward_minor': chosen,
            'platform_fee_minor': fee,
            'sender_total_minor': chosen + fee!,
          },
    'chosen_is_below_minimum': false,
    'chosen_is_below_recommended': chosen != null && chosen < 3000,
    'commission_rate_bps': 2500,
    'pricing_version': 'v1',
    'boost': {
      'currency': 'EUR',
      'boost_eur_cents': 0,
      'boost_traveler_bonus_eur_cents': 0,
      'boost_platform_fee_eur_cents': 0,
      'boost_sender_cost_eur_cents': 0,
    },
    'chosen_terms': chosen == null
        ? {'terms_status': 'unavailable', 'currency': 'EUR'}
        : _terms(chosen, fee!),
    'deposit': {
      'currency': 'EUR',
      'required': true,
      'recommended_eur_cents': 375,
      'minimum_eur_cents': 300,
      'percent_bps': 1000,
      'recommendation_basis_eur_cents': 3750,
      'maximum_eur_cents': chosen == null ? null : chosen + fee!,
      'is_flexible': true,
    },
  };
}

int? _rewardOf(RecordedRequest r) => r.body['chosen_reward_eur_cents'] as int?;

FakeBackend _backend({Completer<void>? hold, int? holdReward}) =>
    FakeBackend()..handle('POST', _quotePath, (request) async {
      final reward = _rewardOf(request);
      if (hold != null && reward == holdReward) await hold.future;
      return FakeResponse(200, _quote(reward));
    });

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

/// Pumps for [ms] and then a couple of frames.
///
/// `pumpAndSettle` is unusable on this step past the first quote: while the
/// form holds a reward the quote was not priced for, the totals card shows an
/// indeterminate `LinearProgressIndicator`, and an indefinite animation never
/// settles. A fixed tick is also what the debounce assertions need — "one read
/// after 350 ms" is a claim about time, not about quiescence.
Future<void> _tick(WidgetTester tester, [int ms = 400]) async {
  await tester.pump(Duration(milliseconds: ms));
  await tester.pump();
  await tester.pump();
}

/// Scrolls [target] into view, and stops there.
///
/// Scrolling is also what *builds* it: a `ListView` has not created a child it
/// has never reached, so a card below the fold is not in the tree to assert
/// on — and one scrolled past has been recycled out of it again. On a 390-point
/// landscape viewport the offer control and the totals card cannot both be on
/// screen, so each is fetched when it is wanted rather than once at the start.
Future<void> _scrollTo(
  WidgetTester tester,
  Finder target, {
  int delta = 120,
}) async {
  await tester.scrollUntilVisible(
    target,
    delta.toDouble(),
    scrollable: find.byType(Scrollable).first,
    maxScrolls: 80,
  );
  await tester.pump();
}

/// The same, for something above the current position.
Future<void> _scrollBackTo(WidgetTester tester, Finder target) =>
    _scrollTo(tester, target, delta: -120);

Future<L> _pumpCreate(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
  RequestCreatePricingSeed? seed,
  bool routed = false,
}) async {
  // A successful Post replaces this route with the request detail (or the
  // deposit), so the test that posts needs both a router and those two
  // destinations to exist.
  await pumpApp(
    tester,
    RequestCreateScreen(debugPricingSeed: seed ?? _seed()),
    container: containerFor(backend),
    locale: locale,
    device: device,
    routed: routed,
    extraRoutes: routed
        ? [
            GoRoute(
              path: '/posted/:id',
              name: Routes.requestDetail,
              builder: (_, _) => const Scaffold(body: Text('posted')),
            ),
            GoRoute(
              path: '/posted/:id/deposit',
              name: Routes.requestDeposit,
              builder: (_, _) => const Scaffold(body: Text('deposit')),
            ),
          ]
        : const [],
  );
  // Two reads: one with no reward, then one for the prefilled recommendation.
  await _tick(tester);
  await _tick(tester);
  final l = L.of(tester.element(find.byType(RequestCreateScreen)));
  await _scrollTo(tester, find.byType(AppAmountStepper));
  // And back up to the head of the offer section, so a test starts where a
  // sender would: the band, then the control, then the totals below.
  await _scrollBackTo(tester, find.text(l.pricingMinimumLabel));
  return l;
}

/// The one text field inside the reward stepper.
Finder get _rewardField => find.descendant(
  of: find.byType(AppAmountStepper),
  matching: find.byType(TextField),
);

String _rewardText(WidgetTester tester) =>
    tester.widget<TextField>(_rewardField).controller!.text;

Future<void> _typeReward(WidgetTester tester, String value) async {
  await tester.enterText(_rewardField, value);
  await tester.pump();
}

/// The label → amount pairs the totals card shows, top to bottom.
///
/// Scrolls to the card first, because reading a widget that has not been built
/// yet would report "no Boost line" for a card that was never on screen — the
/// emptiest possible pass.
Future<List<(String, String)>> _cardLines(WidgetTester tester) async {
  final breakdown = find.descendant(
    of: find.byKey(const ValueKey('request-pricing-totals')),
    matching: find.byType(MoneyBreakdown),
  );
  await _scrollTo(tester, breakdown);
  final widget = tester.widget<MoneyBreakdown>(breakdown);
  final locale = Localizations.localeOf(tester.element(breakdown));
  return [
    for (final line in widget.lines) (line.label, line.amount.format(locale)),
  ];
}

String _eur(int cents, [Locale locale = const Locale('en')]) =>
    Money.eurCents(cents).format(locale);

/// One end of the stepper, found by the name it gives a screen reader.
///
/// A widget predicate rather than `find.bySemanticsLabel`, which needs the
/// semantics tree switched on; the point here is the box's geometry, and the
/// `Semantics` widget wrapping the control is exactly that box.
Finder _stepControl(String semanticLabel) => find.byWidgetPredicate(
  (w) =>
      w is Semantics &&
      w.properties.label == semanticLabel &&
      (w.properties.button ?? false),
);

Finder _namedSemantics(String label) => find.byWidgetPredicate(
  (w) => w is Semantics && w.properties.label == label,
);

Future<void> _tapStep(WidgetTester tester, String semanticLabel) async {
  await tester.tap(_stepControl(semanticLabel).first, warnIfMissed: false);
  await tester.pump();
}

// ---------------------------------------------------------------------------
// The published request, for the post-publication half.
// ---------------------------------------------------------------------------

Map<String, dynamic> _requestFixture({int boostCents = 0}) => {
  'id': 42,
  'sender_id': 42,
  'status': 'open',
  'schema_version': 3,
  'title': 'Wedding photos album',
  'description': 'A thin album, well wrapped.',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'actual_weight_kg': 2.5,
  'declared_value_eur_cents': 6000,
  'sender_proposed_reward_eur_cents': 3000,
  'boost_eur_cents': boostCents,
  'total_offered_reward_eur_cents': 3000 + boostCents,
  'ready_window_start': '2026-10-01T09:00:00Z',
  'ready_window_end': '2026-10-01T11:00:00Z',
  'deadline_at': '2026-10-03T09:00:00Z',
  'media': <Object>[],
  'pickup_place': {
    'id': 101,
    'country_code': 'FR',
    'place_type': 'locality',
    'name': 'Paris',
    'display_label': 'Paris',
    'parent_name': '',
  },
  'delivery_place': {
    'id': 202,
    'country_code': 'DZ',
    'place_type': 'locality',
    'name': 'Algiers',
    'display_label': 'Algiers',
    'parent_name': '',
  },
};

Map<String, dynamic> _requestPricingFixture({
  int boostCents = 0,
  bool canEditBoost = true,
}) => {
  ..._quote(3000),
  'delivery_request_id': 42,
  'request_status': 'open',
  'boost': {
    'currency': 'EUR',
    'boost_eur_cents': boostCents,
    'boost_traveler_bonus_eur_cents': boostCents,
    'boost_platform_fee_eur_cents': (boostCents * 0.25).round(),
    'boost_sender_cost_eur_cents': boostCents + (boostCents * 0.25).round(),
  },
  'actions': {
    'can_edit_boost': canEditBoost,
    'can_choose_deposit': false,
    'can_cancel': true,
  },
};

Map<String, dynamic> _boostStateFixture({int boostCents = 0}) => {
  'delivery_request_id': 42,
  'request_status': 'open',
  'is_owner': true,
  'ranking_boost_active': false,
  'ranking_boost_weight': 0,
  'affects_compatibility': false,
  'active_count': 0,
  'occupied_slots': 0,
  'purchases': <Object>[],
  'boost_eur_cents': boostCents,
  'can_edit': true,
  'economics': {
    'economics_version': 'additive_commission_v2',
    'currency': 'EUR',
    'boost_eur_cents': boostCents,
    'boost_commission_rate_bps': 1500,
    'boost_traveler_bonus_eur_cents': boostCents,
    'boost_platform_fee_eur_cents': boostCents == 500 ? 75 : 0,
    'boost_sender_cost_eur_cents': boostCents == 500 ? 575 : 0,
    'rounding_rule': 'ceil',
  },
  'policy': {
    'currency': 'EUR',
    'enabled': true,
    'minimum_boost_eur_cents': 100,
    'maximum_boost_eur_cents': 10000,
    'boost_commission_rate_bps': 1500,
    'settings_version': 7,
    'affects_compatibility': false,
    'has_expiry': false,
  },
  'history': <Object>[],
};

FakeBackend _publishedBackend({
  int boostCents = 0,
  bool canEditBoost = true,
  void Function(RecordedRequest)? onSetBoost,
}) {
  var boost = boostCents;
  return FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..handle(
      'GET',
      '/api/parcels/42',
      (_) async => FakeResponse(200, _requestFixture(boostCents: boost)),
    )
    ..handle(
      'GET',
      '/api/parcels/42/pricing',
      (_) async => FakeResponse(
        200,
        _requestPricingFixture(boostCents: boost, canEditBoost: canEditBoost),
      ),
    )
    ..handle(
      'GET',
      '/api/parcels/42/boost',
      (_) async => FakeResponse(200, _boostStateFixture(boostCents: boost)),
    )
    ..handle('PUT', '/api/parcels/42/boost', (request) async {
      onSetBoost?.call(request);
      boost = request.body['boost_eur_cents'] as int;
      return FakeResponse(200, _boostStateFixture(boostCents: boost));
    })
    ..on('GET', '/api/matches', FakeResponse(200, <Object>[]));
}

Future<ProviderContainer> _signedIn(
  WidgetTester tester,
  FakeBackend backend,
) async {
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  return container;
}

/// A seed complete enough to post: every earlier step already answered.
RequestCreatePricingSeed _postableSeed() {
  final base = _seed();
  return RequestCreatePricingSeed(
    pickup: base.pickup,
    delivery: base.delivery,
    weightKg: base.weightKg,
    readyStart: base.readyStart,
    readyEnd: base.readyEnd,
    deadline: base.deadline,
    title: 'Wedding photos album',
    description: 'A thin album, well wrapped.',
    category: ItemCategory.documents,
    declaredValue: '60.00',
    itemPhotoMediaId: 9001,
  );
}

void main() {
  // -------------------------------------------------------------------------
  group('Boost is not offered while the request is being written', () {
    testWidgets('no Boost control, no Boost copy, no Boost fee', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());

      for (final gone in [
        l.boostSectionTitle,
        l.boostPresetNone,
        l.boostPreset5,
        l.boostPreset10,
        l.boostPresetCustom,
        l.boostCustomAmountLabel,
        l.boostExplainer,
        l.boostTitle,
        l.boostAddAction,
        l.moneyBoostFee,
        l.moneyBoostBonus,
        l.moneyBaseReward,
      ]) {
        expect(
          find.text(gone),
          findsNothing,
          reason: 'Boost copy "$gone" is on the creation screen',
        );
      }
      // Not a chip that merely lost its label, either.
      expect(find.byType(ChoiceChip), findsNothing);
      expect(find.textContaining('Boost'), findsNothing);
      expect(
        (await _cardLines(tester)).map((line) => line.$1),
        isNot(contains(l.moneyBoostFee)),
      );
    });

    testWidgets('and the quote is never asked for one', (tester) async {
      final backend = _backend();
      await _pumpCreate(tester, backend);
      final calls = backend.to('POST', _quotePath);
      expect(calls, isNotEmpty);
      for (final call in calls) {
        expect(
          call.body.containsKey('boost_eur_cents'),
          isFalse,
          reason: 'the pricing quote carried a Boost: ${call.body}',
        );
      }
    });

    testWidgets('the totals card is three server lines', (tester) async {
      final l = await _pumpCreate(tester, _backend());
      expect(await _cardLines(tester), [
        (l.moneyTravelerReceives, '€30.00'),
        (l.moneyPlatformFee, '€7.50'),
        (l.moneyYouPay, '€37.50'),
      ]);
    });

    test('the draft omits boost_eur_cents rather than sending zero', () {
      final body = DeliveryRequestDraft(
        pickupPlaceId: 101,
        deliveryPlaceId: 202,
        readyWindowStart: DateTime.utc(2026, 10, 1, 9),
        readyWindowEnd: DateTime.utc(2026, 10, 1, 11),
        deadlineAt: DateTime.utc(2026, 10, 3, 9),
        actualWeightKg: 2.5,
        declaredValueEurCents: 6000,
        senderProposedRewardEurCents: 3000,
        title: 'Album',
        description: 'A thin album.',
        category: ItemCategory.documents,
        handlingNotes: '',
        fragile: false,
        itemPhotoMediaId: 9001,
        acknowledgements: const SafetyAcknowledgements(
          descriptionIsAccurate: true,
          itemIsLegal: true,
          noProhibitedGoods: true,
          declaredValueIsAccurate: true,
          customsResponsibilitiesUnderstood: true,
        ),
      ).toJson();
      expect(body.containsKey('boost_eur_cents'), isFalse);
      expect(body['sender_proposed_reward_eur_cents'], 3000);
    });

    testWidgets('posting the form sends no boost_eur_cents', (tester) async {
      final backend = _backend()
        ..handle(
          'POST',
          _createPath,
          (_) async => FakeResponse(201, _requestFixture()),
        );
      final l = await _pumpCreate(
        tester,
        backend,
        seed: _postableSeed(),
        routed: true,
      );

      for (final ack in [
        l.requestAckCustoms,
        l.requestAckValueAccurate,
        l.requestAckNoProhibited,
        l.requestAckItemLegal,
        l.requestAckDescriptionAccurate,
      ]) {
        await _scrollBackTo(tester, find.text(ack));
        await tester.tap(find.text(ack));
        await tester.pump();
      }
      await tester.tap(find.text(l.requestPostAction));
      await _tick(tester, 600);

      final created = backend.lastTo('POST', _createPath);
      expect(created, isNotNull, reason: 'the request was never posted');
      expect(created!.body.containsKey('boost_eur_cents'), isFalse);
      expect(created.body['sender_proposed_reward_eur_cents'], 3000);
    });
  });

  // -------------------------------------------------------------------------
  group('the offer section states the band and takes one number', () {
    testWidgets('minimum and recommended are both on screen, from the server', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());

      expect(find.text(l.pricingMinimumLabel), findsOneWidget);
      expect(find.text('€20.00'), findsOneWidget);
      expect(find.text(l.pricingRecommendedLabel), findsOneWidget);
      // The recommendation is preselected, so €30.00 is both the reference and
      // what the field holds.
      expect(find.text('€30.00'), findsWidgets);
      expect(_rewardText(tester), '30.00');
    });

    testWidgets('the offer is editable and the quote follows it', (
      tester,
    ) async {
      final backend = _backend();
      final l = await _pumpCreate(tester, backend);
      await _typeReward(tester, '40.00');
      await _tick(tester);

      expect(_rewardOf(backend.lastTo('POST', _quotePath)!), 4000);
      expect(await _cardLines(tester), [
        (l.moneyTravelerReceives, '€40.00'),
        (l.moneyPlatformFee, '€10.00'),
        (l.moneyYouPay, '€50.00'),
      ]);
    });

    testWidgets('above the recommendation is allowed and called competitive', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());
      await _typeReward(tester, '50.00');
      await _tick(tester);

      expect(find.text(l.pricingCompetitive), findsOneWidget);
      expect(find.text(l.pricingBelowMinimumError('€20.00')), findsNothing);
      expect((await _cardLines(tester)).last, (l.moneyYouPay, '€62.50'));
    });

    testWidgets('below the recommendation is allowed and only noted', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());
      await _typeReward(tester, '25.00');
      await _tick(tester);

      expect(find.text(l.pricingBelowRecommended), findsOneWidget);
      expect(find.text(l.pricingCompetitive), findsNothing);
      expect((await _cardLines(tester)).last, (l.moneyYouPay, '€31.25'));
    });

    testWidgets('below the minimum is refused and blocks Post', (tester) async {
      final backend = _backend()
        ..handle(
          'POST',
          _createPath,
          (_) async => FakeResponse(201, _requestFixture()),
        );
      final l = await _pumpCreate(tester, backend, seed: _postableSeed());
      await _typeReward(tester, '5.00');
      await _tick(tester);

      await tester.tap(find.text(l.requestPostAction));
      await _tick(tester, 600);

      expect(find.text(l.pricingBelowMinimumError('€20.00')), findsWidgets);
      expect(backend.to('POST', _createPath), isEmpty);
    });

    testWidgets('unusable text is refused and priced against nothing', (
      tester,
    ) async {
      final backend = _backend()
        ..handle(
          'POST',
          _createPath,
          (_) async => FakeResponse(201, _requestFixture()),
        );
      final l = await _pumpCreate(tester, backend, seed: _postableSeed());
      final before = backend.to('POST', _quotePath).length;
      await _typeReward(tester, '..,,');
      await _tick(tester);

      await tester.tap(find.text(l.requestPostAction));
      await _tick(tester, 600);

      expect(backend.to('POST', _createPath), isEmpty);
      // A reward that is not a number is not a reward, so nothing is priced
      // against it — and no fixture is missing.
      expect(
        backend.to('POST', _quotePath).skip(before).map(_rewardOf),
        everyElement(isNull),
      );
      expect(tester.takeException(), isNull);
    });
  });

  // -------------------------------------------------------------------------
  group('the stepper moves the offer by exactly fifty cents', () {
    testWidgets('+ adds €0.50 and the field says so at once', (tester) async {
      final backend = _backend();
      final l = await _pumpCreate(tester, backend);
      await _tapStep(tester, l.pricingIncrement50c);

      expect(_rewardText(tester), '30.50');
      await _tick(tester);
      expect(_rewardOf(backend.lastTo('POST', _quotePath)!), 3050);
    });

    testWidgets('− takes €0.50 off', (tester) async {
      final backend = _backend();
      final l = await _pumpCreate(tester, backend);
      await _tapStep(tester, l.pricingDecrement50c);

      expect(_rewardText(tester), '29.50');
      await _tick(tester);
      expect(_rewardOf(backend.lastTo('POST', _quotePath)!), 2950);
    });

    testWidgets('− stops at the server minimum rather than below it', (
      tester,
    ) async {
      final backend = _backend();
      final l = await _pumpCreate(tester, backend);
      await _typeReward(tester, '20.00');
      await _tick(tester);

      await _tapStep(tester, l.pricingDecrement50c);
      expect(_rewardText(tester), '20.00');
      await _tick(tester);
      expect(_rewardOf(backend.lastTo('POST', _quotePath)!), 2000);
    });

    testWidgets('typing then stepping continues from what was typed', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());
      await _typeReward(tester, '40.00');
      await _tapStep(tester, l.pricingIncrement50c);
      expect(_rewardText(tester), '40.50');
      await _tapStep(tester, l.pricingDecrement50c);
      expect(_rewardText(tester), '40.00');
      await _tick(tester);
    });

    testWidgets('five fast taps move five steps and cost one read', (
      tester,
    ) async {
      final backend = _backend();
      final l = await _pumpCreate(tester, backend);
      final before = backend.to('POST', _quotePath).length;

      for (var i = 0; i < 5; i++) {
        await _tapStep(tester, l.pricingIncrement50c);
        await tester.pump(const Duration(milliseconds: 60));
      }
      // The field moved on every press; the server was not asked five times.
      expect(_rewardText(tester), '32.50');
      expect(backend.to('POST', _quotePath).length, before);

      await _tick(tester);
      final reads = backend.to('POST', _quotePath).skip(before).toList();
      expect(reads, hasLength(1));
      expect(_rewardOf(reads.single), 3250);
    });
  });

  // -------------------------------------------------------------------------
  group('the quote refresh keeps its J6.3 guarantees', () {
    testWidgets('typing is debounced into one read at 350ms', (tester) async {
      final backend = _backend();
      await _pumpCreate(tester, backend);
      final before = backend.to('POST', _quotePath).length;

      for (final text in ['4', '40', '40.', '40.0', '40.00']) {
        await _typeReward(tester, text);
        await tester.pump(const Duration(milliseconds: 100));
      }
      expect(backend.to('POST', _quotePath).length, before);
      await _tick(tester);

      final reads = backend.to('POST', _quotePath).skip(before).toList();
      expect(reads, hasLength(1));
      expect(_rewardOf(reads.single), 4000);
    });

    testWidgets('a slow older answer never replaces a newer one', (
      tester,
    ) async {
      final hold = Completer<void>();
      final backend = _backend(hold: hold, holdReward: 5000);
      final l = await _pumpCreate(tester, backend);

      await _typeReward(tester, '50.00');
      await tester.pump(const Duration(milliseconds: 400));
      await tester.pump();

      // While €50.00 is in flight, the figures on screen are not its figures:
      // dimmed, hidden from screen readers, marked as updating.
      expect(_namedSemantics(l.pricingUpdating), findsOneWidget);

      // The sender changes their mind before the €50.00 answer arrives.
      await _typeReward(tester, '40.00');
      await tester.pump(const Duration(milliseconds: 400));
      hold.complete();
      await _tick(tester);
      await _tick(tester);

      expect((await _cardLines(tester)).last, (l.moneyYouPay, '€50.00'));
      expect(find.text('€62.50'), findsNothing);
      expect(_namedSemantics(l.pricingUpdating), findsNothing);
    });

    testWidgets('an empty offer is prefilled with the recommendation', (
      tester,
    ) async {
      final backend = _backend();
      await _pumpCreate(tester, backend);
      expect(backend.to('POST', _quotePath).map(_rewardOf).toList(), [
        null,
        3000,
      ]);
    });
  });

  // -------------------------------------------------------------------------
  group('the control is one component, not three', () {
    for (final device in [
      DeviceProfile.smallAndroid,
      DeviceProfile.iphone,
      DeviceProfile.android,
      DeviceProfile.landscape,
      _text13,
      DeviceProfile.largeText,
    ]) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        testWidgets('aligned on ${device.name} in ${locale.languageCode}', (
          tester,
        ) async {
          final l = await _pumpCreate(
            tester,
            _backend(),
            device: device,
            locale: locale,
          );
          final minus = tester.getRect(_stepControl(l.pricingDecrement50c));
          final input = tester.getRect(_rewardField);
          final plus = tester.getRect(_stepControl(l.pricingIncrement50c));

          // One vertical centre, to within a rounding error. This is the bug
          // the owner reported: the buttons used to sit a label's height above
          // the digits, and further above them the larger the text got.
          expect(
            minus.center.dy,
            closeTo(input.center.dy, 1),
            reason: 'the minus control is not centred on the input',
          );
          expect(
            plus.center.dy,
            closeTo(input.center.dy, 1),
            reason: 'the plus control is not centred on the input',
          );
          // Balanced heights: the buttons are the field's height, not a fixed
          // 40 points beside a field that grew with the text.
          expect(minus.height, closeTo(input.height, 1));
          expect(plus.height, closeTo(input.height, 1));
          // Symmetrical ends.
          expect(minus.width, closeTo(plus.width, 0.5));
          // Real tap targets at any text size.
          for (final end in [minus, plus]) {
            expect(end.width, greaterThanOrEqualTo(AppSpace.minTapTarget));
            expect(end.height, greaterThanOrEqualTo(AppSpace.minTapTarget));
          }
          // Nothing overflowed and nothing was clipped off the screen.
          expect(tester.takeException(), isNull);
          for (final rect in [minus, input, plus]) {
            expect(rect.left, greaterThanOrEqualTo(-0.5));
            expect(rect.right, lessThanOrEqualTo(device.size.width + 0.5));
          }
        });
      }
    }

    testWidgets('in Arabic the control mirrors but the arithmetic does not', (
      tester,
    ) async {
      final l = await _pumpCreate(
        tester,
        _backend(),
        locale: const Locale('ar'),
        device: DeviceProfile.iphone,
      );

      expect(
        Directionality.of(tester.element(_rewardField)),
        TextDirection.rtl,
      );
      // Mirrored: the decrement sits at the start edge, which in Arabic is the
      // right-hand side.
      expect(
        tester.getRect(_stepControl(l.pricingDecrement50c)).center.dx,
        greaterThan(
          tester.getRect(_stepControl(l.pricingIncrement50c)).center.dx,
        ),
      );

      // Not mirrored: minus still subtracts and plus still adds.
      await _tapStep(tester, l.pricingDecrement50c);
      expect(_rewardText(tester), '29.50');
      await _tapStep(tester, l.pricingIncrement50c);
      await _tapStep(tester, l.pricingIncrement50c);
      expect(_rewardText(tester), '30.50');
      await _tick(tester);
    });

    testWidgets('both ends and the input are named for a screen reader', (
      tester,
    ) async {
      final l = await _pumpCreate(tester, _backend());
      expect(_stepControl(l.pricingDecrement50c), findsOneWidget);
      expect(_stepControl(l.pricingIncrement50c), findsOneWidget);
      // The input keeps its name even though the heading above carries the
      // same words and the visible label is suppressed.
      expect(_namedSemantics(l.pricingYourOfferLabel), findsWidgets);
      expect(find.text(l.pricingYourOfferLabel), findsOneWidget);
    });

    for (final locale in const [Locale('fr'), Locale('ar')]) {
      testWidgets('the whole step reads in ${locale.languageCode}', (
        tester,
      ) async {
        final l = await _pumpCreate(
          tester,
          _backend(),
          locale: locale,
          device: DeviceProfile.smallAndroid,
        );
        // The band first: reading the totals card scrolls past it, and a
        // recycled child is not on screen to be found.
        expect(find.text(l.pricingMinimumLabel), findsOneWidget);
        expect(find.text(l.pricingRecommendedLabel), findsOneWidget);
        expect(await _cardLines(tester), [
          (l.moneyTravelerReceives, _eur(3000, locale)),
          (l.moneyPlatformFee, _eur(750, locale)),
          (l.moneyYouPay, _eur(3750, locale)),
        ]);
        expect(find.text(l.boostSectionTitle), findsNothing);
        expect(tester.takeException(), isNull);
      });
    }
  });

  // -------------------------------------------------------------------------
  group('a published request is where Boost is offered', () {
    Future<L> pumpDetail(WidgetTester tester, FakeBackend backend) async {
      final container = await _signedIn(tester, backend);
      await pumpApp(
        tester,
        const RequestDetailScreen(requestId: 42),
        container: container,
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(RequestDetailScreen)));
      // The Boost card sits below the route, parcel, timing and reward
      // sections; a `ListView` has not built it until it is reached.
      await _scrollTo(tester, find.text(l.boostExplainer));
      // Scrolling brings the matches section into being, which starts its own
      // read; leaving it in flight fails the test at teardown.
      await tester.pumpAndSettle();
      return l;
    }

    testWidgets('an open request with no Boost offers Add Boost', (
      tester,
    ) async {
      final l = await pumpDetail(tester, _publishedBackend());

      expect(find.text(l.boostAddAction), findsWidgets);
      expect(find.text(l.boostPostPublicationOnly), findsOneWidget);
      expect(find.text(l.boostEditAction), findsNothing);
    });

    testWidgets('a boosted request offers Change Boost and states it', (
      tester,
    ) async {
      final l = await pumpDetail(tester, _publishedBackend(boostCents: 500));

      expect(find.text(l.boostCurrentActive('€5.00')), findsOneWidget);
      expect(find.text(l.boostEditAction), findsWidgets);
      expect(find.text(l.boostAddAction), findsNothing);
    });

    testWidgets('the server can still refuse the edit, and the card says so', (
      tester,
    ) async {
      final l = await pumpDetail(
        tester,
        _publishedBackend(boostCents: 500, canEditBoost: false),
      );
      expect(find.text(l.boostNotEditable), findsOneWidget);
    });

    testWidgets('setting a Boost afterwards still works, at server prices', (
      tester,
    ) async {
      RecordedRequest? sent;
      final backend = _publishedBackend(onSetBoost: (r) => sent = r);
      final container = await _signedIn(tester, backend);
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: container,
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(BoostScreen)));

      await tester.tap(find.text(l.boostPreset5));
      await tester.pumpAndSettle();
      // The fee is the server's 15% Boost rate, not the 25% delivery rate a
      // client doing its own arithmetic would reach for.
      expect(find.text('€0.75'), findsOneWidget);
      expect(find.text('€5.75'), findsOneWidget);

      await tester.tap(find.text(l.actionSave));
      await tester.pumpAndSettle();

      expect(sent, isNotNull);
      expect(sent!.body['boost_eur_cents'], 500);
    });
  });
}
