/// Phase 8F-F3: offer and Deal money follows the authenticated party.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/money_perspective.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/features/common/delivery_card.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/payment_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _viewerId = 42;
const _otherPartyId = 99;

Map<String, dynamic> _offer({
  required int id,
  required String proposedBy,
  required int proposerId,
  required int reward,
  required int fee,
  required int senderTotal,
  required String awaitingParty,
  required int awaitingUserId,
  required List<String> allowedActions,
  String status = 'pending',
  int? parentOfferId,
}) => {
  'id': id,
  'match': 77,
  'parent_offer': parentOfferId,
  'proposed_by': proposedBy,
  'proposer_id': proposerId,
  'economics_version': 'v1_eur',
  'currency': 'EUR',
  'traveler_reward_minor': reward,
  'commission_rate_bps': 1000,
  'platform_fee_minor': fee,
  'sender_total_minor': senderTotal,
  // J6.1: a pending offer with no Boost, as the server now publishes it.
  'boost_terms_status': 'provisional',
  'boost_economics_version': 'additive_commission_v2',
  'boost_amount_minor': 0,
  'boost_traveler_bonus_minor': 0,
  'boost_platform_fee_minor': 0,
  'traveler_total_minor': reward,
  'sender_total_with_boost_minor': senderTotal,
  'status': status,
  'note': '',
  'awaiting_party': awaitingParty,
  'awaiting_user_id': awaitingUserId,
  'allowed_actions': allowedActions,
};

/// A countered offer as the server publishes it: closed, so no Boost-inclusive
/// totals, only the base economics frozen on the row.
Map<String, dynamic> _countered(Map<String, dynamic> offer) =>
    Map<String, dynamic>.from(offer)
      ..['status'] = 'countered'
      ..['allowed_actions'] = <String>[]
      ..['boost_terms_status'] = 'unavailable'
      ..['boost_economics_version'] = null
      ..['boost_amount_minor'] = null
      ..['boost_traveler_bonus_minor'] = null
      ..['boost_platform_fee_minor'] = null
      ..['traveler_total_minor'] = null
      ..['sender_total_with_boost_minor'] = null;

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

Map<String, dynamic> _terms() => {
  'currency': 'EUR',
  'traveler_reward_minor': 3000,
  'commission_rate_bps': 1667,
  'platform_fee_minor': 500,
  'sender_total_minor': 3500,
  'boost_amount_minor': 1000,
  'boost_traveler_bonus_minor': 750,
  'boost_platform_fee_minor': 250,
  'traveler_total_minor': 3750,
  'platform_total_minor': 750,
  'sender_total_with_boost_minor': 4500,
  'is_legacy': false,
};

Map<String, dynamic> _deal({
  required bool viewerIsSender,
  String status = 'payment_required',
}) => {
  'id': 7,
  'accepted_offer_id': 8,
  'delivery_request_id': 12,
  'journey_id': 21,
  'sender_id': viewerIsSender ? _viewerId : _otherPartyId,
  'traveler_id': viewerIsSender ? _otherPartyId : _viewerId,
  'status': status,
  'is_legacy': false,
  'terms': _terms(),
  'leg_allocations': <Object>[],
  'cancellation': {
    'allowed': false,
    'mode': '',
    'refusal_code': 'deal_not_cancellable',
  },
};

