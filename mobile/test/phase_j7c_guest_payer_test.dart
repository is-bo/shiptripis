/// J7C — "Someone else can pay", as the Sender and the payer experience it.
///
/// Every test drives production widgets over the fake wire, so what is being
/// checked is the contract the phone actually speaks:
///
/// * opening the sheet **reads** the link and only the very first open issues
///   one — the link a relative holds is never replaced behind the Sender;
/// * the amount on screen is the server's, and its purpose is words, not enums;
/// * Share and Copy are the only primary actions, Revoke is one step away, and
///   none of them survive into a state where they no longer make sense;
/// * the payer's email appears only when a receipt will really be sent;
/// * a guest paying moves the open sheet to "Payment received" off the live
///   event, and the fallback poll is bounded.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/guest/guest_pay_screen.dart';
import 'package:shiptrip/features/guest/guest_payment_sheet.dart';
import 'package:shiptrip/features/requests/checkout_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

const _ref = 'order_j7c';
const _linkPath = '/api/payments/orders/$_ref/guest-link';
const _revokePath = '/api/payments/orders/$_ref/guest-link/revoke';
const _orderPath = '/api/payments/orders/$_ref';
const _url = 'https://test.shiptrip.app/pay/guest/tok_j7c_abcdefghijklmnop';

Map<String, dynamic> _order({
  String status = 'pending',
  String purpose = 'deal_balance',
  int outstanding = 4250,
  int paid = 0,
  int depositCredit = 0,
  List<Map<String, dynamic>> attempts = const [],
  List<Map<String, dynamic>>? providers,
}) => {
  'public_reference': _ref,
  'status': status,
  'purpose': purpose,
  'currency': 'EUR',
  'amount_eur_cents': outstanding + paid + depositCredit,
  'deposit_credit_eur_cents': depositCredit,
  'paid_eur_cents': paid,
  'outstanding_eur_cents': outstanding,
  'deal_id': 77,
  'attempts': attempts,
  'refunds': const <Map<String, dynamic>>[],
  'providers': providers ?? const <Map<String, dynamic>>[],
};

Map<String, dynamic> _link(
  String state, {
  bool shown = true,
  bool inProgress = false,
  bool canCreate = true,
  bool? canRevoke,
  int amount = 4250,
  bool reused = false,
}) {
  final live = state == 'active';
  return {
    'state': state,
    'token': live && shown ? 'tok_j7c_abcdefghijklmnop' : null,
    'payment_link': live && shown ? _url : null,
    'expires_at': live || state == 'expired' ? '2026-09-21T12:00:00Z' : null,
    'amount_eur_cents': amount,
    'currency': 'EUR',
    'purpose': 'deal_balance',
    'communication_language': 'en',
    'checkout_in_progress': inProgress,
    'can_create': canCreate && !inProgress && state != 'paid',
    'can_revoke': canRevoke ?? (live && !inProgress),
    'reused': reused,
    'reissued': false,
  };
}

/// A backend whose link state moves the way the server's does.
class _Server {
  _Server({
    Map<String, dynamic>? link,
    Map<String, dynamic>? order,
    this.createResponse,
    this.revokeResponse,
  }) : link = link ?? _link('none'),
       order = order ?? _order() {
    backend
      ..handle('GET', _linkPath, (_) => FakeResponse(200, this.link))
      ..handle('POST', _linkPath, (_) {
        final response = createResponse;
        if (response != null) return response;
        final wasActive = this.link['state'] == 'active';
        this.link = _link('active', reused: wasActive);
        return FakeResponse(wasActive ? 200 : 201, this.link);
      })
      ..handle('POST', _revokePath, (_) {
        final response = revokeResponse;
        if (response != null) return response;
        this.link = _link('revoked');
        return FakeResponse(200, {'revoked': 1, ...this.link});
      })
      ..handle('GET', _orderPath, (_) => FakeResponse(200, this.order));
  }

  final backend = FakeBackend();
  Map<String, dynamic> link;
  Map<String, dynamic> order;
  FakeResponse? createResponse;
  FakeResponse? revokeResponse;

