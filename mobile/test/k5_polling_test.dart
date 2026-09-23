/// K5 (13.18): the payment re-reads end, and there is only ever one of them.
///
/// Both fallbacks — the checkout's "Checking your payment" re-reads and the
/// guest-link sheet's poll — exist for a payer whose live event is late. They
/// must stop on a terminal answer and when their screen closes, never run two
/// loops side by side, and not spend their budget while the app is off screen.
/// None of them ever decides a payment happened: only the server's order does.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:dio/dio.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/guest/guest_payment_sheet.dart';
import 'package:shiptrip/features/requests/checkout_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _ref = 'ord_k5';
const _orderPath = '/api/payments/orders/$_ref';
const _linkPath = '/api/payments/orders/$_ref/guest-link';
const _checkoutUrl = 'https://checkout.stripe.test/c/k5';

final L _en = lookupL(const Locale('en'));

Map<String, dynamic> _attempt(String status) => {
  'id': 1,
  'provider': 'stripe',
  'status': status,
  'amount_eur_cents': 3500,
  'payment_currency': 'EUR',
  'is_guest_payment': false,
  'failure_code': status == 'failed' ? 'card_declined' : '',
  'checkout_url': _checkoutUrl,
  'expires_at': '2099-01-01T00:00:00Z',
  'created_at': '2026-09-18T09:00:00Z',
};

Map<String, dynamic> _order({
  bool paid = false,
  List<Map<String, dynamic>> attempts = const [],
}) => {
  'public_reference': _ref,
  'purpose': 'deal_balance',
  'status': paid ? 'paid' : 'pending',
  'currency': 'EUR',
  'amount_eur_cents': 3500,
  'deposit_credit_eur_cents': 0,
  'paid_eur_cents': paid ? 3500 : 0,
  'refunded_eur_cents': 0,
  'outstanding_eur_cents': paid ? 0 : 3500,
  'deal_id': 7,
  'delivery_request_id': null,
  'paid_at': paid ? '2026-09-18T09:05:00Z' : null,
  'attempts': paid ? [_attempt('succeeded')] : attempts,
  'refunds': <Object>[],
  'providers': [
    {
      'provider': 'stripe',
      'available': true,
      'settlement_currency': 'EUR',
      'supports_guest_payment': true,
      'unavailable_reason': '',
      'settlement_amount_minor': 3500,
      'settlement_amount_exponent': 2,
    },
  ],
};

Map<String, dynamic> _activeLink() => {
  'state': 'active',
  'token': 'tok_k5_abcdefghijklmnop',
  'payment_link': 'https://test.shiptrip.app/pay/guest/tok_k5_abcdefghijklmnop',
  'expires_at': '2099-01-01T12:00:00Z',
  'amount_eur_cents': 3500,
  'currency': 'EUR',
  'purpose': 'deal_balance',
  'communication_language': 'en',
  'checkout_in_progress': false,
  'can_create': true,
  'can_revoke': true,
  'reused': true,
  'reissued': false,
};

/// A server whose order reads can be held open, to put a re-read in flight
/// exactly when the app returns or the payer backs out.
class _Server {
  _Server() {
    backend
      ..on(
        'GET',
        '/api/payments/providers',
        const FakeResponse(200, {
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
        }),
      )
      ..handle(
        'POST',
        '$_orderPath/checkout',
        (_) => FakeResponse(201, _attempt('checkout_pending')),
      )
      ..handle('GET', _linkPath, (_) => FakeResponse(200, _activeLink()))
      ..handle('GET', _orderPath, (_) async {
        final held = gate;
        if (held != null) await held.future;
        return FakeResponse(200, order);
      });
  }

  final backend = FakeBackend();
  Map<String, dynamic> order = _order(attempts: [_attempt('checkout_pending')]);

  /// While set, every order read waits for it.
  Completer<void>? gate;

  int get orderReads => backend.to('GET', _orderPath).length;
  int get checkouts => backend.to('POST', '$_orderPath/checkout').length;

  void release() {
    gate?.complete();
    gate = null;
  }
}

/// Order reads answered by hand, in the order they were sent.
List<Completer<FakeResponse>> _holdOrderReads(
  FakeBackend backend,
  String path,
) {
  final replies = <Completer<FakeResponse>>[];
  backend.handle('GET', path, (_) {
    final reply = Completer<FakeResponse>();
    replies.add(reply);
    return reply.future;
  });
  return replies;
}

/// Order reads that fail in a way no `ApiException` describes: an answer the
/// client cannot interpret.
class _UnreadableOrders extends PaymentRepository {
  _UnreadableOrders(super.api);

