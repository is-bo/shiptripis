/// Phase J7D — payment success, return and completion, as the payer sees it.
///
/// Every payment result in the app is now one visual system with different
/// words: the deposit that publishes a request, a Deal balance paid in full or
/// in part, a payment someone else made, a return from the provider that is
/// still being checked, a declined card, an abandoned checkout, and a payment
/// opened long after it was settled. These tests hold the words, the figures'
/// source, where each button goes, what Back does afterwards, how often the app
/// asks the server, and how it all fits on small, landscape and large-text
/// screens in English, French and Arabic.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/money/money.dart';
import 'package:shiptrip/design/components/route.dart';
import 'package:shiptrip/design/theme.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/common/payment_result.dart';
import 'package:shiptrip/features/deals/payment_screen.dart';
import 'package:shiptrip/features/requests/checkout_section.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures — the server's own shapes
// ---------------------------------------------------------------------------

Map<String, dynamic> _attempt({
  int id = 1,
  String status = 'succeeded',
  int amount = 3500,
  bool guest = false,
  String? checkoutUrl,
}) => {
  'id': id,
  'provider': 'stripe',
  'status': status,
  'amount_eur_cents': amount,
  'payment_currency': 'EUR',
  'is_guest_payment': guest,
  'failure_code': status == 'failed' ? 'card_declined' : '',
  'checkout_url': checkoutUrl,
  'expires_at': '2099-01-01T00:00:00Z',
  'created_at': '2026-09-18T09:00:00Z',
};

/// One payment order with the settlement block J7D reads.
Map<String, dynamic> _order({
  String purpose = 'deal_balance',
  String status = 'paid',
  int amount = 3500,
  int credit = 0,
  int paid = 3500,
  int outstanding = 0,
  int? lastPayment,
  String? lastPaidBy = 'self',
  List<Map<String, dynamic>>? attempts,
  int? dealId = 7,
  int? requestId,
  bool withProviders = false,
}) => {
  'public_reference': 'ord_7',
  'purpose': purpose,
  'status': status,
  'currency': 'EUR',
  'amount_eur_cents': amount,
  'deposit_credit_eur_cents': credit,
  'paid_eur_cents': paid,
  'refunded_eur_cents': 0,
  'outstanding_eur_cents': outstanding,
  'deal_id': dealId,
  'delivery_request_id': requestId,
  'paid_at': status == 'paid' ? '2026-09-18T09:05:00Z' : null,
  'attempts':
      attempts ??
      [
        if (paid > 0)
          _attempt(amount: lastPayment ?? paid, guest: lastPaidBy == 'guest'),
      ],
  'refunds': <Object>[],
  'providers': withProviders
      ? [
          {
            'provider': 'stripe',
            'available': true,
            'settlement_currency': 'EUR',
            'supports_guest_payment': false,
            'unavailable_reason': '',
            'settlement_amount_minor': outstanding,
            'settlement_amount_exponent': 2,
          },
        ]
      : <Object>[],
  'settlement': {
    'is_settled': status == 'paid',
    'purpose': purpose,
    'currency': 'EUR',
    'amount_eur_cents': amount,
    'paid_eur_cents': paid,
    'deposit_credited_eur_cents': credit,
    'remaining_eur_cents': outstanding,
    'refunded_eur_cents': 0,
    'deal_id': dealId,
    'delivery_request_id': requestId,
    'paid_by': paid > 0 ? lastPaidBy : null,
    'last_payment_eur_cents': paid > 0 ? (lastPayment ?? paid) : null,
    'last_paid_by': paid > 0 ? lastPaidBy : null,
    'next_step': purpose == 'posting_deposit'
        ? (status == 'paid' ? 'await_offers' : 'pay_posting_deposit')
        : (status == 'paid' ? 'await_pickup' : 'pay_deal_balance'),
    'paid_at': null,
  },
};

Map<String, dynamic> _dealPayment(Map<String, dynamic> order) => {
  'deal_id': 7,
  'deal_status': 'payment_required',
  'currency': 'EUR',
  'sender_total_eur_cents': 3500,
  'traveler_reward_eur_cents': 3000,
  'platform_fee_eur_cents': 500,
  'sender_total_with_boost_eur_cents': 3500,
  'order': order,
};

Map<String, dynamic> _deal() =>
    dealFixture(id: 7, status: 'payment_required')
      ..['delivery_request_id'] = 77;

Map<String, dynamic> _place(int id, String name, String country) => {
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'locality',
  'iata_code': null,
  'country_code': country,
  'parent_name': null,
  'matching_locality_id': id,
  'matching_locality_name': name,
};

/// `GET /api/parcels/77`: Jijel → Paris on the request's canonical places.
Map<String, dynamic> _request({
  String status = 'open',
  bool withRoute = true,
}) => {
  'id': 77,
  'sender_id': 42,
  'target_traveler_id': null,
  'kind': 'delivery',
  'status': status,
  'schema_version': 3,
  'title': 'Documents',
  'description': 'A folder.',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'actual_weight_kg': '1.00',
  'declared_value_eur_cents': 5000,
  'sender_proposed_reward_eur_cents': 3000,
  'boost_eur_cents': 0,
  'total_offered_reward_eur_cents': 3000,
  'ready_window_start': '2026-10-01T09:00:00Z',
  'ready_window_end': '2026-10-02T16:00:00Z',
  'deadline_at': '2026-10-04T09:00:00Z',
  'media': <Object>[],
  'item_photo_media_id': null,
  'pickup_location': null,
  'delivery_location': null,
  'pickup_place': withRoute ? _place(11, 'Jijel', 'DZ') : null,
  'delivery_place': withRoute ? _place(22, 'Paris', 'FR') : null,
};

