/// Phase J6.2: one name for the Boost fee, and an open offer that keeps up.
///
/// **Terminology.** Under J2 the Traveler receives the whole Boost and ShipTrip
/// charges the sender a separate fee on it. "ShipTrip boost share" described the
/// retired split model, where ShipTrip kept part of the Boost. Every screen that
/// names that fee now calls it the Boost fee, in all three languages.
///
/// **Live refresh.** The sender can change their Boost while an offer is
/// pending, which moves the offer's provisional totals. The server now sends
/// `offer.economics_changed` — identifiers only — and the open offer re-reads
/// itself over HTTP. It never adjusts a figure locally, only a pending offer
/// listens, one signal costs one read, and the acceptance refusal from J6.1 is
/// still what makes a stale figure harmless.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/design/components/money.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/payment_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/features/requests/boost_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'phase_j6_ux_acceptance_test.dart' show j6BoostBackend;
import 'support/fake_api.dart';
import 'support/harness.dart';

const _viewerId = 42;
const _otherPartyId = 99;
const _matchId = 77;
const _en = Locale('en');

String _eur(int cents) => Money.eurCents(cents).format(_en);

/// A pending V1 offer as the J6.1 server publishes it: base €30.00 with a 25%
/// commission, and [boost] on top with its own 25% fee. Fixture data standing
/// in for the server; the app under test never computes these totals.
Map<String, dynamic> _offer({
  int boost = 500,
  String status = 'pending',
  String boostTermsStatus = 'provisional',
  bool viewerIsSender = false,
  List<String> allowedActions = const ['accept', 'counter', 'decline'],
}) {
  final fee = (boost * 2500 + 9999) ~/ 10000;
  final available = boostTermsStatus != 'unavailable';
  return {
    'id': 1,
    'match': _matchId,
    'parent_offer': null,
    'proposed_by': 'sender',
    'proposer_id': viewerIsSender ? _viewerId : _otherPartyId,
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
    'boost_platform_fee_minor': available ? fee : null,
    'traveler_total_minor': available ? 3000 + boost : null,
    'sender_total_with_boost_minor': available ? 3750 + boost + fee : null,
    'status': status,
    'note': '',
    'awaiting_party': status == 'pending' ? 'traveler' : null,
    'awaiting_user_id': status == 'pending'
        ? (viewerIsSender ? _otherPartyId : _viewerId)
        : null,
    'allowed_actions': allowedActions,
  };
}

Map<String, dynamic> _match(
  Map<String, dynamic> latestOffer, {
  bool viewerIsSender = false,
  String status = 'pending',
}) => {
  'id': _matchId,
  'parcel_id': 12,
  'journey_id': 21,
  'start_leg_id': 31,
  'end_leg_id': 32,
  'sender_id': viewerIsSender ? _viewerId : _otherPartyId,
  'traveler_id': viewerIsSender ? _otherPartyId : _viewerId,
  'sender_name': viewerIsSender ? 'Amina' : 'Karim',
  'traveler_name': viewerIsSender ? 'Karim' : 'Amina',
  'status': status,
  'latest_offer': latestOffer,
  'parcel': {
    'id': 12,
    'kind': 'delivery',
    'actual_weight_kg': '2.50',
    'origin': {'id': 1, 'name': 'Paris', 'country_code': 'FR'},
    'destination': {'id': 2, 'name': 'Alger', 'country_code': 'DZ'},
  },
};

/// The server's current negotiation, mutable so a test can play the sender.
class _Negotiation {
  _Negotiation({this.viewerIsSender = false});

  final bool viewerIsSender;
  int boost = 500;
  String status = 'pending';
  String boostTermsStatus = 'provisional';
  String matchStatus = 'pending';

  Map<String, dynamic> offer() => _offer(
    boost: boost,
    status: status,
    boostTermsStatus: boostTermsStatus,
    viewerIsSender: viewerIsSender,
    allowedActions: status == 'pending'
        ? const ['accept', 'counter', 'decline']
        : const [],
  );

  FakeBackend backend() => FakeBackend()
    ..on('GET', '/api/me', FakeResponse(200, meFixture()))
    ..handle(
      'GET',
      '/api/matches/$_matchId',
      (_) => FakeResponse(
        200,
        _match(offer(), viewerIsSender: viewerIsSender, status: matchStatus),
      ),
    )
    ..handle(
      'GET',
      '/api/matches/$_matchId/offers',
      (_) => FakeResponse(200, [offer()]),
    );
}