  int reads = 0;

  @override
  Future<PaymentOrder> order(String reference, {CancelToken? cancelToken}) {
    reads++;
    throw StateError('settlement is malformed');
  }
}

void _stubBrowser(WidgetTester tester) {
  const channel = MethodChannel('plugins.flutter.io/url_launcher');
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    channel,
    (call) async => true,
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      channel,
      null,
    ),
  );
}

/// The lifecycle a phone actually delivers: the framework walks every state
/// in between, so a return from the browser is `hidden → inactive → resumed`.
void _leave(WidgetTester tester) {
  for (final state in [
    AppLifecycleState.inactive,
    AppLifecycleState.hidden,
    AppLifecycleState.paused,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

void _return(WidgetTester tester) {
  for (final state in [
    AppLifecycleState.hidden,
    AppLifecycleState.inactive,
    AppLifecycleState.resumed,
  ]) {
    tester.binding.handleAppLifecycleStateChanged(state);
  }
}

Future<void> _settle(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 50));
  }
}

Future<void> _pumpFor(WidgetTester tester, Duration total) async {
  const step = Duration(milliseconds: 250);
  for (var t = Duration.zero; t < total; t += step) {
    await tester.pump(step);
  }
}

Finder get _payButton =>
    find.text(_en.paymentPayWith('€35.00', _en.paymentProviderStripe));

/// Mounts the section on an unpaid order and pays: the payer is now on the
/// provider's page and the section is checking.
Future<void> _startChecking(
  WidgetTester tester,
  _Server server, {
  VoidCallback? onSettled,
}) async {
  _stubBrowser(tester);
  await pumpApp(
    tester,
    Scaffold(
      body: SingleChildScrollView(
        child: CheckoutSection(
          orderReference: _ref,
          order: PaymentOrder.fromJson(_order()),
          onSettled: onSettled ?? () {},
        ),
      ),
    ),
    container: containerFor(server.backend),
  );
  await _settle(tester);
  await tester.ensureVisible(_payButton);
  await tester.tap(_payButton);
  await _settle(tester);
  expect(find.text(_en.payResultCheckingTitle), findsOneWidget);
  expect(server.orderReads, 0);
}

Future<void> _pumpSheet(WidgetTester tester, _Server server) async {
  await pumpApp(
    tester,
    Scaffold(body: GuestPaymentSheet(order: PaymentOrder.fromJson(_order()))),
    container: containerFor(server.backend),
  );
  await _settle(tester);
  expect(server.backend.to('GET', _linkPath), hasLength(1));
}