Map<String, dynamic> _depositState(
  Map<String, dynamic> order, {
  int maximum = 3500,
}) => {
  'timing_mode': 'posting_deposit',
  'deposit_required': true,
  'request_status': order['status'] == 'paid' ? 'open' : 'awaiting_deposit',
  'order': order,
  'quote': {
    'amount_eur_cents': 500,
    'recommended_eur_cents': 500,
    'minimum_eur_cents': 300,
    'maximum_eur_cents': maximum,
    'percent_bps': 1000,
    'min_eur_cents': 300,
    'max_eur_cents': 700,
    'estimated_sender_total_eur_cents': 3500,
    'clamped': '',
  },
};

Map<String, dynamic> _depositOrder({
  String status = 'paid',
  int amount = 500,
  String? lastPaidBy = 'self',
}) => _order(
  purpose: 'posting_deposit',
  status: status,
  amount: amount,
  paid: status == 'paid' ? amount : 0,
  outstanding: status == 'paid' ? 0 : amount,
  dealId: null,
  requestId: 77,
  lastPaidBy: lastPaidBy,
  withProviders: status != 'paid',
);

const _providers = FakeResponse(200, {
  'timing_mode': 'after_acceptance',
  'canonical_currency': 'EUR',
  'providers': [
    {
      'provider': 'stripe',
      'available': true,
      'settlement_currency': 'EUR',
      'supports_guest_payment': false,
      'unavailable_reason': '',
    },
  ],
});

FakeBackend _dealBackend(Map<String, dynamic> Function() order) => FakeBackend()
  ..on('GET', '/api/me', FakeResponse(200, meFixture()))
  ..on('GET', '/api/deals/7', FakeResponse(200, _deal()))
  ..on('GET', '/api/parcels/77', FakeResponse(200, _request()))
  ..on('GET', '/api/payments/providers', _providers)
  ..handle(
    'GET',
    '/api/deals/7/payment',
    (_) => FakeResponse(200, _dealPayment(order())),
  )
  ..handle(
    'GET',
    '/api/payments/orders/ord_7',
    (_) => FakeResponse(200, order()),
  );

/// Scroll [target] into view, let the frame lay out, then tap it.
Future<void> _tap(WidgetTester tester, Finder target) async {
  await tester.ensureVisible(target);
  await tester.pump();
  await tester.tap(target);
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<void> _emitPayment(
  WidgetTester tester,
  ProviderContainer container, {
  Map<String, dynamic> data = const {'deal_id': 7},
}) async {
  final live = container.read(liveUpdatesProvider);
  live.bindAccount(42);
  live.ingest({
    'type': 'payment.captured',
    'event_id': 'payment-captured-${data.hashCode}',
    ...data,
  }, source: LiveEventSource.websocket);
  await _settle(tester);
}

/// url_launcher's default channel, answering "opened" to every launch — the
/// payer is now on the provider's page as far as the app can tell.
void _stubBrowser(WidgetTester tester, List<String> opened) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    const MethodChannel('plugins.flutter.io/url_launcher'),
    (call) async {
      if (call.method == 'launch') {
        opened.add((call.arguments as Map)['url'] as String);
      }
      return true;
    },
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/url_launcher'),
      null,
    ),
  );
}

PaymentOrder _parse(Map<String, dynamic> json) => PaymentOrder.fromJson(json);

final L _en = lookupL(const Locale('en'));
const _locale = Locale('en');

// ---------------------------------------------------------------------------
// Pumping a result on a real router, for the navigation tests
// ---------------------------------------------------------------------------