  int get creates => backend.to('POST', _linkPath).length;
  int get linkReads => backend.to('GET', _linkPath).length;
  int get orderReads => backend.to('GET', _orderPath).length;
}

Future<L> _pumpSheet(
  WidgetTester tester,
  _Server server, {
  Map<String, dynamic>? order,
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
  VoidCallback? onSettled,
  ProviderContainer? container,
}) async {
  await pumpApp(
    tester,
    Scaffold(
      body: GuestPaymentSheet(
        order: PaymentOrder.fromJson(order ?? server.order),
        onSettled: onSettled,
      ),
    ),
    container: container ?? containerFor(server.backend),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(GuestPaymentSheet)));
}

/// Captures what reached the platform: clipboard writes and share calls.
class _Platform {
  _Platform(WidgetTester tester) {
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        clipboard = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    messenger.setMockMethodCallHandler(_shareChannel, (call) async {
      shares.add(Map<String, dynamic>.from(call.arguments as Map));
      return 'dev.fluttercommunity.plus/share/success';
    });
    addTearDown(() {
      messenger.setMockMethodCallHandler(SystemChannels.platform, null);
      messenger.setMockMethodCallHandler(_shareChannel, null);
    });
  }

  static const _shareChannel = MethodChannel('dev.fluttercommunity.plus/share');
  String? clipboard;
  final shares = <Map<String, dynamic>>[];
}