void main() {
  // The binding outlives each test; start every one on screen.
  setUp(() {
    TestWidgetsFlutterBinding.ensureInitialized()
        .handleAppLifecycleStateChanged(AppLifecycleState.resumed);
  });

  group('checkout re-reads', () {
    testWidgets(
      'a return while a re-read is in flight shares it and settles once',
      (tester) async {
        var settled = 0;
        final server = _Server();
        await _startChecking(tester, server, onSettled: () => settled++);

        // The first scheduled re-read leaves and is held open.
        server.gate = Completer<void>();
        await tester.pump(const Duration(seconds: 3));
        expect(server.orderReads, 1);

        // Back from the browser mid-read. Asking again now would be a second
        // request for the same answer — and both would report it.
        tester.binding
          ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
          ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
        await _settle(tester);
        expect(server.orderReads, 1);

        server.order = _order(paid: true);
        server.release();
        await _settle(tester);
        expect(settled, 1);
        expect(find.text(_en.payResultCheckingTitle), findsNothing);

        // A terminal answer ends the schedule.
        await _pumpFor(tester, const Duration(minutes: 3));
        expect(server.orderReads, 1);
        expect(settled, 1);
      },
    );

    testWidgets(
      'backing out and paying again mid-read leaves one schedule, and '
      'leaving the screen ends it',
      (tester) async {
        final server = _Server();
        await _startChecking(tester, server);

        server.gate = Completer<void>();
        await tester.pump(const Duration(seconds: 3));
        expect(server.orderReads, 1);

        await tester.tap(find.text(_en.payResultBackToPayment));
        await _settle(tester);
        await tester.ensureVisible(_payButton);
        await tester.tap(_payButton);
        await _settle(tester);
        expect(find.text(_en.payResultCheckingTitle), findsOneWidget);

        // The old read lands after the new schedule began. It must not start a
        // loop of its own beside it.
        server.release();
        await _settle(tester);
        final afterRelease = server.orderReads;
        await _pumpFor(tester, const Duration(seconds: 4));
        expect(server.orderReads, afterRelease + 1, reason: 'one loop, 3 s');
        await _pumpFor(tester, const Duration(seconds: 3));
        expect(server.orderReads, afterRelease + 2);

        // Leaving the screen cancels every re-read, including any orphan.
        await tester.pumpWidget(const SizedBox.shrink());
        final atDispose = server.orderReads;
        await _pumpFor(tester, const Duration(minutes: 3));
        expect(server.orderReads, atDispose);
        expect(tester.takeException(), isNull);
      },
    );

    testWidgets(
      'nothing is spent while the payer is away; the return asks at once',
      (tester) async {
        final server = _Server();
        await _startChecking(tester, server);

        _leave(tester);
        await _pumpFor(tester, const Duration(minutes: 5));
        expect(
          server.orderReads,
          0,
          reason: 'the budget used to run out on the provider page',
        );

        _return(tester);
        await _settle(tester);
        expect(server.orderReads, 1);
        expect(find.text(_en.payResultCheckingTitle), findsOneWidget);

        // The schedule carries on from where it paused.
        await _pumpFor(tester, const Duration(seconds: 3));
        expect(server.orderReads, 2);

        await tester.pumpWidget(const SizedBox.shrink());
        await _pumpFor(tester, const Duration(minutes: 3));
        expect(server.orderReads, 2);
      },
    );

    testWidgets('a return from another app does not adopt a read sent before '
        'it left; one fresh read follows and settles once', (tester) async {
      var settled = 0;
      final server = _Server();
      final replies = _holdOrderReads(server.backend, _orderPath);
      await _startChecking(tester, server, onSettled: () => settled++);

      // A re-read leaves, then the payer goes to the bank app for 3-D Secure.
      await tester.pump(const Duration(seconds: 3));
      expect(replies, hasLength(1));
      _leave(tester);
      await _pumpFor(tester, const Duration(seconds: 20));
      _return(tester);
      await _settle(tester);
      expect(replies, hasLength(1), reason: 'still one read at a time');

      // The old read answers from before the 3-D Secure step.
      replies[0].complete(
        FakeResponse(200, _order(attempts: [_attempt('checkout_pending')])),
      );
      await _settle(tester);
      expect(replies, hasLength(2), reason: 'a fresh read, straight away');
      expect(settled, 0);

      replies[1].complete(FakeResponse(200, _order(paid: true)));
      await _settle(tester);
      expect(settled, 1);
      expect(find.text(_en.payResultCheckingTitle), findsNothing);

      await _pumpFor(tester, const Duration(minutes: 3));
      expect(replies, hasLength(2));
      expect(settled, 1);
    });

    testWidgets('a read for the previous order is never joined or adopted '
        'after the reference changes', (tester) async {
      const refB = 'ord_k5_b';
      const pathB = '/api/payments/orders/$refB';
      var settled = 0;
      final server = _Server();
      final repliesA = _holdOrderReads(server.backend, _orderPath);
      final repliesB = _holdOrderReads(server.backend, pathB);
      server.backend.handle(
        'POST',
        '$pathB/checkout',
        (_) => FakeResponse(201, _attempt('checkout_pending')),
      );
      final reference = ValueNotifier(_ref);
      addTearDown(reference.dispose);
      _stubBrowser(tester);
      await pumpApp(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            child: ValueListenableBuilder<String>(
              valueListenable: reference,
              builder: (_, value, _) => CheckoutSection(
                orderReference: value,
                order: PaymentOrder.fromJson({
                  ..._order(),
                  'public_reference': value,
                }),
                onSettled: () => settled++,
              ),
            ),
          ),
        ),
        container: containerFor(server.backend),
      );
      await _settle(tester);
      await tester.ensureVisible(_payButton);
      await tester.tap(_payButton);
      await _settle(tester);
      await tester.pump(const Duration(seconds: 3));
      expect(repliesA, hasLength(1));

      // The parent moves to order B while A's read is out, and B is paid.
      reference.value = refB;
      await _settle(tester);
      await tester.ensureVisible(_payButton);
      await tester.tap(_payButton);
      await _settle(tester);
      expect(find.text(_en.payResultCheckingTitle), findsOneWidget);

      // A's paid answer lands. It is not B's, so nothing settles.
      repliesA[0].complete(FakeResponse(200, _order(paid: true)));
      await _settle(tester);
      expect(settled, 0);
      expect(find.text(_en.payResultCheckingTitle), findsOneWidget);

      // B's own schedule reads B.
      await _pumpFor(tester, const Duration(seconds: 3));
      expect(repliesB, hasLength(1));
      repliesB[0].complete(
        FakeResponse(200, {..._order(paid: true), 'public_reference': refB}),
      );
      await _settle(tester);
      expect(settled, 1);
      expect(repliesA, hasLength(1));

      await tester.pumpWidget(const SizedBox.shrink());
      await _pumpFor(tester, const Duration(minutes: 3));
    });

    testWidgets('an unreadable answer keeps the schedule going and ends in '
        '"Check again", not an endless spinner', (tester) async {
      final server = _Server();
      _UnreadableOrders? orders;
      final tokens = FakeTokenStore();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(
            apiClientFor(server.backend, tokens),
          ),
          paymentRepositoryProvider.overrideWith(
            (ref) => orders = _UnreadableOrders(ref.watch(apiClientProvider)),
          ),
        ],
      );
      _stubBrowser(tester);
      await pumpApp(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            child: CheckoutSection(
              orderReference: _ref,
              order: PaymentOrder.fromJson(_order()),
              onSettled: () {},
            ),
          ),
        ),
        container: container,
      );
      await _settle(tester);
      await tester.ensureVisible(_payButton);
      await tester.tap(_payButton);
      await _settle(tester);

      await _pumpFor(tester, const Duration(minutes: 3));
      expect(tester.takeException(), isNull);
      expect(orders!.reads, 9, reason: 'the whole nine-read schedule');
      expect(find.text(_en.paymentCheckAgain), findsOneWidget);
    });

    testWidgets('a declined attempt stops the re-reads', (tester) async {
      final server = _Server();
      await _startChecking(tester, server);
      server.order = _order(attempts: [_attempt('failed')]);
      await tester.pump(const Duration(seconds: 3));
      await _settle(tester);
      expect(server.orderReads, 1);
      expect(find.text(_en.payResultCheckingTitle), findsNothing);

      await _pumpFor(tester, const Duration(minutes: 3));
      expect(server.orderReads, 1);
    });
  });

  group('guest link fallback poll', () {
    testWidgets('a return while a tick is in flight leaves one loop', (
      tester,
    ) async {
      final server = _Server();
      await _pumpSheet(tester, server);

      server.gate = Completer<void>();
      await tester.pump(const Duration(seconds: 3));
      expect(server.orderReads, 1);

      // Back from the messaging app: the fallback restarts. The held tick
      // must not keep a loop of its own going beside the new one.
      tester.binding
        ..handleAppLifecycleStateChanged(AppLifecycleState.inactive)
        ..handleAppLifecycleStateChanged(AppLifecycleState.resumed);
      // Released a second later, so a second loop would tick out of phase with
      // the restarted one instead of hiding behind its in-flight read.
      await tester.pump(const Duration(seconds: 1));
      server.release();
      await _settle(tester);
      final start = server.orderReads;

      // One loop restarted at the return reads at 3, 6, 11, 16, 26 and 46 s.
      await _pumpFor(tester, const Duration(seconds: 49));
      expect(server.orderReads - start, lessThanOrEqualTo(6));

      await tester.pumpWidget(const SizedBox.shrink());
      final atDispose = server.orderReads;
      await _pumpFor(tester, const Duration(minutes: 2));
      expect(server.orderReads, atDispose);
    });

    testWidgets('a return during a read sent before leaving reads once more '
        'when it lands', (tester) async {
      final server = _Server();
      await _pumpSheet(tester, server);

      server.gate = Completer<void>();
      await tester.pump(const Duration(seconds: 3));
      expect(server.orderReads, 1);

      _leave(tester);
      await _pumpFor(tester, const Duration(seconds: 20));
      _return(tester);
      await _settle(tester);
      expect(server.orderReads, 1, reason: 'one read at a time');

      server.release();
      await _settle(tester);
      expect(
        server.orderReads,
        2,
        reason: 'the answer from before is not kept',
      );

      await tester.pumpWidget(const SizedBox.shrink());
      await _pumpFor(tester, const Duration(minutes: 2));
    });

    testWidgets('no ticks while away; the return reads at once', (
      tester,
    ) async {
      final server = _Server();
      await _pumpSheet(tester, server);

      _leave(tester);
      await _pumpFor(tester, const Duration(minutes: 5));
      expect(server.orderReads, 0);

      _return(tester);
      await _settle(tester);
      expect(server.orderReads, 1);
      expect(server.backend.to('GET', _linkPath), hasLength(2));

      await tester.pumpWidget(const SizedBox.shrink());
      await _pumpFor(tester, const Duration(minutes: 2));
      expect(server.orderReads, 1);
    });
  });
}