Future<GoRouter> _pumpRouter(
  WidgetTester tester, {
  required ProviderContainer container,
  required String initialLocation,
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(390, 844);
  addTearDown(tester.view.reset);
  addTearDown(container.dispose);
  final router = GoRouter(
    initialLocation: initialLocation,
    routes: [
      GoRoute(
        path: '/start',
        builder: (_, _) => const Scaffold(body: Text('start page')),
      ),
      GoRoute(
        path: '/home',
        name: Routes.home,
        builder: (_, _) => const Scaffold(body: Text('home page')),
      ),
      GoRoute(
        path: '/requests/:id',
        name: Routes.requestDetail,
        builder: (_, state) =>
            Scaffold(body: Text('request ${state.pathParameters['id']}')),
        routes: [
          GoRoute(
            path: 'deposit',
            name: Routes.requestDeposit,
            builder: (_, state) => DepositScreen(
              requestId: int.parse(state.pathParameters['id']!),
            ),
          ),
        ],
      ),
      GoRoute(
        path: '/deals/:id',
        name: Routes.deal,
        builder: (_, state) =>
            Scaffold(body: Text('deal ${state.pathParameters['id']}')),
        routes: [
          GoRoute(
            path: 'payment',
            name: Routes.dealPayment,
            builder: (_, state) => DealPaymentScreen(
              dealId: int.parse(state.pathParameters['id']!),
            ),
          ),
        ],
      ),
    ],
  );
  await tester.pumpWidget(
    UncontrolledProviderScope(
      container: container,
      child: MaterialApp.router(
        locale: _locale,
        supportedLocales: const [Locale('en'), Locale('fr'), Locale('ar')],
        localizationsDelegates: const [
          L.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        theme: buildAppTheme(brightness: Brightness.light, locale: _locale),
        routerConfig: router,
      ),
    ),
  );
  await _settle(tester);
  return router;
}

void main() {
  // -------------------------------------------------------------------------
  // What each result says — built from the server's figures only
  // -------------------------------------------------------------------------

  group('purpose-specific content', () {
    test('a deposit that just published a request', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(_depositOrder()),
        justPaid: true,
        requestPublished: true,
        currentObligation: Money.eurCents(3500),
      );
      expect(content.kind, PaymentResultKind.received);
      expect(content.title, 'Payment received');
      expect(content.eyebrow, _en.guestPurposeDeposit);
      expect(content.amount, Money.eurCents(500));
      expect(content.outcome, 'Your request is now published');
      expect(content.nextStep, _en.payResultDepositNext);
      expect(content.ledgerNote, _en.payResultDepositCredited);
      // A deposit is not the delivery: nothing is "paid in full" yet.
      expect(content.paidInFull, isFalse);
      expect(content.lines, isEmpty);
    });

    test('a deposit that covers the whole current obligation', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(_depositOrder(amount: 3500)),
        justPaid: true,
        requestPublished: true,
        currentObligation: Money.eurCents(3500),
      );
      expect(content.paidInFull, isTrue);
      expect(content.outcome, 'Your request is now published');
      expect(content.ledgerNote, _en.payResultDepositCoversTotal);
      // It must not promise that nothing can ever be due again.
      final note = content.ledgerNote!.toLowerCase();
      expect(note, isNot(contains('never')));
      expect(note, contains('only the difference'));
    });

    test('a request that is not open is not announced as published', () {
      for (final published in [false]) {
        final content = settledPaymentResult(
          l: _en,
          locale: _locale,
          order: _parse(_depositOrder()),
          justPaid: true,
          requestPublished: published,
        );
        expect(content.outcome, isNull);
        expect(content.nextStep, isNull);
      }
    });

    test('a Deal paid after a deposit credit: paid now, credit, total', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(
          _order(amount: 4200, credit: 1200, paid: 3000, lastPayment: 3000),
        ),
        justPaid: true,
      );
      expect(content.title, 'Payment received');
      expect(content.eyebrow, _en.guestPurposeRemaining);
      expect(content.amount, Money.eurCents(3000));
      // Read like a receipt: total, what the deposit covered, paid now.
      expect(content.lines.map((l) => l.label), [
        _en.payResultDeliveryTotal,
        _en.moneyDepositPaid,
        _en.payResultPaidNow,
      ]);
      expect(content.lines[0].amount, Money.eurCents(4200));
      expect(content.lines[1].isCredit, isTrue);
      expect(content.lines[1].amount, Money.eurCents(1200));
      expect(content.lines[2].amount, Money.eurCents(3000));
      // Paid in full is a stamp, never "Remaining €0.00".
      expect(content.paidInFull, isTrue);
      expect(
        content.lines.any((l) => l.label == _en.payResultRemaining),
        isFalse,
      );
      expect(content.outcome, 'Payment protected');
      expect(content.nextStep, _en.payResultDealNext);
      expect(content.nextStep!.toLowerCase(), isNot(contains('escrow')));
    });

    test('a Deal paid in one payment shows no ledger lines', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(_order()),
        justPaid: true,
      );
      expect(content.eyebrow, _en.guestPurposeDelivery);
      expect(content.amount, Money.eurCents(3500));
      expect(content.lines, isEmpty);
      expect(content.paidInFull, isTrue);
    });

    test('a partial payment keeps the success and names the remainder', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(
          _order(
            status: 'partially_paid',
            amount: 4000,
            paid: 3500,
            outstanding: 500,
          ),
        ),
        justPaid: true,
      );
      expect(content.title, 'Payment received');
      expect(content.amount, Money.eurCents(3500));
      final remaining = content.lines.last;
      expect(remaining.label, _en.payResultRemaining);
      expect(remaining.amount, Money.eurCents(500));
      expect(remaining.isEmphasised, isTrue);
      expect(content.paidInFull, isFalse);
      expect(content.outcome, isNull);
      expect(content.ledgerNote, _en.payResultRemainingNote('€5.00'));
    });

    test('someone else paying is said plainly, with no label and no email', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(_order(amount: 4250, paid: 4250, lastPaidBy: 'guest')),
        justPaid: true,
      );
      expect(content.title, 'Payment received');
      expect(content.lead, 'Someone else paid €42.50 for this payment.');
      for (final word in ['Guest', 'Self', 'External payer', '@']) {
        expect(content.lead, isNot(contains(word)));
      }
    });

    test('the amount is the payment just made, not the running total', () {
      final order = _parse(
        _order(amount: 4000, paid: 4000, lastPayment: 500, lastPaidBy: 'guest'),
      );
      expect(lastPaymentOf(order), Money.eurCents(500));
      expect(lastPaidByGuest(order), isTrue);
    });

    test('a payment opened after it settled is "already complete"', () {
      final content = settledPaymentResult(
        l: _en,
        locale: _locale,
        order: _parse(_order()),
        justPaid: false,
      );
      expect(content.kind, PaymentResultKind.alreadyComplete);
      expect(content.title, 'This payment is already complete');
    });
  });

  // -------------------------------------------------------------------------
  // The deposit screen
  // -------------------------------------------------------------------------

  group('request deposit result', () {
    FakeBackend depositBackend(Map<String, dynamic> Function() state) =>
        FakeBackend()
          ..on('GET', '/api/me', FakeResponse(200, meFixture()))
          ..on('GET', '/api/parcels/77', FakeResponse(200, _request()))
          ..on('GET', '/api/payments/providers', _providers)
          ..handle(
            'GET',
            '/api/parcels/77/posting-deposit',
            (_) => FakeResponse(200, state()),
          );

    testWidgets('settling while watching publishes and offers View request', (
      tester,
    ) async {
      var paid = false;
      final backend = depositBackend(
        () => _depositState(_depositOrder(status: paid ? 'paid' : 'pending')),
      );
      final container = containerFor(backend);
      await pumpApp(
        tester,
        const DepositScreen(requestId: 77),
        container: container,
        device: DeviceProfile.iphone,
      );
      await _settle(tester);
      expect(find.text(_en.guestPaidTitle), findsNothing);

      paid = true;
      await _emitPayment(tester, container, data: const {'request_id': 77});

      expect(find.text('Payment received'), findsOneWidget);
      expect(find.text('€5.00'), findsOneWidget);
      expect(find.text('Your request is now published'), findsOneWidget);
      expect(find.text('Jijel'), findsOneWidget);
      expect(find.text('Paris'), findsOneWidget);
      expect(find.text('View request'), findsOneWidget);
      expect(find.text('Back to Home'), findsOneWidget);
      // A deposit has no Deal: nothing points at a delivery.
      expect(find.text('View delivery'), findsNothing);
      expect(find.text('Find travelers'), findsNothing);
      // Nothing payable is left on the page.
      expect(find.byType(CheckoutSection), findsNothing);
      expect(find.textContaining('Pay '), findsNothing);
      expect(tester.takeException(), isNull);
    });

    testWidgets('opened again later it is already complete', (tester) async {
      final backend = depositBackend(() => _depositState(_depositOrder()));
      await pumpApp(
        tester,
        const DepositScreen(requestId: 77),
        container: containerFor(backend),
      );
      await _settle(tester);
      expect(find.text('This payment is already complete'), findsOneWidget);
      expect(find.text('Payment received'), findsNothing);
      expect(find.text('View request'), findsOneWidget);
    });

    testWidgets('the full obligation paid at posting is "paid in full"', (
      tester,
    ) async {
      final backend = depositBackend(
        () => _depositState(_depositOrder(amount: 3500), maximum: 3500),
      );
      await pumpApp(
        tester,
        const DepositScreen(requestId: 77),
        container: containerFor(backend),
      );
      await _settle(tester);
      expect(find.text('PAID IN FULL'), findsOneWidget);
      expect(find.text(_en.payResultDepositCoversTotal), findsOneWidget);
      expect(find.textContaining('€0.00'), findsNothing);
    });

    testWidgets('a request without a recorded route shows no route line', (
      tester,
    ) async {
      final backend = depositBackend(() => _depositState(_depositOrder()))
        ..on(
          'GET',
          '/api/parcels/77',
          FakeResponse(200, _request(withRoute: false)),
        );
      await pumpApp(
        tester,
        const DepositScreen(requestId: 77),
        container: containerFor(backend),
      );
      await _settle(tester);
      expect(find.byType(InlineRoute), findsNothing);
      expect(find.text('Jijel'), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  // The Deal payment screen
  // -------------------------------------------------------------------------

  group('Deal payment result', () {
    testWidgets('settling while watching: received, paid in full, protected', (
      tester,
    ) async {
      var order = _order(
        status: 'pending',
        amount: 4200,
        credit: 1200,
        paid: 0,
        outstanding: 3000,
        withProviders: true,
        attempts: const [],
      );
      final backend = _dealBackend(() => order);
      final container = containerFor(backend);
      await pumpApp(
        tester,
        const DealPaymentScreen(dealId: 7),
        container: container,
        device: DeviceProfile.iphone,
      );
      await _settle(tester);
      expect(find.text(_en.moneyRemainingToPay), findsWidgets);

      order = _order(amount: 4200, credit: 1200, paid: 3000, lastPayment: 3000);
      await _emitPayment(tester, container);

      expect(find.text('Payment received'), findsOneWidget);
      expect(find.text('€30.00'), findsWidgets);
      expect(find.text('−€12.00'), findsOneWidget);
      expect(find.text('€42.00'), findsOneWidget);
      expect(find.text('PAID IN FULL'), findsOneWidget);
      expect(find.text('Payment protected'), findsOneWidget);
      expect(find.text(_en.payResultDealNext), findsOneWidget);
      expect(find.text('View delivery'), findsOneWidget);
      expect(find.text('View request'), findsNothing);
      expect(find.text(_en.moneyRemainingToPay), findsNothing);
      expect(find.textContaining('€0.00'), findsNothing);
      expect(find.text('Jijel'), findsOneWidget);
    });

    testWidgets('someone else paid: the Sender is told so, and nothing else', (
      tester,
    ) async {
      final backend = _dealBackend(
        () => _order(amount: 4250, paid: 4250, lastPaidBy: 'guest'),
      );
      await pumpApp(
        tester,
        const DealPaymentScreen(dealId: 7),
        container: containerFor(backend),
      );
      await _settle(tester);
      expect(
        find.text('Someone else paid €42.50 for this payment.'),
        findsOneWidget,
      );
      expect(find.textContaining('@'), findsNothing);
      expect(find.text('Guest'), findsNothing);
    });

    testWidgets('opened after it settled: already complete, nothing to pay', (
      tester,
    ) async {
      final backend = _dealBackend(() => _order());
      await pumpApp(
        tester,
        const DealPaymentScreen(dealId: 7),
        container: containerFor(backend),
      );
      await _settle(tester);
      expect(find.text('This payment is already complete'), findsOneWidget);
      expect(find.byType(CheckoutSection), findsNothing);
      expect(find.text('View delivery'), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  // Leaving the provider and coming back
  // -------------------------------------------------------------------------

  group('return from the provider', () {
    late Map<String, dynamic> order;
    late List<String> opened;

    Future<(FakeBackend, ProviderContainer)> start(WidgetTester tester) async {
      opened = [];
      _stubBrowser(tester, opened);
      order = _order(
        status: 'pending',
        paid: 0,
        outstanding: 3500,
        withProviders: true,
        attempts: const [],
      );
      final backend = _dealBackend(() => order)
        ..on(
          'POST',
          '/api/payments/orders/ord_7/checkout',
          FakeResponse(
            201,
            _attempt(
              status: 'checkout_pending',
              checkoutUrl: 'https://checkout.stripe.test/c/pay_1',
            ),
          ),
        );
      final container = containerFor(backend);
      await pumpApp(
        tester,
        const DealPaymentScreen(dealId: 7),
        container: container,
        device: DeviceProfile.iphone,
      );
      await _settle(tester);
      final pay = find.text(
        _en.paymentPayWith('€35.00', _en.paymentProviderStripe),
      );
      expect(pay, findsOneWidget);
      // An impatient double tap opens one checkout, not two.
      await _tap(tester, pay);
      await tester.tap(pay, warnIfMissed: false);
      await _settle(tester);
      expect(
        backend.to('POST', '/api/payments/orders/ord_7/checkout'),
        hasLength(1),
      );
      expect(opened, ['https://checkout.stripe.test/c/pay_1']);
      // The payer is on the provider's page now.
      order = _order(
        status: 'pending',
        paid: 0,
        outstanding: 3500,
        withProviders: true,
        attempts: [
          _attempt(
            status: 'checkout_pending',
            checkoutUrl: 'https://checkout.stripe.test/c/pay_1',
          ),
        ],
      );
      return (backend, container);
    }

    testWidgets('checking, with no seal and no stale form above it', (
      tester,
    ) async {
      await start(tester);
      expect(find.text('Checking your payment'), findsOneWidget);
      expect(find.text(_en.payResultCheckingBody), findsOneWidget);
      // Nothing claims success before the server does.
      expect(find.text('Payment received'), findsNothing);
      expect(find.byIcon(Icons.check_rounded), findsNothing);
      // The "what you owe" summary and the Pay button step aside.
      expect(find.text(_en.moneyRemainingToPay), findsNothing);
      expect(
        find.text(_en.paymentPayWith('€35.00', _en.paymentProviderStripe)),
        findsNothing,
      );
      expect(find.text('Back to payment'), findsOneWidget);
      // Tear down the backup re-reads.
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('the live event turns checking into the result', (
      tester,
    ) async {
      final (_, container) = await start(tester);
      order = _order();
      await _emitPayment(tester, container);
      expect(find.text('Payment received'), findsOneWidget);
      expect(find.text('Checking your payment'), findsNothing);
      expect(find.text('View delivery'), findsOneWidget);
    });

    testWidgets('the backup re-reads back off and stop — no endless polling', (
      tester,
    ) async {
      final (backend, _) = await start(tester);
      for (final wait in _pollSchedule) {
        await tester.pump(Duration(seconds: wait));
        await _settle(tester);
      }
      expect(
        backend.to('GET', '/api/payments/orders/ord_7'),
        hasLength(_pollSchedule.length),
      );
      expect(find.text("We're still confirming your payment"), findsOneWidget);
      expect(find.text('Check again'), findsOneWidget);

      // Ten more minutes: not one more request on its own.
      await tester.pump(const Duration(minutes: 10));
      await _settle(tester);
      expect(backend.to('GET', '/api/payments/orders/ord_7'), hasLength(9));
    });

    testWidgets('coming back to the app asks straight away', (tester) async {
      final (backend, _) = await start(tester);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
      tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      await _settle(tester);
      expect(backend.to('GET', '/api/payments/orders/ord_7'), hasLength(1));
      await tester.pumpWidget(const SizedBox.shrink());
    });

    testWidgets('a cancelled checkout is cancelled, not failed', (
      tester,
    ) async {
      await start(tester);
      order = _order(
        status: 'pending',
        paid: 0,
        outstanding: 3500,
        withProviders: true,
        attempts: [_attempt(status: 'cancelled')],
      );
      await tester.pump(const Duration(seconds: 3));
      await _settle(tester);
      expect(find.text('Payment cancelled'), findsOneWidget);
      expect(find.text(_en.payResultCancelledBody), findsOneWidget);
      expect(find.text(_en.paymentFailedTitle), findsNothing);
      expect(find.text('Try again'), findsOneWidget);
      expect(find.text('View delivery'), findsOneWidget);

      await _tap(tester, find.text('Try again'));
      await _settle(tester);
      expect(
        find.text(_en.paymentPayWith('€35.00', _en.paymentProviderStripe)),
        findsOneWidget,
      );
      expect(find.text(_en.moneyRemainingToPay), findsWidgets);
    });

    testWidgets('a declined payment says nothing was charged, in words', (
      tester,
    ) async {
      await start(tester);
      order = _order(
        status: 'pending',
        paid: 0,
        outstanding: 3500,
        withProviders: true,
        attempts: [_attempt(status: 'failed')],
      );
      await tester.pump(const Duration(seconds: 3));
      await _settle(tester);
      expect(find.text(_en.paymentFailedTitle), findsOneWidget);
      expect(find.text(_en.paymentFailedBody), findsOneWidget);
      expect(find.textContaining('card_declined'), findsNothing);
      expect(find.text('Try again'), findsOneWidget);
    });

    testWidgets('going back to the payment resumes the same session', (
      tester,
    ) async {
      final (backend, _) = await start(tester);
      await tester.pump(const Duration(seconds: 3));
      await _settle(tester);
      await _tap(tester, find.text('Back to payment'));
      await _settle(tester);
      expect(find.text(_en.paymentContinueTitle), findsOneWidget);
      // No second checkout was opened by going back.
      expect(
        backend.to('POST', '/api/payments/orders/ord_7/checkout'),
        hasLength(1),
      );
    });

    testWidgets('a partial payment offers the remainder, not an error', (
      tester,
    ) async {
      await start(tester);
      order = _order(
        status: 'partially_paid',
        amount: 4000,
        paid: 3500,
        outstanding: 500,
        withProviders: true,
        attempts: [_attempt()],
      );
      await tester.pump(const Duration(seconds: 3));
      await _settle(tester);
      expect(find.text('Payment received'), findsOneWidget);
      expect(find.text('Remaining'), findsOneWidget);
      expect(find.text('€5.00'), findsOneWidget);
      expect(find.text('Pay remaining €5.00'), findsOneWidget);
      expect(find.text('PAID IN FULL'), findsNothing);
    });
  });

  // -------------------------------------------------------------------------
  // Where the buttons go, and what Back does afterwards
  // -------------------------------------------------------------------------

  group('navigation', () {
    FakeBackend settledDeposit() => FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on('GET', '/api/parcels/77', FakeResponse(200, _request()))
      ..on(
        'GET',
        '/api/parcels/77/posting-deposit',
        FakeResponse(200, _depositState(_depositOrder())),
      );

    testWidgets('from the request: View request returns to it', (tester) async {
      final router = await _pumpRouter(
        tester,
        container: containerFor(settledDeposit()),
        initialLocation: '/requests/77/deposit',
      );
      await _tap(tester, find.text('View request'));
      await tester.pumpAndSettle();
      expect(find.text('request 77'), findsOneWidget);
      expect(find.byType(DepositScreen), findsNothing);
      // Popped, not pushed: there is no second copy of the request, and no
      // settled payment waiting one Back away.
      expect(router.canPop(), isFalse);
    });

    testWidgets('straight from creation: the payment is replaced, never '
        'one Back away', (tester) async {
      final router = await _pumpRouter(
        tester,
        container: containerFor(settledDeposit()),
        initialLocation: '/start',
      );
      unawaited(router.push('/requests/77/deposit'));
      await tester.pumpAndSettle();
      expect(find.byType(DepositScreen), findsOneWidget);

      await _tap(tester, find.text('View request'));
      await tester.pumpAndSettle();
      expect(find.text('request 77'), findsOneWidget);
      router.pop();
      await tester.pumpAndSettle();
      expect(find.text('start page'), findsOneWidget);
      expect(find.byType(DepositScreen), findsNothing);
    });

    testWidgets('Back to Home goes home', (tester) async {
      await _pumpRouter(
        tester,
        container: containerFor(settledDeposit()),
        initialLocation: '/requests/77/deposit',
      );
      await _tap(tester, find.text('Back to Home'));
      await tester.pumpAndSettle();
      expect(find.text('home page'), findsOneWidget);
    });

    testWidgets('a Deal result goes to its delivery, never to the request', (
      tester,
    ) async {
      final router = await _pumpRouter(
        tester,
        container: containerFor(_dealBackend(() => _order())),
        initialLocation: '/deals/7/payment',
      );
      await _tap(tester, find.text('View delivery'));
      await tester.pumpAndSettle();
      expect(find.text('deal 7'), findsOneWidget);
      expect(router.canPop(), isFalse);
    });
  });

  // -------------------------------------------------------------------------
  // Three languages, five screens
  // -------------------------------------------------------------------------

  group('localisation and layout', () {
    final results = <String, PaymentResultContent Function(L l, Locale loc)>{
      'deposit': (l, loc) => settledPaymentResult(
        l: l,
        locale: loc,
        order: _parse(_depositOrder(lastPaidBy: 'guest')),
        justPaid: true,
        requestPublished: true,
        currentObligation: Money.eurCents(3500),
      ),
      'deal in full': (l, loc) => settledPaymentResult(
        l: l,
        locale: loc,
        order: _parse(
          _order(amount: 4200, credit: 1200, paid: 3000, lastPayment: 3000),
        ),
        justPaid: true,
      ),
      'partial': (l, loc) => settledPaymentResult(
        l: l,
        locale: loc,
        order: _parse(
          _order(
            status: 'partially_paid',
            amount: 4000,
            paid: 3500,
            outstanding: 500,
          ),
        ),
        justPaid: true,
      ),
      'still checking': (l, loc) => PaymentResultContent(
        kind: PaymentResultKind.stillChecking,
        title: l.payResultStillCheckingTitle,
        eyebrow: l.guestPurposeDelivery,
        lead: l.payResultStillCheckingBody,
      ),
      'failed': (l, loc) => PaymentResultContent(
        kind: PaymentResultKind.failed,
        title: l.paymentFailedTitle,
        eyebrow: l.guestPurposeDelivery,
        lead: l.paymentFailedBody,
      ),
      'cancelled': (l, loc) => PaymentResultContent(
        kind: PaymentResultKind.cancelled,
        title: l.payResultCancelledTitle,
        eyebrow: l.guestPurposeDeposit,
        lead: l.payResultCancelledBody,
      ),
    };

    for (final device in const [
      DeviceProfile.smallAndroid,
      DeviceProfile.iphone,
      DeviceProfile.android,
      DeviceProfile.landscape,
      DeviceProfile.largeText,
    ]) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        testWidgets(
          'every result fits on ${device.name} in ${locale.languageCode}',
          (tester) async {
            final l = lookupL(locale);
            for (final entry in results.entries) {
              await pumpApp(
                tester,
                Scaffold(
                  body: ListView(
                    padding: const EdgeInsets.all(16),
                    children: [
                      PaymentResultView(
                        content: entry.value(l, locale),
                        routeStops: const [
                          InlineRouteStop(label: 'Jijel'),
                          InlineRouteStop(label: 'Paris'),
                        ],
                        primary: PaymentResultAction(
                          label: l.paymentSuccessViewDeliveryAction,
                          onPressed: () {},
                        ),
                        secondary: PaymentResultAction(
                          label: l.payResultBackHome,
                          onPressed: () {},
                        ),
                      ),
                    ],
                  ),
                ),
                device: device,
                locale: locale,
              );
              await _settle(tester);
              expect(
                tester.takeException(),
                isNull,
                reason: '${entry.key} overflowed',
              );
              // 48 dp targets, whatever the text size.
              for (final label in [
                l.paymentSuccessViewDeliveryAction,
                l.payResultBackHome,
              ]) {
                final button = find.ancestor(
                  of: find.text(label),
                  matching: find.byWidgetPredicate(
                    (w) => w is ButtonStyleButton,
                  ),
                );
                expect(
                  tester.getSize(button.first).height,
                  greaterThanOrEqualTo(48),
                  reason: '${entry.key}: $label',
                );
              }
            }
          },
        );
      }
    }

    test('no stacked synonyms, no industry words, in any language', () {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        final l = lookupL(locale);
        final all = [
          l.guestPaidTitle,
          l.payResultAlreadyCompleteTitle,
          l.payResultCheckingTitle,
          l.payResultCheckingBody,
          l.payResultStillCheckingTitle,
          l.payResultStillCheckingBody,
          l.payResultCancelledTitle,
          l.payResultCancelledBody,
          l.payResultDealNext,
          l.payResultDepositCoversTotal,
          l.guestPayHandoffTitle,
          l.guestPayHandoffBody,
        ].join(' ').toLowerCase();
        for (final banned in [
          'escrow',
          'séquestre',
          'webhook',
          'intent',
          'settlement',
          'finalized',
          'is confirmed',
          'successfully',
        ]) {
          expect(all, isNot(contains(banned)), reason: '$locale: $banned');
        }
      }
      expect(_en.payResultPaidInFull, 'Paid in full');
      expect(
        lookupL(const Locale('fr')).payResultPaidInFull,
        'Payé intégralement',
      );
      expect(
        lookupL(const Locale('fr')).payResultCancelledTitle,
        'Paiement annulé',
      );
    });

    testWidgets(
      'Arabic: RTL, the route runs from the right, figures stay LTR',
      (tester) async {
        final l = lookupL(const Locale('ar'));
        await pumpApp(
          tester,
          Scaffold(
            body: ListView(
              children: [
                PaymentResultView(
                  content: results['deal in full']!(l, const Locale('ar')),
                  routeStops: const [
                    InlineRouteStop(label: 'Jijel'),
                    InlineRouteStop(label: 'Paris'),
                  ],
                ),
              ],
            ),
          ),
          locale: const Locale('ar'),
        );
        await _settle(tester);
        expect(
          tester.getCenter(find.text('Jijel')).dx,
          greaterThan(tester.getCenter(find.text('Paris')).dx),
        );
        // One arrow glyph that mirrors itself; no hand-flipped constant.
        expect(find.byIcon(Icons.arrow_forward_rounded), findsOneWidget);
        expect(find.byIcon(Icons.arrow_back_rounded), findsNothing);
        final credit = tester.widget<Text>(find.textContaining('−'));
        expect(credit.textDirection, TextDirection.ltr);
        expect(find.text(l.payResultPaidInFull), findsOneWidget);
      },
    );
  });

  group('Arabic figures inside sentences', () {
    // Measured, not eyeballed: a rendered Arabic line is easy to misread,
    // and an assertion on the string cannot see where the euro sign lands.
    double x(RenderParagraph p, String text, String char) => p
        .getBoxesForSelection(
          TextSelection(
            baseOffset: text.indexOf(char),
            extentOffset: text.indexOf(char) + 1,
          ),
        )
        .first
        .left;

    testWidgets('"42,50 €" keeps its order inside the Arabic sentence', (
      tester,
    ) async {
      const ar = Locale('ar');
      final l = lookupL(ar);
      final content = settledPaymentResult(
        l: l,
        locale: ar,
        order: _parse(_order(amount: 4250, paid: 4250, lastPaidBy: 'guest')),
        justPaid: true,
      );
      await pumpApp(
        tester,
        Scaffold(
          body: ListView(children: [PaymentResultView(content: content)]),
        ),
        locale: ar,
      );
      await _settle(tester);
      final lead = content.lead!;
      final paragraph = tester.renderObject<RenderParagraph>(find.text(lead));
      expect(x(paragraph, lead, '€'), greaterThan(x(paragraph, lead, '4')));

      // In J7E, Money.format universally provides the LTR isolate, so
      // sentences interpolating Money also keep "42,50 €" in natural order.
      final interpolated = l.payResultSomeoneElsePaid(
        Money.eurCents(4250).format(ar),
      );
      await pumpApp(
        tester,
        Scaffold(body: Center(child: Text(interpolated))),
        locale: ar,
      );
      await _settle(tester);
      final plain = tester.renderObject<RenderParagraph>(
        find.text(interpolated),
      );
      expect(
        x(plain, interpolated, '€'),
        greaterThan(x(plain, interpolated, '4')),
      );

      // Without an isolate (raw NumberFormat currency), the euro sign jumps
      // to the front of the number in RTL text — what shipped before J7D/J7E.
      final rawFormatted = NumberFormat.currency(
        locale: 'ar_DZ',
        symbol: '€',
        decimalDigits: 2,
      ).format(42.5);
      final legacy = l.payResultSomeoneElsePaid(rawFormatted);
      await pumpApp(
        tester,
        Scaffold(body: Center(child: Text(legacy))),
        locale: ar,
      );
      await _settle(tester);
      final legacyPlain = tester.renderObject<RenderParagraph>(
        find.text(legacy),
      );
      expect(
        x(legacyPlain, legacy, '€'),
        lessThan(x(legacyPlain, legacy, '4')),
      );
    });

    test('other languages are left untouched', () {
      expect(
        paymentResultFigure(Money.eurCents(4250), const Locale('en')),
        '€42.50',
      );
      final fr = paymentResultFigure(Money.eurCents(4250), const Locale('fr'));
      expect(fr.contains('\u2066'), isFalse);
      final ar = paymentResultFigure(Money.eurCents(4250), const Locale('ar'));
      expect(ar.startsWith('\u2066'), isTrue);
      expect(ar.endsWith('\u2069'), isTrue);
      expect(ar.contains('\u200f'), isFalse);
    });
  });

  // -------------------------------------------------------------------------
  // Accessibility
  // -------------------------------------------------------------------------

  group('accessibility', () {
    testWidgets(
      'the outcome is a live heading and the amount has its purpose',
      (tester) async {
        final handle = tester.ensureSemantics();
        await pumpApp(
          tester,
          Scaffold(
            body: ListView(
              children: [
                PaymentResultView(
                  content: settledPaymentResult(
                    l: _en,
                    locale: _locale,
                    order: _parse(_order()),
                    justPaid: true,
                  ),
                ),
              ],
            ),
          ),
        );
        await _settle(tester);
        expect(
          tester.getSemantics(find.text('Payment received')),
          isSemantics(isHeader: true, isLiveRegion: true),
        );
        expect(
          find.bySemanticsLabel('Amount paid: €35.00. Delivery payment'),
          findsOneWidget,
        );
        // The seal is decoration; the heading already says it.
        expect(
          find.descendant(
            of: find.byType(PaymentResultMark),
            matching: find.byType(ExcludeSemantics),
          ),
          findsWidgets,
        );
        expect(find.bySemanticsLabel('Paid in full'), findsOneWidget);
        handle.dispose();
      },
    );

    testWidgets('checking is announced, and the ring respects reduced motion', (
      tester,
    ) async {
      final handle = tester.ensureSemantics();
      await pumpApp(
        tester,
        Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context).copyWith(disableAnimations: true),
            child: Scaffold(
              body: PaymentResultView(
                content: PaymentResultContent(
                  kind: PaymentResultKind.checking,
                  title: _en.payResultCheckingTitle,
                ),
              ),
            ),
          ),
        ),
      );
      // A still arc: this settles, where a spinning one never would.
      await tester.pumpAndSettle();
      expect(
        tester.getSemantics(find.text('Checking your payment')),
        isSemantics(isHeader: true, isLiveRegion: true),
      );
      final ring = tester.widget<CircularProgressIndicator>(
        find.byType(CircularProgressIndicator),
      );
      expect(ring.value, isNotNull);
      handle.dispose();
    });
  });
}

/// Mirrors the checkout's backup schedule: nine backing-off re-reads.
const _pollSchedule = [3, 3, 5, 5, 10, 10, 20, 20, 20];