void main() {
  // -------------------------------------------------------------------------
  // Link creation and reuse
  // -------------------------------------------------------------------------

  group('link creation', () {
    testWidgets('the first open creates the link, once', (tester) async {
      final server = _Server();
      final l = await _pumpSheet(tester, server);

      expect(server.linkReads, 1);
      expect(server.creates, 1);
      expect(find.text(l.guestShareAction), findsOneWidget);
      expect(find.text(l.guestCopyAction), findsOneWidget);
      expect(find.text(l.guestStatusReady), findsOneWidget);
    });

    testWidgets('reopening reuses the live link and issues nothing', (
      tester,
    ) async {
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);

      expect(server.creates, 0, reason: 'opening must never replace a link');
      expect(find.text(l.guestShareAction), findsOneWidget);
      // The same link, recognisable, without its scheme.
      expect(
        find.text('test.shiptrip.app/pay/guest/tok_j7c_abcdefghijklmnop'),
        findsOneWidget,
      );
    });

    testWidgets('the amount is the server figure, headed by its purpose', (
      tester,
    ) async {
      // The order the sheet was opened on says 35.00; the link read says 42.50.
      // The server's latest statement wins, and nothing is recomputed.
      final server = _Server(link: _link('active', amount: 4250));
      final l = await _pumpSheet(
        tester,
        server,
        order: _order(outstanding: 3500),
      );

      expect(find.text('€42.50'), findsOneWidget);
      expect(find.text('€35.00'), findsNothing);
      expect(find.text(l.guestPurposeDelivery.toUpperCase()), findsOneWidget);
      expect(find.textContaining('deal_balance'), findsNothing);
    });

    testWidgets('a balance after a deposit is named the remaining payment', (
      tester,
    ) async {
      final server = _Server(
        link: _link('active'),
        order: _order(depositCredit: 500),
      );
      final l = await _pumpSheet(tester, server);
      expect(find.text(l.guestPurposeRemaining.toUpperCase()), findsOneWidget);
    });

    testWidgets('a deposit is named a deposit', (tester) async {
      final server = _Server(
        link: _link('active'),
        order: _order(purpose: 'posting_deposit', outstanding: 500),
      );
      final l = await _pumpSheet(tester, server);
      expect(find.text(l.guestPurposeDeposit.toUpperCase()), findsOneWidget);
    });

    testWidgets(
      'a link that cannot be shown again is replaced only on request',
      (tester) async {
        final server = _Server(link: _link('active', shown: false));
        final l = await _pumpSheet(tester, server);

        expect(server.creates, 0);
        expect(find.text(l.guestStatusHidden), findsOneWidget);
        expect(find.text(l.guestShareAction), findsNothing);

        await tester.tap(find.text(l.guestCreateNewAction));
        await tester.pumpAndSettle();
        expect(server.creates, 1);
        expect(find.text(l.guestShareAction), findsOneWidget);
      },
    );
  });

  // -------------------------------------------------------------------------
  // Email
  // -------------------------------------------------------------------------

  group('email', () {
    testWidgets('the Sender is never asked for an email', (tester) async {
      final server = _Server(link: _link('active'));
      await _pumpSheet(tester, server);
      expect(find.byType(TextField), findsNothing);
      expect(find.byType(TextFormField), findsNothing);
    });

    FakeBackend payerBackend({required bool receipts}) => FakeBackend()
      ..on(
        'GET',
        '/api/payments/guest/opaque',
        FakeResponse(200, {
          'amount_eur_cents': 4200,
          'currency': 'EUR',
          'purpose': 'deal_balance',
          'description': 'ShipTrip delivery payment',
          'expires_at': '2026-09-21T12:00:00Z',
          'receipt_email_required': receipts,
          'providers': [
            {
              'provider': 'stripe',
              'available': true,
              'payment_currency': 'EUR',
              'settlement_currency': 'EUR',
              'settlement_amount_minor': 4200,
              'settlement_amount_exponent': 2,
              'supports_guest_payment': true,
              'unavailable_reason': '',
            },
          ],
        }),
      )
      ..on(
        'POST',
        '/api/payments/guest/opaque/checkout',
        const FakeResponse(201, {
          'checkout_url': 'https://checkout.example/session',
          'provider': 'stripe',
          'payment_currency': 'EUR',
          'amount_eur_cents': 4200,
        }),
      );

    testWidgets('with receipts off the payer is not asked and none is sent', (
      tester,
    ) async {
      final backend = payerBackend(receipts: false);
      await pumpApp(
        tester,
        const GuestPayScreen(token: 'opaque'),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(GuestPayScreen)));

      expect(find.byType(TextFormField), findsNothing);
      expect(find.text(l.guestPayPayerEmail), findsNothing);
      // The amount leads, and says what it is for in words.
      expect(find.text(l.guestPayPurposeDelivery), findsOneWidget);
      expect(find.text(l.guestPayHandoff), findsOneWidget);

      await tester.tap(find.text('Stripe'));
      await tester.pump();
      await tester.tap(find.byType(FilledButton));
      for (var i = 0; i < 5; i++) {
        await tester.pump(const Duration(milliseconds: 50));
      }
      // The test host has no browser to hand off to; the request is the point.
      tester.takeException();
      final sent = backend.lastTo(
        'POST',
        '/api/payments/guest/opaque/checkout',
      );
      expect(sent, isNotNull);
      expect(sent!.body.containsKey('email'), isFalse);
    });

    testWidgets('with receipts on the field is labelled and explained', (
      tester,
    ) async {
      final backend = payerBackend(receipts: true);
      await pumpApp(
        tester,
        const GuestPayScreen(token: 'opaque'),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(GuestPayScreen)));

      expect(find.text(l.guestPayPayerEmail), findsOneWidget);
      expect(find.text(l.guestPayPayerEmailHelp), findsOneWidget);
      // The amount comes before the field, not after it.
      final amountY = tester.getTopLeft(find.text('€42.00').first).dy;
      final fieldY = tester.getTopLeft(find.byType(TextFormField)).dy;
      expect(amountY, lessThan(fieldY));
    });
  });

  // -------------------------------------------------------------------------
  // Actions
  // -------------------------------------------------------------------------

  group('actions', () {
    testWidgets('copy confirms in place, without a dialog', (tester) async {
      final platform = _Platform(tester);
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);

      await tester.tap(find.text(l.guestCopyAction));
      await tester.pump();

      expect(platform.clipboard, _url);
      expect(find.text(l.guestCopiedAction), findsOneWidget);
      expect(find.byIcon(Icons.check_rounded), findsOneWidget);
      expect(find.byType(AlertDialog), findsNothing);

      await tester.pump(const Duration(seconds: 3));
      expect(find.text(l.guestCopyAction), findsOneWidget);
    });

    testWidgets('share hands the phone a message with the link and amount', (
      tester,
    ) async {
      final platform = _Platform(tester);
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);

      await tester.tap(find.text(l.guestShareAction));
      await tester.pumpAndSettle();

      expect(platform.shares, hasLength(1));
      final shared = platform.shares.single;
      expect(shared['text'], contains(_url));
      expect(shared['text'], contains('€42.50'));
      expect(shared['subject'], l.guestShareSubject);
      expect(server.creates, 0);
    });

    testWidgets('revoke sits behind More, asks first, then says so', (
      tester,
    ) async {
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);

      // Not next to Share.
      expect(find.text(l.guestRevokeAction), findsNothing);
      await tester.tap(find.byTooltip(l.guestMoreActions));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.guestRevokeAction));
      await tester.pumpAndSettle();

      expect(find.text(l.guestRevokeConfirmTitle), findsOneWidget);
      await tester.tap(find.text(l.guestRevokeKeep));
      await tester.pumpAndSettle();
      expect(server.backend.to('POST', _revokePath), isEmpty);

      await tester.tap(find.byTooltip(l.guestMoreActions));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.guestRevokeAction));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, l.guestRevokeAction));
      await tester.pumpAndSettle();

      expect(server.backend.to('POST', _revokePath), hasLength(1));
      expect(find.text(l.guestStatusRevoked), findsOneWidget);
      expect(find.text(l.guestShareAction), findsNothing);
      expect(find.text(l.guestCopyAction), findsNothing);
      expect(find.byTooltip(l.guestMoreActions), findsNothing);
      expect(find.text(l.guestCreateNewAction), findsOneWidget);
    });

    testWidgets('a refused revoke says why in words', (tester) async {
      final server = _Server(
        link: _link('active'),
        revokeResponse: const FakeResponse(409, {
          'code': 'guest_checkout_in_progress',
          'detail': 'Someone is paying with this link right now.',
        }),
      );
      final l = await _pumpSheet(tester, server);
      server.link = _link('active', inProgress: true);

      await tester.tap(find.byTooltip(l.guestMoreActions));
      await tester.pumpAndSettle();
      await tester.tap(find.text(l.guestRevokeAction));
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, l.guestRevokeAction));
      await tester.pumpAndSettle();

      expect(find.text(l.guestErrorRevokeBusy), findsOneWidget);
      expect(find.textContaining('guest_checkout'), findsNothing);
      // The re-read shows who is holding it up.
      expect(find.text(l.guestStatusPaying), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  // States
  // -------------------------------------------------------------------------

  group('states', () {
    testWidgets('active: ready, with its expiry', (tester) async {
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);
      expect(find.text(l.guestStatusReady), findsOneWidget);
      expect(find.textContaining(l.guestStatusExpiresOn('')), findsOneWidget);
    });

    testWidgets('checkout in progress: no sharing, no revoking', (
      tester,
    ) async {
      final server = _Server(link: _link('active', inProgress: true));
      final l = await _pumpSheet(tester, server);
      expect(find.text(l.guestStatusPaying), findsOneWidget);
      expect(find.text(l.guestStatusPayingBody), findsOneWidget);
      expect(find.text(l.guestShareAction), findsNothing);
      expect(find.text(l.guestCopyAction), findsNothing);
      expect(find.byTooltip(l.guestMoreActions), findsNothing);
    });

    testWidgets('expired: said plainly, renewed only on request', (
      tester,
    ) async {
      final server = _Server(link: _link('expired'));
      final l = await _pumpSheet(tester, server);

      expect(server.creates, 0);
      expect(find.text(l.guestStatusExpired), findsOneWidget);
      expect(find.text(l.guestShareAction), findsNothing);

      await tester.tap(find.text(l.guestCreateNewAction));
      await tester.pumpAndSettle();
      expect(server.creates, 1);
      expect(find.text(l.guestStatusReady), findsOneWidget);
    });

    testWidgets('revoked: no longer active, renewable', (tester) async {
      final server = _Server(link: _link('revoked'));
      final l = await _pumpSheet(tester, server);
      expect(find.text(l.guestStatusRevoked), findsOneWidget);
      expect(find.text(l.guestCreateNewAction), findsOneWidget);
      expect(server.creates, 0);
    });

    testWidgets('paid: a result, nothing left to share', (tester) async {
      final server = _Server(
        link: _link('paid', canCreate: false),
        order: _order(status: 'paid', outstanding: 0, paid: 4250),
      );
      final l = await _pumpSheet(tester, server, order: _order());

      expect(find.text(l.guestPaidTitle), findsOneWidget);
      expect(find.text(l.guestPaidBody('€42.50')), findsOneWidget);
      for (final gone in [
        l.guestShareAction,
        l.guestCopyAction,
        l.guestRevokeAction,
        l.guestCreateNewAction,
      ]) {
        expect(find.text(gone), findsNothing);
      }
      expect(find.text(l.actionContinue), findsOneWidget);
    });

    testWidgets('already paid when creating: shows the result, not an error', (
      tester,
    ) async {
      final server = _Server(
        createResponse: const FakeResponse(409, {
          'code': 'nothing_outstanding',
          'detail': 'This order has nothing left to collect.',
        }),
        order: _order(status: 'paid', outstanding: 0, paid: 4250),
      );
      final l = await _pumpSheet(tester, server, order: _order());
      expect(find.text(l.guestPaidTitle), findsOneWidget);
      expect(find.textContaining('nothing left'), findsNothing);
    });

    testWidgets('a busy link on create is explained in words', (tester) async {
      final server = _Server(
        link: _link('expired'),
        createResponse: const FakeResponse(409, {
          'code': 'guest_checkout_in_progress',
          'detail': 'Someone is paying with the current link right now.',
        }),
      );
      final l = await _pumpSheet(tester, server);
      await tester.tap(find.text(l.guestCreateNewAction));
      await tester.pumpAndSettle();
      expect(find.text(l.guestErrorBusy), findsOneWidget);
    });

    testWidgets('a network failure offers a retry that recovers', (
      tester,
    ) async {
      final server = _Server(link: _link('active'));
      var fail = true;
      server.backend.handle(
        'GET',
        _linkPath,
        (_) => fail
            ? const FakeResponse(503, {'code': 'service_unavailable'})
            : FakeResponse(200, server.link),
      );
      final l = await _pumpSheet(tester, server);

      expect(find.text(l.guestErrorLoad), findsOneWidget);
      expect(find.text(l.guestShareAction), findsNothing);
      fail = false;
      await tester.tap(find.text(l.actionRetry));
      await tester.pumpAndSettle();
      expect(find.text(l.guestShareAction), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  // Realtime
  // -------------------------------------------------------------------------

  group('realtime', () {
    testWidgets('a guest paying moves the open sheet to Payment received', (
      tester,
    ) async {
      var settled = 0;
      final server = _Server(link: _link('active'));
      final container = containerFor(server.backend);
      final l = await _pumpSheet(
        tester,
        server,
        container: container,
        onSettled: () => settled++,
      );

      server.order = _order(status: 'paid', outstanding: 0, paid: 4250);
      server.link = _link('paid', canCreate: false);
      container.read(liveUpdatesProvider)
        ..bindAccount(42)
        ..ingest({
          'event_id': 'j7c-guest-paid',
          'type': 'payment.captured',
          'payload': {'deal_id': 77},
        }, source: LiveEventSource.websocket);
      await tester.pump(const Duration(milliseconds: 200));
      await tester.pumpAndSettle();

      expect(find.text(l.guestPaidTitle), findsOneWidget);
      expect(find.text(l.guestShareAction), findsNothing);
      expect(settled, 1);

      // Nothing keeps reading a settled order.
      final reads = server.orderReads;
      await tester.pump(const Duration(minutes: 2));
      expect(server.orderReads, reads);
      expect(settled, 1);
    });

    testWidgets('the fallback poll backs off and then stops', (tester) async {
      final server = _Server(link: _link('active'));
      await _pumpSheet(tester, server);

      // Eleven minutes of an unpaid order with the socket silent.
      for (var i = 0; i < 44; i++) {
        await tester.pump(const Duration(seconds: 15));
      }
      final withinBudget = server.orderReads;
      // 3+3+5+5+10 s, then every 20 s: about 33 reads across ten minutes —
      // never one a second.
      expect(withinBudget, lessThanOrEqualTo(36));
      expect(withinBudget, greaterThan(5));

      for (var i = 0; i < 40; i++) {
        await tester.pump(const Duration(seconds: 15));
      }
      expect(server.orderReads, withinBudget, reason: 'budget spent: stop');
    });

    testWidgets('no link that could be paid, no polling at all', (
      tester,
    ) async {
      final server = _Server(link: _link('expired'));
      await _pumpSheet(tester, server);
      for (var i = 0; i < 10; i++) {
        await tester.pump(const Duration(seconds: 30));
      }
      expect(server.orderReads, 0);
    });
  });

  // -------------------------------------------------------------------------
  // The entry point
  // -------------------------------------------------------------------------

  group('entry point', () {
    Map<String, dynamic> rail(String provider, {required bool guest}) => {
      'provider': provider,
      'available': true,
      'payment_currency': provider == 'stripe' ? 'EUR' : 'DZD',
      'settlement_currency': provider == 'stripe' ? 'EUR' : 'DZD',
      'supports_guest_payment': guest,
      'unavailable_reason': '',
      'canonical_currency': 'EUR',
      'canonical_amount_eur_cents': 4250,
      'settlement_amount_minor': provider == 'stripe' ? 4250 : 6375,
      'settlement_amount_exponent': provider == 'stripe' ? 2 : 0,
    };

    FakeBackend providersBackend() => FakeBackend()
      ..on(
        'GET',
        '/api/payments/providers',
        FakeResponse(200, {
          'timing_mode': 'posting_deposit',
          'canonical_currency': 'EUR',
          'providers': [
            rail('stripe', guest: true),
            rail('chargily', guest: false),
          ],
        }),
      );

    testWidgets('a quiet secondary action, whichever rail is selected', (
      tester,
    ) async {
      final order = PaymentOrder.fromJson(
        _order(
          providers: [
            rail('chargily', guest: false),
            rail('stripe', guest: true),
          ],
        ),
      );
      await pumpApp(
        tester,
        Scaffold(
          body: SingleChildScrollView(
            child: CheckoutSection(
              orderReference: _ref,
              order: order,
              onSettled: () {},
            ),
          ),
        ),
        container: containerFor(providersBackend()),
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(CheckoutSection)));

      // Chargily is listed first and so selected, and takes no guest payment;
      // Stripe does, and that is what the guest will use.
      final entry = find.widgetWithText(TextButton, l.guestPaymentTitle);
      expect(entry, findsOneWidget);
      expect(
        find.widgetWithText(FilledButton, l.guestPaymentTitle),
        findsNothing,
      );
    });

    testWidgets(
      'while a guest pays, the Sender is not sent into their checkout',
      (tester) async {
        final order = PaymentOrder.fromJson(
          _order(
            attempts: [
              {
                'id': 9,
                'provider': 'stripe',
                'status': 'checkout_pending',
                'amount_eur_cents': 4250,
                'payment_currency': 'EUR',
                'provider_amount_minor': 4250,
                'provider_amount_exponent': 2,
                'checkout_url': 'https://checkout.stripe.com/guest-session',
                'is_guest_payment': true,
                'expires_at': '2099-01-01T00:00:00Z',
              },
            ],
            providers: [rail('stripe', guest: true)],
          ),
        );
        await pumpApp(
          tester,
          Scaffold(
            body: SingleChildScrollView(
              child: CheckoutSection(
                orderReference: _ref,
                order: order,
                onSettled: () {},
              ),
            ),
          ),
          container: containerFor(providersBackend()),
        );
        await tester.pumpAndSettle();
        final l = L.of(tester.element(find.byType(CheckoutSection)));

        expect(find.text(l.guestPayingNowTitle), findsOneWidget);
        expect(find.text(l.paymentContinueAction), findsNothing);
      },
    );
  });

  // -------------------------------------------------------------------------
  // Localisation and layout
  // -------------------------------------------------------------------------

  group('EN / FR / AR', () {
    for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
      testWidgets(
        '${locale.languageCode}: translated, and the link stays LTR',
        (tester) async {
          final server = _Server(link: _link('active'));
          final l = await _pumpSheet(tester, server, locale: locale);

          expect(find.text(l.guestPaymentTitle), findsOneWidget);
          expect(find.text(l.guestShareAction), findsOneWidget);
          expect(find.text(l.guestStatusReady), findsOneWidget);
          final sheetDirection = Directionality.of(
            tester.element(find.text(l.guestShareAction)),
          );
          expect(
            sheetDirection,
            locale.languageCode == 'ar' ? TextDirection.rtl : TextDirection.ltr,
          );
          final urlDirection = Directionality.of(
            tester.element(
              find.text('test.shiptrip.app/pay/guest/tok_j7c_abcdefghijklmnop'),
            ),
          );
          expect(urlDirection, TextDirection.ltr);
        },
      );
    }

    test('no guest copy is left untranslated or identical to English', () {
      // Spot-check the strings a Sender reads first.
      final en = lookupL(const Locale('en'));
      for (final code in const ['fr', 'ar']) {
        final other = lookupL(Locale(code));
        for (final pair in [
          (en.guestPaymentTitle, other.guestPaymentTitle),
          (en.guestShareLead, other.guestShareLead),
          (en.guestShareAction, other.guestShareAction),
          (en.guestCopyAction, other.guestCopyAction),
          (en.guestStatusReady, other.guestStatusReady),
          (en.guestStatusExpired, other.guestStatusExpired),
          (en.guestStatusRevoked, other.guestStatusRevoked),
          (en.guestPaidTitle, other.guestPaidTitle),
          (en.guestPayPayerEmail, other.guestPayPayerEmail),
        ]) {
          expect(pair.$2, isNot(pair.$1), reason: '$code: ${pair.$1}');
          expect(pair.$2, isNotEmpty);
        }
      }
    });
  });

  group('layout', () {
    const devices = [
      DeviceProfile.smallAndroid,
      DeviceProfile.iphone,
      DeviceProfile.android,
      DeviceProfile.landscape,
      DeviceProfile.largeText,
    ];
    final states = <String, Map<String, dynamic>>{
      'active': _link('active'),
      'paying': _link('active', inProgress: true),
      'expired': _link('expired'),
    };

    for (final device in devices) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        for (final entry in states.entries) {
          testWidgets(
            '${device.name} ${locale.languageCode} ${entry.key}: no overflow',
            (tester) async {
              final server = _Server(link: entry.value);
              await _pumpSheet(tester, server, locale: locale, device: device);
              expect(tester.takeException(), isNull);
            },
          );
        }
      }
      testWidgets('${device.name}: the paid view fits', (tester) async {
        final server = _Server(
          link: _link('paid', canCreate: false),
          order: _order(status: 'paid', outstanding: 0, paid: 4250),
        );
        await _pumpSheet(
          tester,
          server,
          order: _order(),
          device: device,
          locale: const Locale('ar'),
        );
        expect(tester.takeException(), isNull);
      });
    }

    testWidgets('share, copy and the menu clear a 48dp target', (tester) async {
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(
        tester,
        server,
        device: DeviceProfile.smallAndroid,
      );
      for (final finder in [
        find.widgetWithText(FilledButton, l.guestShareAction),
        find.widgetWithText(OutlinedButton, l.guestCopyAction),
        find.byTooltip(l.guestMoreActions),
      ]) {
        final size = tester.getSize(finder);
        expect(size.height, greaterThanOrEqualTo(48), reason: '$finder');
        expect(size.width, greaterThanOrEqualTo(48), reason: '$finder');
      }
    });

    testWidgets('the amount and the status are announced', (tester) async {
      final handle = tester.ensureSemantics();
      final server = _Server(link: _link('active'));
      final l = await _pumpSheet(tester, server);
      expect(
        find.bySemanticsLabel('${l.guestPurposeDelivery}, €42.50'),
        findsOneWidget,
      );
      expect(
        tester.getSemantics(find.text(l.guestStatusReady)),
        isSemantics(isLiveRegion: true),
      );
      handle.dispose();
    });
  });
}