typedef _Screen = ({FakeBackend backend, ProviderContainer container, L l});

Future<_Screen> _open(
  WidgetTester tester,
  _Negotiation negotiation, {
  Locale locale = _en,
  DeviceProfile device = DeviceProfile.android,
  bool routed = false,
  List<RouteBase> extraRoutes = const [],
}) async {
  final backend = negotiation.backend();
  final container = containerFor(backend);
  await pumpApp(
    tester,
    const NegotiationScreen(matchId: _matchId),
    container: container,
    locale: locale,
    device: device,
    routed: routed,
    extraRoutes: extraRoutes,
  );
  await tester.pumpAndSettle();
  container.read(liveUpdatesProvider).bindAccount(_viewerId);
  return (
    backend: backend,
    container: container,
    l: L.of(tester.element(find.byType(NegotiationScreen))),
  );
}

Map<String, dynamic> _signal(String eventId, {int matchId = _matchId}) => {
  'type': 'offer.economics_changed',
  'event_id': eventId,
  'payload': {'match_id': matchId, 'offer_id': 1},
};

Future<void> _deliver(
  WidgetTester tester,
  ProviderContainer container,
  Iterable<Map<String, dynamic>> events, {
  LiveEventSource source = LiveEventSource.websocket,
}) async {
  final live = container.read(liveUpdatesProvider);
  for (final event in events) {
    live.ingest(event, source: source);
  }
  // Past the coalescing window, then let the re-read land.
  await tester.pump(const Duration(milliseconds: 100));
  await tester.pumpAndSettle();
}

int _detailReads(FakeBackend backend) =>
    backend.to('GET', '/api/matches/$_matchId').length;

Money _hero(WidgetTester tester) =>
    tester.widget<MoneyHero>(find.byType(MoneyHero)).amount;

Map<String, dynamic> _senderDeal() => {
  'id': 7,
  'accepted_offer_id': 8,
  'delivery_request_id': 12,
  'journey_id': 21,
  'sender_id': _viewerId,
  'traveler_id': _otherPartyId,
  'status': 'payment_required',
  'is_legacy': false,
  'terms': {
    'currency': 'EUR',
    'traveler_reward_minor': 3000,
    'commission_rate_bps': 2500,
    'platform_fee_minor': 750,
    'sender_total_minor': 3750,
    'boost_amount_minor': 800,
    'boost_traveler_bonus_minor': 800,
    'boost_platform_fee_minor': 200,
    'traveler_total_minor': 3800,
    'platform_total_minor': 950,
    'sender_total_with_boost_minor': 4750,
    'is_legacy': false,
  },
  'leg_allocations': <Object>[],
  'cancellation': {
    'allowed': false,
    'mode': '',
    'refusal_code': 'deal_not_cancellable',
  },
};

