/// Phase 8F-C: the payment screen offers rails, not currency combinations.
///
/// The device-QA finding was "Stripe is showing an option to pay in DZD". The
/// screen it came from asked one question — *How would you like to pay?* —
/// listed a row called "Card" above a row that said "charged in dinars", and
/// put a single **Pay €37.50** button under both. Neither row carried a figure.
/// So the currency read as a property of the screen rather than of the rail,
/// the second row read as "the dinar option", and the button promised euros for
/// whichever rail was selected — including the one that debits dinars.
///
/// Every test below is about that: a rail states its own charge, in its own
/// settlement currency, from the server; there is no currency control anywhere;
/// and a rail the server will not transact on is not tappable.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/requests/checkout_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

/// One rail row exactly as the server publishes it.
Map<String, dynamic> railRow({
  required String provider,
  required String currency,
  bool available = true,
  String unavailableReason = '',
  int? settlementMinor,
  int settlementExponent = 2,
  int canonicalEurCents = 3750,
  String? rate,
  bool supportsGuest = true,
}) => {
  'provider': provider,
  'available': available,
  'payment_currency': currency,
  'settlement_currency': currency,
  'supports_guest_payment': supportsGuest,
  'unavailable_reason': unavailableReason,
  'canonical_currency': 'EUR',
  'canonical_amount_eur_cents': canonicalEurCents,
  if (settlementMinor != null) ...{
    'settlement_amount_minor': settlementMinor,
    'settlement_amount_exponent': settlementExponent,
  },
  if (rate != null) ...{
    'eur_dzd_rate': rate,
    'rate_settings_version': 3,
    'rate_is_indicative': true,
  },
};

/// Stripe settles euros; Chargily settles dinars at the server's rate.
final _stripeRow = railRow(
  provider: 'stripe',
  currency: 'EUR',
  settlementMinor: 3750,
);
final _chargilyRow = railRow(
  provider: 'chargily',
  currency: 'DZD',
  settlementMinor: 5625,
  settlementExponent: 0,
  rate: '150.000000',
  supportsGuest: false,
);

Map<String, dynamic> orderFixture({List<Map<String, dynamic>>? providers}) => {
  'public_reference': 'ref-8fc',
  'purpose': 'deal_balance',
  'status': 'pending',
  'currency': 'EUR',
  'amount_eur_cents': 3750,
  'outstanding_eur_cents': 3750,
  'attempts': <Map<String, dynamic>>[],
  'refunds': <Map<String, dynamic>>[],
  'providers': providers ?? [_stripeRow, _chargilyRow],
  'chargily_quote': {
    'canonical_currency': 'EUR',
    'canonical_amount_eur_cents': 3750,
    'payment_currency': 'DZD',
    'payment_amount_dzd': 5625,
    'eur_dzd_rate': '150.000000',
    'rate_settings_version': 3,
  },
};

FakeBackend backendWith(List<Map<String, dynamic>> providers) {
  final backend = FakeBackend();
  backend.on(
    'GET',
    '/api/payments/providers',
    FakeResponse(200, {
      'timing_mode': 'posting_deposit',
      'canonical_currency': 'EUR',
      'providers': providers,
      'chargily_rate': {
        'eur_dzd_rate': '150.000000',
        'rate_settings_version': 3,
      },
    }),
  );
  return backend;
}

Future<void> pumpCheckout(
  WidgetTester tester, {
  required FakeBackend backend,
  Map<String, dynamic>? order,
  Locale locale = const Locale('en'),
}) async {
  await pumpApp(
    tester,
    Scaffold(
      body: SingleChildScrollView(
        child: CheckoutSection(
          orderReference: 'ref-8fc',
          order: order == null ? null : PaymentOrder.fromJson(order),
          onSettled: () {},
        ),
      ),
    ),
    container: containerFor(backend),
    locale: locale,
  );
  await tester.pumpAndSettle();
}

/// Every rendered string on screen, for assertions about what is *absent*.
List<String> visibleText(WidgetTester tester) => tester
    .widgetList<Text>(find.byType(Text))
    .map((t) => t.data ?? t.textSpan?.toPlainText() ?? '')
    .toList(growable: false);