FakeBackend _negotiationBackend({
  required bool viewerIsSender,
  required Map<String, dynamic> initialOffer,
  bool counterChangesOffer = false,
  bool senderCounterChangesOffer = false,
}) {
  var current = initialOffer;
  var history = <Map<String, dynamic>>[initialOffer];
  final backend = FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..handle(
      'GET',
      '/api/matches/77',
      (_) => FakeResponse(
        200,
        _match(viewerIsSender: viewerIsSender, latestOffer: current),
      ),
    )
    ..handle(
      'GET',
      '/api/matches/77/offers',
      (_) => FakeResponse(200, history),
    );

  if (counterChangesOffer) {
    backend.handle('POST', '/api/offers/1/counter', (request) {
      expect(request.body, {'traveler_reward_eur_cents': 3000, 'note': ''});
      final previous = _countered(initialOffer);
      current = _offer(
        id: 2,
        parentOfferId: 1,
        proposedBy: 'traveler',
        proposerId: _viewerId,
        reward: 3000,
        fee: 300,
        senderTotal: 3300,
        awaitingParty: 'sender',
        awaitingUserId: _otherPartyId,
        allowedActions: const ['withdraw'],
      );
      history = [current, previous];
      return FakeResponse(201, current);
    });
  } else if (senderCounterChangesOffer) {
    backend.handle('POST', '/api/offers/4/counter', (request) {
      expect(request.body, {'traveler_reward_eur_cents': 3200, 'note': ''});
      final previous = _countered(initialOffer);
      current = _offer(
        id: 5,
        parentOfferId: 4,
        proposedBy: 'sender',
        proposerId: _viewerId,
        reward: 3200,
        fee: 320,
        senderTotal: 3520,
        awaitingParty: 'traveler',
        awaitingUserId: _otherPartyId,
        allowedActions: const ['withdraw'],
      );
      history = [current, previous];
      return FakeResponse(201, current);
    });
  }
  return backend;
}

