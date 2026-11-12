/// L11B: a parcel's tracking number on the screens that refer to a parcel.
///
/// What is asserted: the shared widget (left to right, spelled out, copyable,
/// absent when there is no number), that every payload the server may add the
/// number to is read, and that each screen shows it when it is there and shows
/// nothing, not a placeholder, when it is not (an older cached payload).
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/tracking.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/delivery_request.dart';
import 'package:shiptrip/domain/dispute.dart';
import 'package:shiptrip/domain/offer.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/domain/payout.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/deals/payment_screen.dart';
import 'package:shiptrip/features/disputes/dispute_detail_screen.dart';
import 'package:shiptrip/features/offers/negotiation_screen.dart';
import 'package:shiptrip/features/profile/payout_detail_screen.dart';
import 'package:shiptrip/features/profile/payouts_screen.dart';
import 'package:shiptrip/features/requests/request_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _number = 'WSL-7K3M9QXD';
const _phone = DeviceProfile(name: 'phone (360x740)', size: Size(360, 740));

Finder get _shown => find.byType(TrackingNumberView);
Finder get _numberText => find.text(_number);

Map<String, dynamic> _dealJson({String? number}) => {
  ...dealFixture(id: 7),
  'tracking_number': ?number,
};

Map<String, dynamic> _matchJson({String? number}) => {
  'id': 77,
  'parcel_id': 12,
  'sender_id': 42,
  'traveler_id': 99,
  'sender_name': 'Amina',
  'traveler_name': 'Karim',
  'status': 'pending',
  'tracking_number': ?number,
  'parcel': {
    'id': 12,
    'kind': 'delivery',
    'origin': {'id': 1, 'name': 'Paris', 'country_code': 'FR'},
    'destination': {'id': 2, 'name': 'Alger', 'country_code': 'DZ'},
  },
};

Map<String, dynamic> _paymentJson({String? number}) => {
  'deal_id': 7,
  'deal_status': 'payment_required',
  'currency': 'EUR',
  'tracking_number': ?number,
  'sender_total_eur_cents': 3500,
  'traveler_reward_eur_cents': 3000,
  'platform_fee_eur_cents': 500,
  'order': {
    'public_reference': 'ord_7',
    'purpose': 'deal_balance',
    'status': 'pending',
    'currency': 'EUR',
    'amount_eur_cents': 3500,
    'outstanding_eur_cents': 3500,
    'paid_eur_cents': 0,
    'attempts': <Object>[],
    'refunds': <Object>[],
    'providers': <Object>[],
  },
};

Map<String, dynamic> _disputeJson({String? number}) => {
  'id': 9,
  'public_reference': 'DSP-9',
  'deal_id': 7,
  'tracking_number': ?number,
  'deal_status': 'disputed',
  'status': 'open',
  'category': 'not_delivered',
  'reason_text': 'The parcel did not arrive.',
  'opened_by_id': 42,
  'opened_by_role': 'sender',
  'opened_at': '2026-08-29T09:00:00Z',
  'payout_frozen': true,
  'payout_already_settled': false,
  'evidence': <Object>[],
  'events': <Object>[],
};

Map<String, dynamic> _payoutJson({String? number}) => {
  'reference': 'po-ref-1',
  'deal_id': 7,
  'tracking_number': ?number,
  'rail': 'stripe_eur',
  'amount_eur_cents': 3000,
  'settlement_currency': 'EUR',
  'state': 'paid',
  'display_state': 'paid',
  'message_key': 'payout.paid',
  'protection_active': false,
  'available_actions': <String>[],
};

Future<void> _pumpView(
  WidgetTester tester,
  String? number, {
  Locale locale = const Locale('en'),
  bool dense = false,
}) => pumpApp(
  tester,
  Scaffold(
    body: Padding(
      padding: const EdgeInsets.all(16),
      child: TrackingNumberView(number: number, dense: dense),
    ),
  ),
  device: _phone,
  locale: locale,
);