void main() {
  group('a rail states its own charge', () {
    testWidgets('Stripe shows euros and Chargily shows dinars, side by side', (
      tester,
    ) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      final text = visibleText(tester);
      // Both rails are named as providers, and both carry a figure. Before
      // this phase neither row had one and the euro total sat alone below.
      expect(find.text('Stripe'), findsOneWidget);
      expect(find.text('Chargily'), findsOneWidget);
      expect(text, contains('€37.50'));
      expect(text.any((t) => t.contains('5,625')), isTrue);
    });

    testWidgets('the dinar rail states the euro obligation and the rate', (
      tester,
    ) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      final text = visibleText(tester).join(' | ');
      expect(text, contains('Equivalent to €37.50'));
      expect(text, contains('150.000000'));
      // And says the rate is not yet binding.
      expect(text, contains('locked when you start'));
    });

    testWidgets('the euro rail carries no rate and no equivalence line', (
      tester,
    ) async {
      // €37.50 "equivalent to €37.50" would imply the two could differ.
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow]),
        order: orderFixture(providers: [_stripeRow]),
      );

      final text = visibleText(tester).join(' | ');
      expect(text, isNot(contains('Equivalent to')));
      expect(text, isNot(contains('150.000000')));
      expect(text, isNot(contains('DA')));
    });
  });

  group('the pay button belongs to the selected rail', () {
    testWidgets('Stripe selected pays euros, and says which rail', (
      tester,
    ) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      expect(find.text('Pay €37.50 with Stripe'), findsOneWidget);
    });

    testWidgets('choosing Chargily changes the amount AND the currency', (
      tester,
    ) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      await tester.tap(find.text('Chargily'));
      await tester.pumpAndSettle();

      // The exact defect: this button used to read "Pay €37.50" for a rail
      // that debits dinars.
      expect(find.text('Pay €37.50 with Stripe'), findsNothing);
      expect(
        find.textContaining('with Chargily'),
        findsOneWidget,
        reason: 'the button must name the rail it will actually use',
      );
      final button = tester
          .widgetList<Text>(find.textContaining('with Chargily'))
          .first
          .data!;
      expect(button.contains('5,625'), isTrue, reason: button);
      expect(button.contains('€'), isFalse, reason: button);
    });
  });

  group('there is no currency for the payer to choose', () {
    testWidgets('no rail offers an alternative currency', (tester) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      // Stripe never shows a dinar figure and Chargily never a euro charge.
      // The euro obligation appears only as the stated equivalence.
      final text = visibleText(tester);
      final stripeAdjacent = text.where(
        (t) => t.contains('Visa') || t == 'Stripe',
      );
      expect(stripeAdjacent.any((t) => t.contains('DA')), isFalse);

      // And no control exists to pick one: exactly two rails, no more.
      expect(find.text('Stripe'), findsOneWidget);
      expect(find.text('Chargily'), findsOneWidget);
      expect(find.text('EUR'), findsNothing);
      expect(find.text('DZD'), findsNothing);
    });

    testWidgets('the model reads the currency only from the server', (
      tester,
    ) async {
      final option = ProviderOption.fromJson(_chargilyRow);

      expect(option.paymentCurrency, 'DZD');
      expect(option.settlementAmount!.currency, 'DZD');
      // DZD has no minor unit: whole dinars, exponent 0.
      expect(option.settlementAmount!.exponent, 0);
      expect(option.settlementAmount!.minorUnits, 5625);
      expect(option.canonicalAmount!.minorUnits, 3750);
      expect(option.showsCanonicalEquivalent, isTrue);
      expect(
        ProviderOption.fromJson(_stripeRow).showsCanonicalEquivalent,
        false,
      );
    });
  });

  group('a rail the server will not use is not tappable', () {
    testWidgets('an invalid Chargily configuration is shown unavailable', (
      tester,
    ) async {
      final broken = railRow(
        provider: 'chargily',
        currency: 'DZD',
        available: false,
        unavailableReason: 'provider_configuration_invalid',
        settlementExponent: 0,
        supportsGuest: false,
      );
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, broken]),
        order: orderFixture(providers: [_stripeRow, broken]),
      );

      // Present and named — a payment method that silently vanishes reads as a
      // bug — but carrying a reason and no amount, and not selectable.
      expect(find.text('Chargily'), findsOneWidget);
      expect(find.text('Not ready yet'), findsOneWidget);

      await tester.tap(find.text('Chargily'));
      await tester.pumpAndSettle();

      // Selection did not move: the euro rail is still the one being paid.
      expect(find.text('Pay €37.50 with Stripe'), findsOneWidget);
    });

    testWidgets('an amount under the rail minimum reads as such', (
      tester,
    ) async {
      final tooSmall = railRow(
        provider: 'chargily',
        currency: 'DZD',
        available: false,
        unavailableReason: 'amount_below_provider_minimum',
        settlementExponent: 0,
        supportsGuest: false,
      );
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, tooSmall]),
        order: orderFixture(providers: [_stripeRow, tooSmall]),
      );

      expect(find.text("Below this method's minimum"), findsOneWidget);
    });

    testWidgets('no usable rail at all is an empty state, not a dead button', (
      tester,
    ) async {
      final off = railRow(
        provider: 'chargily',
        currency: 'DZD',
        available: false,
        unavailableReason: 'disabled_by_policy',
        settlementExponent: 0,
        supportsGuest: false,
      );
      final offStripe = railRow(
        provider: 'stripe',
        currency: 'EUR',
        available: false,
        unavailableReason: 'provider_not_configured',
      );
      await pumpCheckout(
        tester,
        backend: backendWith([offStripe, off]),
        order: orderFixture(providers: [offStripe, off]),
      );

      expect(find.text('No payment method available'), findsOneWidget);
      expect(find.textContaining('Pay '), findsNothing);
    });
  });

  group('localisation and direction', () {
    for (final locale in const [Locale('fr'), Locale('ar')]) {
      testWidgets(
        'the new payment strings are translated in ${locale.languageCode}',
        (tester) async {
          await pumpCheckout(
            tester,
            backend: backendWith([_stripeRow, _chargilyRow]),
            order: orderFixture(),
            locale: locale,
          );
          final l = L.of(tester.element(find.byType(CheckoutSection)));

          // A key that fell back to English would read identically to `en`, and
          // that is what a missing translation looks like at runtime.
          expect(l.paymentPayWith('X', 'Y'), isNot('Pay X with Y'));
          expect(l.paymentRailEquivalent('X'), isNot('Equivalent to X'));
          expect(l.paymentProviderConfigurationInvalid, isNot('Not ready yet'));
          expect(
            l.paymentCheckoutFailedTitle,
            isNot('We could not start this payment'),
          );
          expect(l.paymentRailRateLocked.isNotEmpty, isTrue);
          // The provider's own name is a proper noun and stays as it is.
          expect(l.paymentProviderStripe, 'Stripe');
        },
      );
    }

    testWidgets('the rail list lays out right-to-left in Arabic', (
      tester,
    ) async {
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
        locale: const Locale('ar'),
      );

      expect(
        Directionality.of(tester.element(find.text('Stripe'))),
        TextDirection.rtl,
      );
    });
  });

  group('the taller tile still fits a small phone', () {
    // The tile gained a right-aligned amount and up to two extra lines. A
    // provider name and a five-figure dinar amount competing for one row is
    // the obvious place for this to overflow.
    for (final device in const [
      DeviceProfile.smallAndroid,
      DeviceProfile.largeText,
      DeviceProfile.landscape,
    ]) {
      testWidgets('no overflow on ${device.name}', (tester) async {
        await pumpApp(
          tester,
          Scaffold(
            body: SingleChildScrollView(
              child: CheckoutSection(
                orderReference: 'ref-8fc',
                order: PaymentOrder.fromJson(orderFixture()),
                onSettled: () {},
              ),
            ),
          ),
          container: containerFor(backendWith([_stripeRow, _chargilyRow])),
          device: device,
        );
        await tester.pumpAndSettle();

        expect(tester.takeException(), isNull);
        expect(find.text('Chargily'), findsOneWidget);
      });
    }
  });

  group('accessibility', () {
    testWidgets('a rail announces its name and the amount it charges', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, _chargilyRow]),
        order: orderFixture(),
      );

      // A screen-reader user must not have to infer the charge from a figure
      // rendered beside a name they cannot see beside it.
      expect(
        find.bySemanticsLabel(RegExp(r'Stripe, charges €37\.50')),
        findsOneWidget,
      );
      expect(
        find.bySemanticsLabel(RegExp(r'Chargily, charges .*5,625')),
        findsOneWidget,
      );
      handle.dispose();
    });

    testWidgets('an unavailable rail is announced as disabled', (tester) async {
      final handle = tester.ensureSemantics();
      final broken = railRow(
        provider: 'chargily',
        currency: 'DZD',
        available: false,
        unavailableReason: 'provider_configuration_invalid',
        settlementExponent: 0,
        supportsGuest: false,
      );
      await pumpCheckout(
        tester,
        backend: backendWith([_stripeRow, broken]),
        order: orderFixture(providers: [_stripeRow, broken]),
      );

      final node = tester.getSemantics(find.bySemanticsLabel('Chargily'));
      // Explicitly disabled, not merely "no opinion": a screen reader must
      // announce the rail as unavailable rather than as a plain button.
      expect(node.getSemanticsData().flagsCollection.isEnabled.name, 'isFalse');
      handle.dispose();
    });
  });
}
