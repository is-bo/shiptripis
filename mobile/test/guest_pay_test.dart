/// Guest checkout contract and receipt-email coverage.
///
/// The anonymous payer owns no ShipTrip identity. The only new input on this
/// surface is the mailbox used for the provider-independent receipt/failure/
/// refund messages; the server still owns every amount and the hosted provider
/// still owns card details.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/guest/guest_pay_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

FakeResponse _checkoutResponse(RecordedRequest request) => FakeResponse(201, {
  'checkout_url': 'https://checkout.example/session',
  'provider': request.body['provider'],
  'payment_currency': 'EUR',
  'amount_eur_cents': 4200,
  'expires_at': '2026-09-01T00:00:00Z',
});

FakeBackend _guestBackend({FakeHandler? checkout}) => FakeBackend()
  ..on(
    'GET',
    '/api/payments/guest/opaque',
    FakeResponse(200, {
      'amount_eur_cents': 4200,
      'currency': 'EUR',
      'description': 'Payment for a ShipTrip delivery',
      'expires_at': '2026-09-01T00:00:00Z',
      'providers': [
        {
          'provider': 'stripe',
          'available': true,
          'payment_currency': 'EUR',
          'supports_guest_payment': true,
          'unavailable_reason': '',
        },
      ],
    }),
  )
  ..handle(
    'POST',
    '/api/payments/guest/opaque/checkout',
    checkout ?? _checkoutResponse,
  );

void main() {
  group('guest checkout email contract', () {
    test('sends the trimmed payer email and provider only', () async {
      final backend = _guestBackend();
      final container = containerFor(backend);
      addTearDown(container.dispose);

      await container
          .read(paymentRepositoryProvider)
          .guestCheckout(
            token: 'opaque',
            provider: PaymentProviderId.stripe,
            email: '  payer@example.eu  ',
          );

      expect(
        backend.lastTo('POST', '/api/payments/guest/opaque/checkout')!.body,
        {'provider': 'stripe', 'email': 'payer@example.eu'},
      );
    });

    test(
      'does not send a blank email or grant any extra guest fields',
      () async {
        final backend = _guestBackend();
        final container = containerFor(backend);
        addTearDown(container.dispose);

        await container
            .read(paymentRepositoryProvider)
            .guestCheckout(
              token: 'opaque',
              provider: PaymentProviderId.stripe,
              email: '   ',
            );

        final body = backend
            .lastTo('POST', '/api/payments/guest/opaque/checkout')!
            .body;
        expect(body, {'provider': 'stripe'});
        expect(body.keys, containsAll(<String>['provider']));
        expect(body.keys, isNot(contains('deal_id')));
        expect(body.keys, isNot(contains('recipient')));
        expect(body.keys, isNot(contains('communication_language')));
      },
    );

    testWidgets('the payer must enter a valid receipt email before checkout', (
      tester,
    ) async {
      final backend = _guestBackend();
      final container = containerFor(backend);
      addTearDown(container.dispose);

      await pumpApp(
        tester,
        const GuestPayScreen(token: 'opaque'),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Your email for the receipt'), findsOneWidget);
      expect(find.textContaining('payment receipt'), findsOneWidget);

      await tester.enterText(find.byType(TextFormField), 'not-an-email');
      await tester.tap(find.text('Stripe'));
      await tester.pump();
      await tester.enterText(find.byType(TextFormField), 'not-an-email');
      await tester.tap(find.text('Pay €42.00'));
      await tester.pump();

      expect(find.text('Enter a valid email address'), findsOneWidget);
      expect(
        backend.to('POST', '/api/payments/guest/opaque/checkout'),
        isEmpty,
      );
    });
  });
}
