/// Phase J3 Acceptance: Pricing quote, Deposit presets & guidance,
/// Additive Boost, Guest Payer Sheet, and Wax Seal Payment Success UX.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/domain/pricing.dart';
import 'package:shiptrip/features/common/payment_success_view.dart';
import 'package:shiptrip/features/guest/guest_payment_sheet.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

PaymentOrder _mockOrder({
  required String ref,
  required PaymentPurpose purpose,
  required PaymentOrderStatus status,
  Money? paid,
  Money? outstanding,
  PaymentSettlement? settlement,
}) => PaymentOrder(
  publicReference: ref,
  purpose: purpose,
  status: status,
  currency: 'EUR',
  attempts: const [],
  refunds: const [],
  providers: const [],
  paid: paid,
  outstanding: outstanding,
  settlement: settlement,
);

void main() {
  group('J3 Domain Models & Backend Contract Parsing', () {
    test(
      'PostingPricingQuote parses full J2 backend economics and actions',
      () {
        final json = {
          'currency': 'EUR',
          'minimum_reward_eur_cents': 2000,
          'recommended_reward_eur_cents': 2800,
          'chosen_reward_eur_cents': 3000,
          'minimum_economics': {
            'traveler_reward_eur_cents': 2000,
            'platform_fee_eur_cents': 500,
            'sender_total_eur_cents': 2500,
          },
          'recommended_economics': {
            'traveler_reward_eur_cents': 2800,
            'platform_fee_eur_cents': 700,
            'sender_total_eur_cents': 3500,
          },
          'chosen_economics': {
            'traveler_reward_eur_cents': 3000,
            'platform_fee_eur_cents': 750,
            'sender_total_eur_cents': 3750,
          },
          'deposit': {
            'percent_bps': 1000,
            'recommended_eur_cents': 350,
            'min_eur_cents': 300,
            'max_eur_cents': 700,
            // J6.3: the obligation ceiling, Boost included. `max_eur_cents`
            // above only clamps the recommendation.
            'maximum_eur_cents': 4375,
            'clamped': 'none',
          },
          // The keys `BoostReward.as_dict` actually sends.
          'boost': {
            'boost_eur_cents': 500,
            'boost_traveler_bonus_eur_cents': 500,
            'boost_platform_fee_eur_cents': 125,
            'boost_sender_cost_eur_cents': 625,
          },
          'actions': {'can_edit_reward': true, 'can_edit_boost': true},
        };

        final quote = PostingPricingQuote.fromJson(json);

        expect(quote.currency, 'EUR');
        expect(quote.minimumReward, Money.eurCents(2000));
        expect(quote.recommendedReward, Money.eurCents(2800));
        expect(quote.chosenReward, Money.eurCents(3000));

        expect(quote.minimumEconomics.senderTotal, Money.eurCents(2500));
        expect(quote.recommendedEconomics.senderTotal, Money.eurCents(3500));
        expect(quote.chosenEconomics?.senderTotal, Money.eurCents(3750));

        expect(quote.deposit.recommendedDeposit, Money.eurCents(350));
        expect(quote.deposit.minimumDeposit, Money.eurCents(300));
        expect(quote.deposit.maximumDeposit, Money.eurCents(4375));

        expect(quote.boost.amount, Money.eurCents(500));
        expect(quote.boost.travelerBonus, Money.eurCents(500));
        expect(quote.boost.commissionFee, Money.eurCents(125));
        expect(quote.boost.senderCost, Money.eurCents(625));
      },
    );

    test('RequestPricing parses actions and deposit guidance', () {
      final json = {
        'delivery_request_id': 42,
        'request_status': 'open',
        'currency': 'EUR',
        'minimum_reward_eur_cents': 2000,
        'recommended_reward_eur_cents': 2800,
        'minimum_economics': {
          'traveler_reward_minor': 2000,
          'platform_fee_minor': 500,
          'sender_total_minor': 2500,
        },
        'recommended_economics': {
          'traveler_reward_minor': 2800,
          'platform_fee_minor': 700,
          'sender_total_minor': 3500,
        },
        'chosen_is_below_minimum': false,
        'chosen_is_below_recommended': false,
        'deposit': {
          'currency': 'EUR',
          'required': true,
          'recommended_eur_cents': 350,
          'minimum_eur_cents': 300,
          'percent_bps': 1000,
          'recommendation_basis_eur_cents': 3500,
          'is_flexible': true,
        },
        'boost': {
          'boost_eur_cents': 500,
          'boost_platform_fee_eur_cents': 125,
          'boost_sender_cost_eur_cents': 625,
          'boost_traveler_bonus_eur_cents': 500,
          'base_reward_eur_cents': 2800,
          'total_offered_reward_eur_cents': 3300,
        },
        'actions': {
          'can_edit_boost': true,
          'can_choose_deposit': true,
          'can_cancel': true,
        },
      };

      final reqPricing = RequestPricing.fromJson(json);
      expect(reqPricing.actions.canEditBoost, isTrue);
      expect(reqPricing.actions.canChooseDeposit, isTrue);
      expect(reqPricing.deposit.recommendedDeposit, Money.eurCents(350));
    });

    test('PaymentSettlement parses settlement next steps', () {
      final depositJson = {
        'is_settled': true,
        'purpose': 'posting_deposit',
        'paid_eur_cents': 500,
        'currency': 'EUR',
        'paid_by': 'sender',
        'next_step': 'await_offers',
      };
      final depositSettlement = PaymentSettlement.fromJson(depositJson);
      expect(depositSettlement.purpose, PaymentPurpose.postingDeposit);
      expect(depositSettlement.nextStep, PaymentSettlementNextStep.awaitOffers);
      expect(depositSettlement.paid, Money.eurCents(500));

      final dealJson = {
        'is_settled': true,
        'purpose': 'deal_balance',
        'paid_eur_cents': 3500,
        'currency': 'EUR',
        'paid_by': 'guest',
        'next_step': 'await_pickup',
      };
      final dealSettlement = PaymentSettlement.fromJson(dealJson);
      expect(dealSettlement.purpose, PaymentPurpose.dealBalance);
      expect(dealSettlement.nextStep, PaymentSettlementNextStep.awaitPickup);
      expect(dealSettlement.paidBy, 'guest');
    });

    test('GuestPaymentLink parses token and paymentLink', () {
      final json = {
        'token': 'test_token_abc',
        'currency': 'EUR',
        'communication_language': 'en',
        'payment_link': 'https://test.shiptrip.app/pay/test_token_abc',
        'expires_at': '2026-09-20T12:00:00Z',
        'reissued': false,
      };
      final link = GuestPaymentLink.fromJson(json);
      expect(link.token, 'test_token_abc');
      expect(link.paymentLink, 'https://test.shiptrip.app/pay/test_token_abc');
      expect(link.reissued, isFalse);
      expect(link.communicationLanguage, CommunicationLanguage.english);
    });
  });

  group('J3 Wax Seal Receipt & Payment Success View', () {
    for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
      testWidgets(
        'renders wax seal, receipt, and next step in ${locale.languageCode}',
        (tester) async {
          final settlement = PaymentSettlement(
            isSettled: true,
            purpose: PaymentPurpose.postingDeposit,
            currency: 'EUR',
            amount: Money.eurCents(500),
            paid: Money.eurCents(500),
            depositCredited: null,
            remaining: null,
            refunded: null,
            paidBy: 'sender',
            nextStep: PaymentSettlementNextStep.awaitOffers,
          );

          final order = _mockOrder(
            ref: 'order_test_ref_9999',
            purpose: PaymentPurpose.postingDeposit,
            status: PaymentOrderStatus.paid,
            paid: Money.eurCents(500),
            settlement: settlement,
          );

          await pumpApp(
            tester,
            Scaffold(
              body: PaymentSuccessView(
                order: order,
                originPlaceName: 'Paris',
                destinationPlaceName: 'Algiers',
              ),
            ),
            locale: locale,
          );
          await tester.pumpAndSettle();

          final l = L.of(tester.element(find.byType(PaymentSuccessView)));

          // Wax Seal glyph check
          expect(find.text('✓'), findsOneWidget);

          // Contextual route check. The receipt draws travel order, not string
          // order: Arabic reads origin-first from the right, so the arrow and
          // the operands both turn round. A hard-coded `Paris → Algiers` used
          // to print the route backwards on every Arabic receipt.
          expect(
            find.text(
              locale.languageCode == 'ar'
                  ? 'Algiers ← Paris'
                  : 'Paris → Algiers',
            ),
            findsOneWidget,
          );

          // Purpose-aware next step
          expect(find.text(l.paymentSuccessDepositNextBody), findsOneWidget);

          // Card
          expect(find.byType(AppCard), findsWidgets);
        },
      );
    }

    testWidgets('Arabic payment success keeps RTL directionality', (
      tester,
    ) async {
      final settlement = PaymentSettlement(
        isSettled: true,
        purpose: PaymentPurpose.dealBalance,
        currency: 'EUR',
        amount: Money.eurCents(4000),
        paid: Money.eurCents(4000),
        depositCredited: null,
        remaining: null,
        refunded: null,
        paidBy: 'guest',
        nextStep: PaymentSettlementNextStep.awaitPickup,
      );

      final order = _mockOrder(
        ref: 'order_test_ref_8888',
        purpose: PaymentPurpose.dealBalance,
        status: PaymentOrderStatus.paid,
        paid: Money.eurCents(4000),
        settlement: settlement,
      );

      await pumpApp(
        tester,
        Scaffold(
          body: PaymentSuccessView(
            order: order,
            originPlaceName: 'Marseille',
            destinationPlaceName: 'Oran',
          ),
        ),
        locale: const Locale('ar'),
      );
      await tester.pumpAndSettle();

      expect(
        Directionality.of(tester.element(find.byType(PaymentSuccessView))),
        TextDirection.rtl,
      );
      final l = L.of(tester.element(find.byType(PaymentSuccessView)));
      expect(find.text(l.paymentSuccessDealNextBody), findsOneWidget);
    });
  });

  group('J3 Deposit Screen Presets & Deduplication', () {
    testWidgets('shows deduplicated presets and full deposit notice', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/parcels/42/posting-deposit',
          const FakeResponse(200, {
            'timing_mode': 'posting_deposit',
            'deposit_required': true,
            'request_status': 'awaiting_deposit',
            'quote': {
              'amount_eur_cents': 500,
              'currency': 'EUR',
              'percent_bps': 1000,
              'min_eur_cents': 300,
              'max_eur_cents': 700,
              'estimated_sender_total_eur_cents': 5000,
              // J6.3: "pay in full" is the obligation the server states.
              'maximum_eur_cents': 5000,
              'clamped': '',
            },
          }),
        );

      await pumpApp(
        tester,
        const DepositScreen(requestId: 42),
        container: containerFor(backend),
        locale: const Locale('en'),
      );
      await tester.pumpAndSettle();

      final l = L.of(tester.element(find.byType(DepositScreen)));

      // Preset choices exist
      expect(find.text(l.depositPresetMin('€3.00')), findsOneWidget);
      expect(find.text(l.depositPresetRecommended('€5.00')), findsOneWidget);
      expect(find.text(l.depositPresetFull('€50.00')), findsOneWidget);
      expect(find.text(l.depositPresetCustom), findsOneWidget);

      // Select full deposit. J6.3 puts the whole obligation in the hero and
      // keeps the suggested total in the guidance card, so the presets sit
      // lower on the page.
      await tester.ensureVisible(find.text(l.depositPresetFull('€50.00')));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.depositPresetFull('€50.00')));
      await tester.pumpAndSettle();

      // Full deposit notice appears
      await tester.scrollUntilVisible(
        find.text(l.depositFullDepositNotice),
        150,
        scrollable: find.byType(Scrollable).first,
      );
      expect(find.text(l.depositFullDepositNotice), findsOneWidget);
    });
  });

  group('J3 Guest Payment Sheet', () {
    testWidgets(
      'renders guest payment link generation and share/copy buttons',
      (tester) async {
        final backend = FakeBackend()
          ..on(
            'POST',
            '/api/payments/orders/order_test_123/guest-link',
            const FakeResponse(201, {
              'token': 'token_xyz_456',
              'currency': 'EUR',
              'communication_language': 'en',
              'payment_link':
                  'https://test.shiptrip.app/guest-pay/token_xyz_456',
              'expires_at': '2026-09-20T12:00:00Z',
              'reissued': false,
            }),
          )
          ..on(
            'GET',
            '/api/payments/orders/order_test_123/guest-link',
            const FakeResponse(200, {
              'token': 'token_xyz_456',
              'currency': 'EUR',
              'communication_language': 'en',
              'payment_link':
                  'https://test.shiptrip.app/guest-pay/token_xyz_456',
              'expires_at': '2026-09-20T12:00:00Z',
              'reissued': false,
            }),
          );

        final order = _mockOrder(
          ref: 'order_test_123',
          purpose: PaymentPurpose.dealBalance,
          status: PaymentOrderStatus.pending,
          outstanding: Money.eurCents(3500),
        );

        await pumpApp(
          tester,
          Scaffold(body: GuestPaymentSheet(order: order)),
          container: containerFor(backend),
          locale: const Locale('en'),
        );
        await tester.pumpAndSettle();

        final l = L.of(tester.element(find.byType(GuestPaymentSheet)));

        expect(find.text(l.guestPaymentTitle), findsOneWidget);
        expect(find.text(l.guestShareLead), findsOneWidget);
        expect(find.text(l.guestCopyAction), findsOneWidget);
        expect(find.byIcon(Icons.copy_rounded), findsWidgets);
      },
    );
  });
}