/// Lets a provider's retry timer fire after the screen is gone, so the test
/// ends with no timer pending.
Future<void> _drain(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await tester.pump(const Duration(seconds: 5));
}

void main() {
  group('TrackingNumberView', () {
    for (final locale in const ['en', 'fr', 'ar']) {
      testWidgets('shows the number left to right at 360 px ($locale)', (
        tester,
      ) async {
        await _pumpView(tester, _number, locale: Locale(locale));
        final l = L.of(tester.element(_shown));

        expect(find.text(l.trackingNumberLabel), findsOneWidget);
        expect(_numberText, findsOneWidget);
        expect(
          Directionality.of(tester.element(_numberText)),
          TextDirection.ltr,
        );
        expect(tester.takeException(), isNull);
        // Nothing wider than the phone, and the number is not clipped.
        expect(tester.getSize(_numberText).width, lessThan(360));
      });
    }

    testWidgets('is spelled out character by character', (tester) async {
      final handle = tester.ensureSemantics();
      await _pumpView(tester, _number);
      final l = L.of(tester.element(_shown));

      expect(
        find.bySemanticsLabel(
          '${l.trackingNumberLabel}, W S L 7 K 3 M 9 Q X D',
        ),
        findsOneWidget,
      );
      handle.dispose();
    });

    testWidgets('copies the number and confirms', (tester) async {
      String? copied;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (call) async {
          if (call.method == 'Clipboard.setData') {
            copied = (call.arguments as Map)['text'] as String?;
          }
          return null;
        },
      );
      addTearDown(
        () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
          SystemChannels.platform,
          null,
        ),
      );
      await _pumpView(tester, _number);
      expect(find.byIcon(Icons.copy_rounded), findsOneWidget);

      await tester.tap(find.byIcon(Icons.copy_rounded));
      await tester.pump();

      expect(copied, _number);
      expect(find.byIcon(Icons.check_rounded), findsOneWidget);
      await tester.pump(const Duration(seconds: 3));
      expect(find.byIcon(Icons.copy_rounded), findsOneWidget);
    });

    testWidgets('dense form is one line with no copy button', (tester) async {
      await _pumpView(tester, _number, dense: true);
      expect(_numberText, findsOneWidget);
      expect(find.byIcon(Icons.copy_rounded), findsNothing);
    });

    for (final value in <String?>[null, '', '   ']) {
      testWidgets(
        'renders nothing for ${value == null ? 'null' : "'$value'"}',
        (tester) async {
          await _pumpView(tester, value);
          expect(find.byType(Text), findsNothing);
          expect(find.byType(IconButton), findsNothing);
        },
      );
    }
  });

  group('payloads', () {
    test('every payload reads the number, and none invents one', () {
      expect(
        DeliveryRequest.fromJson(
          ownRequestFixture(1)..['tracking_number'] = _number,
        ).trackingNumber,
        _number,
      );
      expect(
        DeliveryRequest.fromJson(ownRequestFixture(1)).trackingNumber,
        isNull,
      );

      expect(
        Match.fromJson(_matchJson(number: _number)).trackingNumber,
        _number,
      );
      expect(Match.fromJson(_matchJson()).trackingNumber, isNull);

      expect(Deal.fromJson(_dealJson(number: _number)).trackingNumber, _number);
      expect(Deal.fromJson(_dealJson()).trackingNumber, isNull);

      expect(
        Dispute.fromJson(_disputeJson(number: _number)).trackingNumber,
        _number,
      );
      expect(Dispute.fromJson(_disputeJson()).trackingNumber, isNull);

      expect(
        PayoutMobile.fromJson(_payoutJson(number: _number)).trackingNumber,
        _number,
      );
      expect(PayoutMobile.fromJson(_payoutJson()).trackingNumber, isNull);

      expect(
        DealPaymentState.fromJson(
          _paymentJson(number: _number),
          viewerIsTraveler: false,
        ).trackingNumber,
        _number,
      );
      expect(
        DealPaymentState.fromJson(
          _paymentJson(),
          viewerIsTraveler: false,
        ).trackingNumber,
        isNull,
      );

      expect(
        PaymentOrder.fromJson({
          'public_reference': 'ord',
          'purpose': 'posting_deposit',
          'status': 'pending',
          'tracking_number': _number,
        }).trackingNumber,
        _number,
      );
      expect(
        Offer.fromJson({
          'id': 1,
          'match': 77,
          'tracking_number': _number,
        }).trackingNumber,
        _number,
      );
      expect(
        PayoutListItem.fromJson({
          'id': 1,
          'tracking_number': _number,
          'reference': 'r',
        }).trackingNumber,
        _number,
      );
    });

    test('an empty or non-text number is no number', () {
      expect(
        Deal.fromJson({...dealFixture(), 'tracking_number': ''}).trackingNumber,
        isNull,
      );
      expect(
        Deal.fromJson({...dealFixture(), 'tracking_number': 42}).trackingNumber,
        isNull,
      );
    });
  });

  group('screens', () {
    for (final withNumber in [true, false]) {
      final tag = withNumber ? 'with' : 'without';
      final number = withNumber ? _number : null;

      testWidgets('request detail $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/parcels/77',
            FakeResponse(200, {
              ...ownRequestFixture(77),
              'tracking_number': ?number,
            }),
          )
          ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
          ..on(
            'GET',
            '/api/parcels/77/pricing',
            FakeResponse(404, {'code': 'not_found', 'detail': 'n/a'}),
          );
        await pumpApp(
          tester,
          const RequestDetailScreen(requestId: 77),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        expect(_shown, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('delivery screen $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/deals/7',
            FakeResponse(200, _dealJson(number: number)),
          );
        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('proposal $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/matches/77',
            FakeResponse(200, _matchJson(number: number)),
          )
          ..on('GET', '/api/matches/77/offers', FakeResponse(200, <Object>[]));
        await pumpApp(
          tester,
          const NegotiationScreen(matchId: 77),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('payment $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/deals/7',
            FakeResponse(200, _dealJson(number: number)),
          )
          ..on(
            'GET',
            '/api/deals/7/payment',
            FakeResponse(200, _paymentJson(number: number)),
          );
        await pumpApp(
          tester,
          const DealPaymentScreen(dealId: 7),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('dispute $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/disputes/9',
            FakeResponse(200, _disputeJson(number: number)),
          );
        await pumpApp(
          tester,
          const DisputeDetailScreen(disputeId: 9),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('payout detail $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/payouts/po-ref-1',
            FakeResponse(200, _payoutJson(number: number)),
          );
        await pumpRouted(
          tester,
          const PayoutDetailScreen(reference: 'po-ref-1'),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        await _drain(tester);
      });

      testWidgets('payout line $tag a number', (tester) async {
        final backend = FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on(
            'GET',
            '/api/payouts',
            FakeResponse(200, {
              'count': 1,
              'next': null,
              'previous': null,
              'results': [
                {
                  'id': 1,
                  'deal_id': 7,
                  'tracking_number': ?number,
                  'amount_eur_cents': 3000,
                  'method': 'stripe',
                  'status': 'paid',
                  'reference': 'po-ref-1',
                  'created_at': '2026-09-01T10:00:00Z',
                  'mobile': _payoutJson(number: number),
                },
              ],
            }),
          );
        await pumpRouted(
          tester,
          const PayoutsScreen(),
          container: containerFor(backend),
          device: _phone,
        );
        await tester.pumpAndSettle();
        expect(_numberText, withNumber ? findsOneWidget : findsNothing);
        // The list line has no copy button: the detail screen offers it.
        expect(find.byIcon(Icons.copy_rounded), findsNothing);
        await _drain(tester);
      });
    }
  });
}