Future<L> _pumpNegotiation(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
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
  test('party ids resolve perspective and select only server amounts', () {
    final offer = Offer.fromJson(
      _offer(
        id: 1,
        proposedBy: 'sender',
        proposerId: _viewerId,
        reward: 3000,
        fee: 500,
        senderTotal: 3500,
        awaitingParty: 'traveler',
        awaitingUserId: _otherPartyId,
        allowedActions: const ['withdraw'],
      ),
    );
    final match = Match.fromJson(
      _match(
        viewerIsSender: true,
        latestOffer: _offer(
          id: 1,
          proposedBy: 'sender',
          proposerId: _viewerId,
          reward: 3000,
          fee: 500,
          senderTotal: 3500,
          awaitingParty: 'traveler',
          awaitingUserId: _otherPartyId,
          allowedActions: const ['withdraw'],
        ),
      ),
    );
    final terms = DealTerms.maybe(_terms())!;

    expect(match.moneyPerspectiveFor(_viewerId), MoneyPerspective.sender);
    expect(match.moneyPerspectiveFor(_otherPartyId), MoneyPerspective.traveler);
    expect(match.moneyPerspectiveFor(777), isNull);
    expect(offer.amountFor(MoneyPerspective.sender), Money.eurCents(3500));
    expect(offer.amountFor(MoneyPerspective.traveler), Money.eurCents(3000));
    expect(terms.totalFor(MoneyPerspective.sender), Money.eurCents(4500));
    expect(terms.totalFor(MoneyPerspective.traveler), Money.eurCents(3750));
  });

  testWidgets(
    'traveler counter stays earnings-oriented despite sender dashboard context',
    (tester) async {
      final initial = _offer(
        id: 1,
        proposedBy: 'sender',
        proposerId: _otherPartyId,
        reward: 2800,
        fee: 280,
        senderTotal: 3080,
        awaitingParty: 'traveler',
        awaitingUserId: _viewerId,
        allowedActions: const ['accept', 'counter', 'decline'],
      );
      final backend = _negotiationBackend(
        viewerIsSender: false,
        initialOffer: initial,
        counterChangesOffer: true,
      );
      final l = await _pumpNegotiation(tester, backend);

      expect(find.text(l.offerSenderOfferTitle), findsOneWidget);
      expect(find.text(l.moneyYouReceive), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsNothing);
      expect(find.text(l.moneyPlatformFee), findsNothing);

      await tester.tap(find.widgetWithText(AppButton, l.offerCounter));
      await tester.pumpAndSettle();
      expect(find.text(l.moneyYouReceive), findsWidgets);
      expect(find.text(l.offerCounterTravelerExplainer), findsOneWidget);
      expect(find.text(l.offerSendCounter), findsOneWidget);
      expect(find.text(l.moneyYouPay), findsNothing);

      await tester.enterText(find.byType(TextFormField), '30.00');
      await tester.tap(find.widgetWithText(AppButton, l.offerSendCounter));
      await tester.pumpAndSettle();

      final locale = Localizations.localeOf(
        tester.element(find.byType(NegotiationScreen)),
      );
      expect(find.text(l.offerYourCounterTitle), findsOneWidget);
      expect(find.text(l.moneyYouReceive), findsOneWidget);
      expect(
        find.textContaining(Money.eurCents(3000).format(locale)),
        findsOneWidget,
      );
      // The countered offer is closed, so its reward is named as the base.
      expect(
        find.text(
          l.offerHistoryBaseReward(
            l.offerSenderOfferTitle,
            Money.eurCents(2800).format(locale),
          ),
        ),
        findsOneWidget,
      );
      expect(find.text(l.moneyYouPay), findsNothing);
    },
  );

  testWidgets('traveler acceptance confirms the reward they receive', (
    tester,
  ) async {
    final initial = _offer(
      id: 1,
      proposedBy: 'sender',
      proposerId: _otherPartyId,
      reward: 2800,
      fee: 280,
      senderTotal: 3080,
      awaitingParty: 'traveler',
      awaitingUserId: _viewerId,
      allowedActions: const ['accept'],
    );
    final l = await _pumpNegotiation(
      tester,
      _negotiationBackend(viewerIsSender: false, initialOffer: initial),
    );
    final amount = Money.eurCents(2800).format(const Locale('en'));

    await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
    await tester.pumpAndSettle();
    expect(
      find.text(l.offerAcceptTravelerConfirmTitle(amount)),
      findsOneWidget,
    );
    expect(find.text(l.offerAcceptTravelerBody), findsOneWidget);
    expect(find.text(l.offerAcceptSenderConfirmTitle(amount)), findsNothing);
  });

  testWidgets('sender offer and acceptance use the server sender total', (
    tester,
  ) async {
    final counter = _offer(
      id: 4,
      proposedBy: 'traveler',
      proposerId: _otherPartyId,
      reward: 3000,
      fee: 300,
      senderTotal: 3300,
      awaitingParty: 'sender',
      awaitingUserId: _viewerId,
      allowedActions: const ['accept', 'counter', 'decline'],
    );
    final l = await _pumpNegotiation(
      tester,
      _negotiationBackend(viewerIsSender: true, initialOffer: counter),
    );
    final amount = Money.eurCents(3300).format(const Locale('en'));

    expect(find.text(l.offerTravelerCounterTitle), findsOneWidget);
    expect(find.text(l.moneyTravelerReceives), findsOneWidget);
    expect(find.text(l.moneyPlatformFee), findsOneWidget);
    expect(find.text(l.moneyYouPay), findsOneWidget);
    expect(find.textContaining(amount), findsOneWidget);
    expect(find.text(l.moneyYouReceive), findsNothing);

    await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
    await tester.pumpAndSettle();
    expect(find.text(l.offerAcceptSenderConfirmTitle(amount)), findsOneWidget);
    expect(find.text(l.offerAcceptSenderBody), findsOneWidget);
  });

  testWidgets('sender counter keeps payer wording and server total', (
    tester,
  ) async {
    final counter = _offer(
      id: 4,
      proposedBy: 'traveler',
      proposerId: _otherPartyId,
      reward: 3000,
      fee: 300,
      senderTotal: 3300,
      awaitingParty: 'sender',
      awaitingUserId: _viewerId,
      allowedActions: const ['accept', 'counter', 'decline'],
    );
    final backend = _negotiationBackend(
      viewerIsSender: true,
      initialOffer: counter,
      senderCounterChangesOffer: true,
    );
    final l = await _pumpNegotiation(tester, backend);

    await tester.tap(find.widgetWithText(AppButton, l.offerCounter));
    await tester.pumpAndSettle();
    expect(find.text(l.moneyTravelerReceives), findsWidgets);
    expect(find.text(l.offerSendCounter), findsOneWidget);
    expect(find.text(l.moneyYouReceive), findsNothing);

    await tester.enterText(find.byType(TextFormField), '32.00');
    await tester.tap(find.widgetWithText(AppButton, l.offerSendCounter));
    await tester.pumpAndSettle();

    final locale = Localizations.localeOf(
      tester.element(find.byType(NegotiationScreen)),
    );
    expect(find.text(l.offerYourCounterTitle), findsOneWidget);
    expect(find.text(l.moneyYouPay), findsOneWidget);
    expect(
      find.textContaining(Money.eurCents(3520).format(locale)),
      findsOneWidget,
    );
    expect(find.text(l.moneyYouReceive), findsNothing);
    expect(find.widgetWithText(AppButton, l.offerAccept), findsNothing);
    expect(find.widgetWithText(AppButton, l.offerCounter), findsNothing);
  });

  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets(
      'traveler money semantics are localized in ${locale.languageCode}',
      (tester) async {
        final initial = _offer(
          id: 1,
          proposedBy: 'sender',
          proposerId: _otherPartyId,
          reward: 2800,
          fee: 280,
          senderTotal: 3080,
          awaitingParty: 'traveler',
          awaitingUserId: _viewerId,
          allowedActions: const ['counter'],
        );
        final l = await _pumpNegotiation(
          tester,
          _negotiationBackend(viewerIsSender: false, initialOffer: initial),
          locale: locale,
          device: locale.languageCode == 'ar'
              ? DeviceProfile.largeText
              : DeviceProfile.smallAndroid,
        );

        expect(find.text(l.moneyYouReceive), findsOneWidget);
        expect(find.text(l.moneyYouPay), findsNothing);
        expect(tester.takeException(), isNull);
        if (locale.languageCode == 'ar') {
          expect(
            Directionality.of(tester.element(find.byType(NegotiationScreen))),
            TextDirection.rtl,
          );
        }
      },
    );
  }

  testWidgets('Deal cards use Boost-inclusive totals for each party', (
    tester,
  ) async {
    final senderDeal = Deal.fromJson(_deal(viewerIsSender: true));
    final travelerDeal = Deal.fromJson(_deal(viewerIsSender: false));
    await pumpApp(
      tester,
      Column(
        children: [
          DeliveryCard(deal: senderDeal, viewerId: _viewerId, onTap: () {}),
          DeliveryCard(deal: travelerDeal, viewerId: _viewerId, onTap: () {}),
        ],
      ),
    );
    final l = L.of(tester.element(find.byType(DeliveryCard).first));

    expect(find.text(l.moneyYouPay), findsOneWidget);
    expect(find.text(l.moneyYouReceive), findsOneWidget);
    expect(find.textContaining('€45.00'), findsOneWidget);
    expect(find.textContaining('€37.50'), findsOneWidget);
  });

  testWidgets('traveler Deal shows base, Boost bonus, and total received', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(200, _deal(viewerIsSender: false)),
      );
    await pumpApp(
      tester,
      const DealScreen(dealId: 7),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DealScreen)));

    expect(find.text(l.moneyYouReceive), findsOneWidget);
    expect(find.text(l.moneyBaseReward), findsOneWidget);
    expect(find.text(l.moneyBoostBonus), findsOneWidget);
    expect(find.text(l.moneyTotalYouReceive), findsOneWidget);
    expect(find.text(l.moneyYouPay), findsNothing);
    expect(find.text(l.moneyPlatformFee), findsNothing);
    expect(find.text(l.moneyPlatformBoostRevenue), findsNothing);
    expect(find.textContaining('€37.50'), findsWidgets);
  });

  testWidgets('traveler payment route remains earnings-only without checkout', (
    tester,
  ) async {
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/deals/7',
        FakeResponse(200, _deal(viewerIsSender: false)),
      )
      ..on(
        'GET',
        '/api/deals/7/payment',
        const FakeResponse(200, {
          'deal_id': 7,
          'deal_status': 'payment_required',
          'currency': 'EUR',
          'traveler_reward_eur_cents': 3000,
          'traveler_boost_bonus_eur_cents': 750,
          'traveler_total_eur_cents': 3750,
          'order': {'status': 'required', 'outstanding_eur_cents': 4500},
        }),
      );
    await pumpApp(
      tester,
      const DealPaymentScreen(dealId: 7),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(DealPaymentScreen)));

    expect(find.text(l.moneyYourEarnings), findsOneWidget);
    expect(find.text(l.moneyTotalYouReceive), findsOneWidget);
    expect(find.text(l.dealTravelerAwaitingPayment), findsOneWidget);
    expect(find.text(l.moneyYouPay), findsNothing);
    expect(find.text(l.paymentChooseProvider), findsNothing);
    expect(find.textContaining('€37.50'), findsOneWidget);
  });
}