void main() {
  // -------------------------------------------------------------------------
  // Terminology
  // -------------------------------------------------------------------------

  group('the Boost fee has one name', () {
    test('in every language, and the retired phrase is gone', () {
      final expected = {
        'en': ('Boost fee', 'Boost bonus'),
        'fr': ('Frais Boost', 'Bonus Boost'),
        'ar': ('رسوم التعزيز', 'مكافأة التعزيز'),
      };
      for (final MapEntry(key: code, value: (fee, bonus)) in expected.entries) {
        final l = lookupL(Locale(code));
        expect(l.moneyBoostFee, fee, reason: code);
        expect(l.moneyBoostBonus, bonus, reason: code);
      }

      // French had two names for one product on the same flow: the request's
      // button said "Mettre en avant" and the screen it opens said "Booster".
      final fr = lookupL(const Locale('fr'));
      expect(fr.boostTitle, fr.boostSectionTitle);
      expect(fr.boostCompatibilityNote, isNot(contains('mise en avant')));

      // Nothing the app can render still says "share" about Boost money —
      // not in a translation, and not as a literal in a screen.
      final retired = RegExp(
        r'boost share|Part de ShipTrip sur la mise en avant|حصة ShipTrip من التعزيز',
        caseSensitive: false,
      );
      final offenders = <String>[
        for (final entity in Directory('lib').listSync(recursive: true))
          if (entity is File &&
              (entity.path.endsWith('.arb') || entity.path.endsWith('.dart')) &&
              retired.hasMatch(entity.readAsStringSync()))
            entity.path,
      ];
      expect(offenders, isEmpty);
    });

    testWidgets('the Sender offer breakdown names it', (tester) async {
      final screen = await _open(tester, _Negotiation(viewerIsSender: true));
      final l = screen.l;

      expect(find.text('ShipTrip boost share'), findsNothing);
      expect(find.text('Boost fee'), findsOneWidget);
      // Base reward, Boost, Traveler receives, ShipTrip fee, Boost fee, total.
      final labels = tester
          .widget<MoneyBreakdown>(find.byType(MoneyBreakdown))
          .lines
          .map((line) => line.label)
          .toList();
      expect(labels, [
        l.moneyBaseReward,
        l.moneyBoostBonus,
        l.moneyTravelerReceives,
        l.moneyPlatformFee,
        l.moneyBoostFee,
        l.moneyYouPay,
      ]);
      expect(find.textContaining(_eur(125)), findsOneWidget);
    });

    testWidgets('the Sender Deal breakdown names it', (tester) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('GET', '/api/deals/7', FakeResponse(200, _senderDeal()));
      await pumpApp(
        tester,
        const DealScreen(dealId: 7),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DealScreen)));

      expect(find.text('ShipTrip boost share'), findsNothing);
      expect(find.text(l.moneyBoostFee), findsOneWidget);
      expect(find.textContaining(_eur(200)), findsWidgets);
      expect(find.textContaining(_eur(4750)), findsWidgets);
    });

    testWidgets('the Sender payment breakdown names it', (tester) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on('GET', '/api/deals/7', FakeResponse(200, _senderDeal()))
        ..on(
          'GET',
          '/api/payments/providers',
          const FakeResponse(200, {
            'timing_mode': 'after_acceptance',
            'canonical_currency': 'EUR',
            'providers': <Object>[],
          }),
        )
        ..on(
          'GET',
          '/api/deals/7/payment',
          const FakeResponse(200, {
            'deal_id': 7,
            'deal_status': 'payment_required',
            'currency': 'EUR',
            'sender_total_eur_cents': 3750,
            'traveler_reward_eur_cents': 3000,
            'platform_fee_eur_cents': 750,
            'boost_amount_eur_cents': 800,
            'traveler_boost_bonus_eur_cents': 800,
            'platform_boost_revenue_eur_cents': 200,
            'traveler_total_eur_cents': 3800,
            'sender_total_with_boost_eur_cents': 4750,
            'order': {
              'public_reference': 'ord_7',
              'purpose': 'deal_balance',
              'status': 'required',
              'currency': 'EUR',
              'amount_eur_cents': 4750,
              'outstanding_eur_cents': 4750,
              'paid_eur_cents': 0,
              'attempts': <Object>[],
              'refunds': <Object>[],
              'providers': <Object>[],
            },
          }),
        );
      await pumpApp(
        tester,
        const DealPaymentScreen(dealId: 7),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DealPaymentScreen)));

      expect(find.text('ShipTrip boost share'), findsNothing);
      expect(find.text(l.moneyBoostFee), findsOneWidget);
      expect(find.text(l.moneyBoostBonus), findsOneWidget);
    });

    testWidgets('the Boost screen calls its fee the Boost fee', (tester) async {
      await pumpApp(
        tester,
        const BoostScreen(requestId: 42),
        container: containerFor(j6BoostBackend()),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(BoostScreen)));

      // A card titled "What the Boost costs" used to list "ShipTrip fee", the
      // same words the delivery's own commission goes by everywhere else.
      expect(find.text(l.moneyBoostFee), findsOneWidget);
      expect(find.text(l.pricingPlatformFee), findsNothing);
      expect(find.text('€1.25'), findsOneWidget);
    });

    for (final (locale, fee) in [
      (const Locale('fr'), 'Frais Boost'),
      (const Locale('ar'), 'رسوم التعزيز'),
    ]) {
      testWidgets(
        'the Sender breakdown fits a small phone in ${locale.languageCode}',
        (tester) async {
          await _open(
            tester,
            _Negotiation(viewerIsSender: true),
            locale: locale,
            device: DeviceProfile.smallAndroid,
          );
          expect(find.text(fee), findsOneWidget);
          expect(tester.takeException(), isNull);
          expect(
            Directionality.of(tester.element(find.byType(NegotiationScreen))),
            locale.languageCode == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          );
        },
      );
    }
  });

  // -------------------------------------------------------------------------
  // The signal's reach
  // -------------------------------------------------------------------------

  group('the signal reaches only what shows offer money', () {
    test('an open offer and the Open offers list; not the bell', () {
      expect(
        resourcesForLiveEvent('offer.economics_changed', {
          'match_id': _matchId,
          'offer_id': 1,
        }),
        {
          const LiveResource.matches(),
          const LiveResource.offerEconomics(_matchId),
        },
      );
      // Malformed identity: still no detail read, still nothing else.
      expect(
        resourcesForLiveEvent('offer.economics_changed', {'match_id': 'x'}),
        {const LiveResource.matches()},
      );
      // A lifecycle event never pokes the Boost-only subscription.
      expect(
        resourcesForLiveEvent('offer.updated', {'match_id': _matchId}),
        isNot(contains(const LiveResource.offerEconomics(_matchId))),
      );
    });

    test('its inbox row opens the negotiation', () {
      final row = AppNotification.fromJson({
        'id': 5,
        'channel': 'offer.economics_changed',
        'event_id': 'e1',
        'payload': {'match_id': _matchId, 'offer_id': 1},
        'read_at': null,
        'created_at': '2026-09-16T10:00:00Z',
      });
      expect(row.channel, NotificationChannel.offerEconomicsChanged);
      expect(row.destination, isA<OpenMatch>());
      expect((row.destination! as OpenMatch).matchId, _matchId);
    });

    test('the Open offers list re-reads once; the badge does not', () async {
      var matchesReads = 0;
      var unreadReads = 0;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle('GET', '/api/matches', (_) {
          matchesReads++;
          return FakeResponse(200, [_match(_offer())]);
        })
        ..handle('GET', '/api/notifications/unread-count', (_) {
          unreadReads++;
          return const FakeResponse(200, {
            'unread': 0,
            'active': 0,
            'unread_active': 0,
          });
        });
      final container = containerFor(backend);
      addTearDown(container.dispose);
      final lists = container.listen(matchesProvider, (_, _) {});
      final badge = container.listen(unreadNotificationsProvider, (_, _) {});
      addTearDown(lists.close);
      addTearDown(badge.close);
      for (var i = 0; i < 50 && matchesReads + unreadReads < 2; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      await Future<void>.delayed(const Duration(milliseconds: 20));
      final (listBefore, badgeBefore) = (matchesReads, unreadReads);

      container.read(liveUpdatesProvider)
        ..bindAccount(_viewerId)
        ..ingest(_signal('list-1'), source: LiveEventSource.websocket);
      for (var i = 0; i < 50 && matchesReads == listBefore; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
      await Future<void>.delayed(const Duration(milliseconds: 150));

      expect(matchesReads, listBefore + 1);
      expect(unreadReads, badgeBefore);
    });
  });

  // -------------------------------------------------------------------------
  // The Traveler's open offer
  // -------------------------------------------------------------------------

  group('an open pending offer follows the sender\'s Boost', () {
    testWidgets('a raised Boost re-reads the offer and says so, once', (
      tester,
    ) async {
      final negotiation = _Negotiation();
      final screen = await _open(tester, negotiation);
      final l = screen.l;
      expect(_hero(tester), Money.eurCents(3500));
      // Nothing changed yet, so nothing says it did.
      expect(find.text(l.offerEconomicsUpdated), findsNothing);
      final detailBefore = _detailReads(screen.backend);
      final historyBefore = screen.backend
          .to('GET', '/api/matches/$_matchId/offers')
          .length;

      negotiation.boost = 800;
      await _deliver(tester, screen.container, [_signal('raise')]);

      expect(_hero(tester), Money.eurCents(3800));
      expect(find.textContaining(_eur(800)), findsWidgets);
      expect(
        find.text(l.offerBoostIncludedTraveler(_eur(800))),
        findsOneWidget,
      );
      expect(find.text(l.offerEconomicsUpdated), findsOneWidget);
      // One signal, one read of the offer. The history list is not re-read:
      // past offers publish no total, so a Boost cannot change them.
      expect(_detailReads(screen.backend), detailBefore + 1);
      expect(
        screen.backend.to('GET', '/api/matches/$_matchId/offers').length,
        historyBefore,
      );
    });

    testWidgets('a lowered Boost re-reads the offer too', (tester) async {
      final negotiation = _Negotiation()..boost = 800;
      final screen = await _open(tester, negotiation);
      expect(_hero(tester), Money.eurCents(3800));

      negotiation.boost = 300;
      await _deliver(tester, screen.container, [_signal('lower')]);

      expect(_hero(tester), Money.eurCents(3300));
      expect(find.text(screen.l.offerEconomicsUpdated), findsOneWidget);
    });

    testWidgets('a removed Boost takes its row and note with it', (
      tester,
    ) async {
      final negotiation = _Negotiation();
      final screen = await _open(tester, negotiation);
      final l = screen.l;
      expect(find.text(l.moneyBoostBonus), findsOneWidget);

      negotiation.boost = 0;
      await _deliver(tester, screen.container, [_signal('remove')]);

      expect(_hero(tester), Money.eurCents(3000));
      expect(find.text(l.moneyBoostBonus), findsNothing);
      expect(find.text(l.moneyBaseReward), findsNothing);
      expect(find.text(l.offerBoostIncludedTraveler(_eur(500))), findsNothing);
      expect(find.text(l.offerEconomicsUpdated), findsOneWidget);
    });

    testWidgets('the Sender sees the same re-read with their own totals', (
      tester,
    ) async {
      final negotiation = _Negotiation(viewerIsSender: true);
      final screen = await _open(tester, negotiation);
      expect(find.textContaining(_eur(4375)), findsOneWidget);

      negotiation.boost = 800;
      await _deliver(tester, screen.container, [_signal('sender')]);

      // €30.00 + €7.50 + €8.00 + €2.00, as the server published it.
      expect(find.textContaining(_eur(4750)), findsOneWidget);
      expect(find.textContaining(_eur(200)), findsOneWidget);
      expect(find.text(screen.l.moneyBoostFee), findsOneWidget);
      expect(find.text(screen.l.offerEconomicsUpdated), findsOneWidget);
    });

    testWidgets('a re-read that changes nothing says nothing', (tester) async {
      final screen = await _open(tester, _Negotiation());
      await _deliver(tester, screen.container, [_signal('same')]);
      expect(_hero(tester), Money.eurCents(3500));
      expect(find.text(screen.l.offerEconomicsUpdated), findsNothing);
    });

    testWidgets('a burst and its duplicates cost one read', (tester) async {
      final negotiation = _Negotiation();
      final screen = await _open(tester, negotiation);
      final before = _detailReads(screen.backend);

      negotiation.boost = 900;
      final live = screen.container.read(liveUpdatesProvider);
      // The same event over the socket and a push copy, plus quick edits.
      live.ingest(_signal('burst-1'), source: LiveEventSource.firebase);
      await _deliver(tester, screen.container, [
        _signal('burst-1'),
        _signal('burst-2'),
        _signal('burst-3'),
      ]);

      expect(_detailReads(screen.backend), before + 1);
      expect(_hero(tester), Money.eurCents(3900));

      // A replay of an event already handled is not a second read.
      await _deliver(tester, screen.container, [_signal('burst-2')]);
      expect(_detailReads(screen.backend), before + 1);
    });

    testWidgets('someone else\'s signal and other events leave it alone', (
      tester,
    ) async {
      final negotiation = _Negotiation();
      final screen = await _open(tester, negotiation);
      final before = _detailReads(screen.backend);
      final historyBefore = screen.backend
          .to('GET', '/api/matches/$_matchId/offers')
          .length;

      negotiation.boost = 800;
      await _deliver(tester, screen.container, [
        _signal('other-match', matchId: 78),
        {
          'type': 'chat.message.new',
          'event_id': 'chat-1',
          'payload': {'match_id': _matchId},
        },
        {
          'type': 'deal.updated',
          'event_id': 'deal-1',
          'payload': {'deal_id': 5},
        },
        {
          'type': 'ping',
          'payload': {'match_id': _matchId},
        },
      ]);

      expect(_detailReads(screen.backend), before);
      expect(
        screen.backend.to('GET', '/api/matches/$_matchId/offers').length,
        historyBefore,
      );
      expect(_hero(tester), Money.eurCents(3500));
    });
  });

  // -------------------------------------------------------------------------
  // Closed offers
  // -------------------------------------------------------------------------

  group('a closed offer does not listen', () {
    testWidgets('an accepted offer ignores the signal entirely', (
      tester,
    ) async {
      final negotiation = _Negotiation()
        ..status = 'accepted'
        ..boostTermsStatus = 'frozen'
        ..matchStatus = 'accepted';
      final screen = await _open(tester, negotiation);
      final before = _detailReads(screen.backend);

      negotiation.boost = 800;
      await _deliver(tester, screen.container, [_signal('frozen')]);

      expect(_detailReads(screen.backend), before);
      expect(_hero(tester), Money.eurCents(3500));
    });

    testWidgets('an offer that closes while open stops listening', (
      tester,
    ) async {
      final negotiation = _Negotiation();
      final screen = await _open(tester, negotiation);

      // The sender declined: the lifecycle event re-reads the match as usual.
      negotiation
        ..status = 'declined'
        ..boostTermsStatus = 'unavailable';
      await _deliver(tester, screen.container, [
        {
          'type': 'offer.updated',
          'event_id': 'declined',
          'payload': {'match_id': _matchId},
        },
      ]);
      final before = _detailReads(screen.backend);

      await _deliver(tester, screen.container, [_signal('after-close')]);
      expect(_detailReads(screen.backend), before);
    });
  });

  // -------------------------------------------------------------------------
  // The acceptance guard is still the guarantee
  // -------------------------------------------------------------------------

  group('accepting across a Boost change', () {
    testWidgets(
      'a stale confirm is refused, and the new figures are what gets accepted',
      (tester) async {
        final negotiation = _Negotiation();
        final screen = await _open(
          tester,
          negotiation,
          routed: true,
          extraRoutes: [
            GoRoute(
              path: '/deals/:id',
              name: Routes.deal,
              builder: (_, state) => Text('deal ${state.pathParameters['id']}'),
            ),
          ],
        );
        final l = screen.l;
        final bodies = <Object?>[];
        screen.backend.handle('POST', '/api/offers/1/accept', (request) {
          bodies.add(request.body);
          final body = request.body as Map;
          final current = negotiation.offer();
          if (body['traveler_total_minor'] != current['traveler_total_minor']) {
            return FakeResponse(409, {
              'code': 'offer_economics_changed',
              'detail': 'This offer\'s amounts changed.',
              'current_economics': {
                'traveler_total_minor': current['traveler_total_minor'],
                'sender_total_with_boost_minor':
                    current['sender_total_with_boost_minor'],
              },
            });
          }
          return FakeResponse(201, _senderDeal());
        });

        // The Traveler opens the confirmation at €35.00...
        await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
        await tester.pumpAndSettle();
        expect(
          find.text(l.offerAcceptTravelerConfirmTitle(_eur(3500))),
          findsOneWidget,
        );
        // ...the sender raises the Boost before the signal arrives...
        negotiation.boost = 800;
        await tester.tap(find.widgetWithText(TextButton, l.offerAccept));
        await tester.pumpAndSettle();

        // ...and the server, not the socket, is what stops a €35.00 Deal.
        expect(bodies, [
          {'traveler_total_minor': 3500, 'sender_total_with_boost_minor': 4375},
        ]);
        expect(find.text(l.staleOfferEconomicsChanged), findsOneWidget);
        expect(_hero(tester), Money.eurCents(3800));

        // The signal lands late. Harmless: the screen already re-read.
        await _deliver(tester, screen.container, [_signal('late')]);
        expect(_hero(tester), Money.eurCents(3800));

        // Accepting now is an explicit choice of the new figures.
        await tester.tap(find.widgetWithText(AppButton, l.offerAccept));
        await tester.pumpAndSettle();
        expect(
          find.text(l.offerAcceptTravelerConfirmTitle(_eur(3800))),
          findsOneWidget,
        );
        await tester.tap(find.widgetWithText(TextButton, l.offerAccept));
        await tester.pumpAndSettle();
        expect(bodies.last, {
          'traveler_total_minor': 3800,
          'sender_total_with_boost_minor': 4750,
        });
        expect(bodies, hasLength(2));
        // Accepted: the Traveler lands on the Deal the server created.
        expect(find.text('deal 7'), findsOneWidget);
      },
    );

    testWidgets('the update line reads right-to-left in Arabic', (
      tester,
    ) async {
      final negotiation = _Negotiation();
      final screen = await _open(
        tester,
        negotiation,
        locale: const Locale('ar'),
        device: DeviceProfile.smallAndroid,
      );

      negotiation.boost = 800;
      await _deliver(tester, screen.container, [_signal('ar')]);

      final notice = find.widgetWithText(
        InfoNotice,
        screen.l.offerEconomicsUpdated,
      );
      expect(notice, findsOneWidget);
      expect(
        screen.l.offerEconomicsUpdated,
        'تم تحديث العرض. هذه أحدث المبالغ.',
      );
      expect(Directionality.of(tester.element(notice)), TextDirection.rtl);
      expect(tester.takeException(), isNull);
    });
  });
}
