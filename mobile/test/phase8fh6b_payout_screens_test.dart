/// Phase 8F-H6B: Traveler Mobile Payout UX tests.
///
/// Asserts on:
/// - PayoutMethodsScreen: preference selection, EUR/DZD cards, dynamic actions.
/// - DzdSetupScreen: strictly 6 inputs, NO NIP anywhere, mandated cheque copy in EN/FR/AR.
/// - PayoutDetailScreen: canonical EUR, frozen DZD + rate, display states, blocking reasons.
/// - PayoutsScreen: paginated history list, tapping detail.
/// - DeliveryScreen: payoutSummary integration.
/// - RTL / Localization verification.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/notification.dart';
import 'package:shiptrip/features/deals/delivery_screen.dart';
import 'package:shiptrip/features/profile/dzd_setup_screen.dart';
import 'package:shiptrip/features/profile/payout_detail_screen.dart';
import 'package:shiptrip/features/profile/payout_methods_screen.dart';
import 'package:shiptrip/features/profile/payouts_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

class _FixedSession extends SessionController {
  _FixedSession(this._account);
  final Account _account;

  @override
  SessionState build() => SessionSignedIn(_account);
}

ProviderContainer _payoutDetailContainer(FakeBackend backend) {
  final store = FakeTokenStore();
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(store),
      apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
      sessionProvider.overrideWith(
        () => _FixedSession(Account.fromJson(meFixture())),
      ),
    ],
  );
}

Map<String, dynamic> payoutMethodsFixture({
  String preference = 'both',
  String eurState = 'ready',
  String dzdState = 'ready',
  List<String> eurActions = const ['manage_eur', 'refresh'],
  List<String> dzdActions = const ['replace_dzd_profile'],
}) => {
  'contract_version': 'h6a_v1',
  'preference': preference,
  'preference_required': false,
  'revisions': {'EUR': 2, 'DZD': 1},
  'available_actions': ['update_preference'],
  'eur': {
    'state': eurState,
    'ready': eurState == 'ready',
    'supported': true,
    'country': 'FR',
    'available_actions': eurActions,
    'supported_countries': ['FR', 'DE', 'ES', 'IT'],
  },
  'dzd': {
    'state': dzdState,
    'ready': dzdState == 'ready',
    'supported': true,
    'country': 'DZ',
    'profile': {
      'revision': 1,
      'account_holder_name': 'Amine Benali',
      'ccp_last_four': '1234',
      'rip_last_four': '5678',
      'is_verified': true,
      'submitted_at': '2026-09-01T12:00:00Z',
    },
    'available_actions': dzdActions,
  },
};

Map<String, dynamic> payoutMobileFixture({
  String reference = 'po-ref-123',
  int dealId = 42,
  String rail = 'manual_dzd',
  int amountEurCents = 4500,
  int? dzdAmount = 11700,
  int? fxRateMicros = 260000000,
  String displayState = 'paid',
  String? blockingReason,
  List<String> availableActions = const ['view_deal'],
}) => {
  'reference': reference,
  'deal_id': dealId,
  'rail': rail,
  'amount_eur_cents': amountEurCents,
  'settlement_currency': dzdAmount != null ? 'DZD' : 'EUR',
  'dzd_amount': dzdAmount,
  'fx_rate_micros': fxRateMicros,
  'state': 'paid',
  'display_state': displayState,
  'message_key': 'payout.paid',
  'protection_active': false,
  'blocking_reason': blockingReason,
  'available_actions': availableActions,
  'created_at': '2026-09-01T10:00:00Z',
  'paid_at': '2026-09-03T10:00:00Z',
};

Map<String, dynamic> payoutHistoryFixture() => {
  'count': 2,
  'next': null,
  'previous': null,
  'results': [
    {
      'id': 101,
      'deal_id': 42,
      'amount_eur_cents': 4500,
      'method': 'dzd_manual',
      'status': 'paid',
      'reference': 'po-ref-101',
      'payout_currency': 'DZD',
      'payout_amount': '11700',
      'created_at': '2026-09-01T10:00:00Z',
      'paid_at': '2026-09-03T10:00:00Z',
      'mobile': payoutMobileFixture(
        reference: 'po-ref-101',
        dealId: 42,
        rail: 'manual_dzd',
        amountEurCents: 4500,
        dzdAmount: 11700,
        displayState: 'paid',
      ),
    },
    {
      'id': 102,
      'deal_id': 43,
      'amount_eur_cents': 3000,
      'method': 'stripe',
      'status': 'protection_active',
      'reference': 'po-ref-102',
      'payout_currency': 'EUR',
      'payout_amount': '30.00',
      'created_at': '2026-09-04T10:00:00Z',
      'mobile': payoutMobileFixture(
        reference: 'po-ref-102',
        dealId: 43,
        rail: 'stripe_eur',
        amountEurCents: 3000,
        dzdAmount: null,
        displayState: 'protection_active',
      ),
    },
  ],
};

void main() {
  group('PayoutMethodsScreen', () {
    testWidgets('renders preferences, EUR card, and DZD card', (tester) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/methods',
        FakeResponse(200, payoutMethodsFixture()),
      );

      final container = containerFor(backend);
      await pumpRouted(
        tester,
        const PayoutMethodsScreen(),
        container: container,
      );
      await tester.pumpAndSettle();

      // Top bar & preference card
      expect(find.text('Payout methods'), findsOneWidget);
      expect(find.text('Payout preference'), findsOneWidget);
      expect(find.text('EUR only'), findsOneWidget);
      expect(find.text('DZD only'), findsOneWidget);
      expect(find.text('Both'), findsOneWidget);

      // EUR card
      expect(find.text('EUR payouts (Stripe)'), findsOneWidget);
      expect(find.text('Manage with Stripe'), findsOneWidget);

      // DZD card
      expect(find.text('DZD payouts (CCP / BaridiMob)'), findsOneWidget);
      expect(find.text('•••• 1234'), findsOneWidget);
      expect(find.text('•••• 5678'), findsOneWidget);
      expect(find.text('Update payout information'), findsOneWidget);
    });

    testWidgets('selecting preference sends PATCH with exact wire fields', (
      tester,
    ) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/methods',
        FakeResponse(200, payoutMethodsFixture(preference: 'both')),
      );
      backend.on(
        'PATCH',
        '/api/payouts/methods',
        FakeResponse(200, payoutMethodsFixture(preference: 'eur_only')),
      );

      final container = containerFor(backend);
      await pumpRouted(
        tester,
        const PayoutMethodsScreen(),
        container: container,
      );
      await tester.pumpAndSettle();

      // Tap EUR only
      await tester.tap(find.text('EUR only'));
      await tester.pumpAndSettle();

      final patches = backend.to('PATCH', '/api/payouts/methods');
      expect(patches, hasLength(1));
      expect(patches.first.body['preference'], 'eur_only');
      expect(patches.first.body['eur_revision'], 2);
      expect(patches.first.body['dzd_revision'], 1);
    });
  });

  group('DzdSetupScreen', () {
    testWidgets('has strictly six inputs and NO NIP field', (tester) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/methods',
        FakeResponse(200, payoutMethodsFixture()),
      );

      final container = containerFor(backend);
      await pumpRouted(
        tester,
        const DzdSetupScreen(),
        container: container,
        device: DeviceProfile.iphone,
      );
      await tester.pumpAndSettle();

      // Exactly 5 text fields (First name, Last name, CCP, Key, RIP)
      expect(find.byType(TextFormField), findsNWidgets(5));

      // Scroll to reveal cheque card and submit button
      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -600),
      );
      await tester.pumpAndSettle();
      expect(find.text('Photo of the full crossed cheque'), findsOneWidget);
      expect(find.text('Upload photo'), findsOneWidget);

      // Verify ABSOLUTELY NO NIP anywhere
      expect(find.textContaining('NIP', findRichText: true), findsNothing);
      expect(
        find.textContaining('National Identification', findRichText: true),
        findsNothing,
      );
      expect(
        find.textContaining('numéro d\'identification', findRichText: true),
        findsNothing,
      );
    });

    testWidgets(
      'displays mandated cheque copy in English, French, and Arabic',
      (tester) async {
        final backend = FakeBackend();
        backend.on(
          'GET',
          '/api/payouts/methods',
          FakeResponse(200, payoutMethodsFixture()),
        );

        // EN
        await pumpRouted(
          tester,
          const DzdSetupScreen(),
          container: containerFor(backend),
          device: DeviceProfile.iphone,
          locale: const Locale('en'),
        );
        await tester.pumpAndSettle();
        await tester.drag(
          find.byType(SingleChildScrollView),
          const Offset(0, -600),
        );
        await tester.pumpAndSettle();
        expect(find.text('Photo of the full crossed cheque'), findsOneWidget);
        expect(
          find.text('Upload a clear photo of the full crossed cheque.'),
          findsOneWidget,
        );

        // FR
        await pumpRouted(
          tester,
          const DzdSetupScreen(),
          container: containerFor(backend),
          device: DeviceProfile.iphone,
          locale: const Locale('fr'),
        );
        await tester.pumpAndSettle();
        await tester.drag(
          find.byType(SingleChildScrollView),
          const Offset(0, -600),
        );
        await tester.pumpAndSettle();
        expect(find.text('Photo du chèque barré complet'), findsOneWidget);
        expect(
          find.text('Téléversez une photo claire du chèque barré complet.'),
          findsOneWidget,
        );

        // AR
        await pumpRouted(
          tester,
          const DzdSetupScreen(),
          container: containerFor(backend),
          device: DeviceProfile.iphone,
          locale: const Locale('ar'),
        );
        await tester.pumpAndSettle();
        await tester.drag(
          find.byType(SingleChildScrollView),
          const Offset(0, -600),
        );
        await tester.pumpAndSettle();
        expect(find.text('صورة كاملة لشيك مُسطَّر'), findsOneWidget);
        expect(
          find.text('حمّل صورة واضحة وكاملة للشيك المُسطَّر.'),
          findsOneWidget,
        );
      },
    );

    testWidgets('validates required fields before submission', (tester) async {
      final backend = FakeBackend();
      final container = containerFor(backend);
      await pumpRouted(
        tester,
        const DzdSetupScreen(),
        container: container,
        device: DeviceProfile.iphone,
      );
      await tester.pumpAndSettle();

      await tester.drag(
        find.byType(SingleChildScrollView),
        const Offset(0, -600),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Submit payout information'));
      await tester.pumpAndSettle();

      expect(find.text('This is required'), findsWidgets);
      expect(backend.requests.where((r) => r.method == 'POST'), isEmpty);
    });
  });

  group('PayoutDetailScreen', () {
    testWidgets('renders canonical EUR, snapshotted DZD, and rate formula', (
      tester,
    ) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/po-ref-123',
        FakeResponse(200, payoutMobileFixture()),
      );

      final container = _payoutDetailContainer(backend);
      await pumpRouted(
        tester,
        const PayoutDetailScreen(reference: 'po-ref-123'),
        container: container,
      );
      await tester.pumpAndSettle();

      // Canonical EUR
      expect(find.text('€45.00'), findsOneWidget);

      // DZD conversion and rate formula
      expect(find.textContaining('11,700'), findsOneWidget);
      expect(find.text('Frozen rate: 1 EUR = 260 DZD'), findsOneWidget);

      // Status pill
      expect(find.text('Paid'), findsOneWidget);

      // Rail and reference
      expect(find.text('CCP Transfer (DZD)'), findsOneWidget);
      expect(find.text('po-ref-123'), findsWidgets);
    });

    testWidgets('renders blocking reason when present', (tester) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts/po-blocked',
        FakeResponse(
          200,
          payoutMobileFixture(
            reference: 'po-blocked',
            displayState: 'needs_attention',
            blockingReason: 'payout_profile_needs_attention',
          ),
        ),
      );

      final container = _payoutDetailContainer(backend);
      await pumpRouted(
        tester,
        const PayoutDetailScreen(reference: 'po-blocked'),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Needs attention'), findsWidgets);
      expect(find.text('Profile needs attention'), findsOneWidget);
    });
  });

  group('PayoutsScreen (History)', () {
    testWidgets('renders paginated payout history items', (tester) async {
      final backend = FakeBackend();
      backend.on(
        'GET',
        '/api/payouts',
        FakeResponse(200, payoutHistoryFixture()),
      );

      final container = containerFor(backend);
      await pumpRouted(tester, const PayoutsScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.text('Payout history'), findsOneWidget);
      expect(find.text('€45.00'), findsOneWidget);
      expect(find.textContaining('11,700'), findsOneWidget);
      expect(find.text('€30.00'), findsOneWidget);
    });
  });

  group('DeliveryScreen payout integration', () {
    testWidgets('renders payoutSummary in traveler delivery screen', (
      tester,
    ) async {
      final backend = FakeBackend();
      final account = Account.fromJson(meFixture());

      final dealJson = {
        'id': 42,
        'public_reference': 'deal-42',
        'is_traveler': true,
        'is_sender': false,
        'state': 'delivered',
        'traveler_id': account.id,
        'sender_id': 99,
        'delivery_confirmed_at': '2026-09-01T12:00:00Z',
        'handover': {
          'is_pickup_confirmed': true,
          'is_delivery_confirmed': true,
          'delivery_confirmed_at': '2026-09-01T12:00:00Z',
          'can_reveal_delivery_code': false,
          'traveler_can_view_delivery_code': false,
        },
        'protection': {
          'protection_ends_at': '2026-09-03T12:00:00Z',
          'is_frozen': false,
        },
        'payout_summary': payoutMobileFixture(
          reference: 'po-delivery-42',
          dealId: 42,
          displayState: 'ready',
          amountEurCents: 4500,
        ),
      };

      backend.on('GET', '/api/deals/42', FakeResponse(200, dealJson));

      final store = FakeTokenStore();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
          sessionProvider.overrideWith(() => _FixedSession(account)),
        ],
      );
      await pumpRouted(
        tester,
        const DeliveryScreen(dealId: 42),
        container: container,
      );
      // Pump frame without hanging on periodic countdown timer
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 100));

      // Payout section rendered
      expect(find.text('Payout'), findsWidgets);
      expect(find.text('Payout ready'), findsOneWidget);
      expect(find.text('€45.00'), findsWidgets);
      expect(find.text('View payout'), findsOneWidget);
    });
  });

  group('Payout notifications and deep-linking', () {
    test('notification parsing and destinations for all payout states', () {
      final states = [
        ('eligible', 'po-ref-1'),
        ('processing', 'po-ref-2'),
        ('sent', 'po-ref-3'),
        ('paid', 'po-ref-4'),
        ('returned', 'po-ref-5'),
        ('needs_attention', 'po-ref-6'),
      ];

      for (final (event, ref) in states) {
        final notif = AppNotification.fromJson({
          'id': 1,
          'channel': 'payout.status_changed',
          'payload': {'event': event, 'payout_reference': ref, 'deal_id': 42},
        });

        expect(notif.channel, NotificationChannel.payoutStatusChanged);
        expect(notif.destination, isA<OpenPayoutDetail>());
        expect((notif.destination as OpenPayoutDetail).reference, ref);
      }
    });

    test('profile notification destinations map to payout methods', () {
      for (final profileEvent in ['profile_ready', 'profile_needs_attention']) {
        final notif = AppNotification.fromJson({
          'id': 2,
          'channel': 'payout.status_changed',
          'payload': {
            'event': profileEvent,
            'message_key': 'payout.$profileEvent',
          },
        });

        expect(notif.destination, isA<OpenPayoutMethods>());
      }
    });

    test(
      'deal fallback deep-link works where defined when payout_reference is absent',
      () {
        final notif = AppNotification.fromJson({
          'id': 3,
          'channel': 'payout.status_changed',
          'payload': {'deal_id': 42},
        });

        expect(notif.destination, isA<OpenDeal>());
        expect((notif.destination as OpenDeal).dealId, 42);
      },
    );

    test(
      'fallback to payout methods when neither reference, profile event nor deal is present',
      () {
        final notif = AppNotification.fromJson({
          'id': 4,
          'channel': 'payout.status_changed',
          'payload': const {},
        });

        expect(notif.destination, isA<OpenPayoutMethods>());
      },
    );

    test('pushLocation routes payout notifications correctly', () {
      // Payout reference deep-links to payout detail (even if deal_id is present)
      expect(
        pushLocation({
          'channel': 'payout.status_changed',
          'payout_reference': 'po-ref-detail',
          'deal_id': '42',
        }),
        '/payouts/po-ref-detail',
      );

      // Profile events deep-link to payout methods
      expect(
        pushLocation({
          'channel': 'payout.status_changed',
          'event': 'profile_ready',
        }),
        '/profile/payout-methods',
      );
      expect(
        pushLocation({
          'channel': 'payout.status_changed',
          'event': 'profile_needs_attention',
        }),
        '/profile/payout-methods',
      );

      // Deal fallback deep-link works when no payout_reference is present
      expect(
        pushLocation({'channel': 'payout.status_changed', 'deal_id': '42'}),
        '/deals/42',
      );

      // Generic fallback
      expect(
        pushLocation({'channel': 'payout.status_changed'}),
        '/profile/payouts',
      );
    });
  });

  group('Arabic RTL widget layout', () {
    testWidgets(
      'PayoutMethodsScreen renders cleanly in Arabic RTL without overflow',
      (tester) async {
        final backend = FakeBackend();
        backend.on(
          'GET',
          '/api/payouts/methods',
          FakeResponse(200, payoutMethodsFixture()),
        );

        await pumpRouted(
          tester,
          const PayoutMethodsScreen(),
          container: containerFor(backend),
          device: DeviceProfile.iphone,
          locale: const Locale('ar'),
        );
        await tester.pumpAndSettle();

        // RTL directionality verified
        expect(
          Directionality.of(tester.element(find.byType(PayoutMethodsScreen))),
          TextDirection.rtl,
        );

        // Arabic strings present in top part
        expect(find.text('وسائل التحويل'), findsOneWidget);
        expect(find.text('التحويلات باليورو (Stripe)'), findsOneWidget);

        // Scroll to reveal DZD card
        await tester.drag(find.byType(Scrollable).first, const Offset(0, -400));
        await tester.pumpAndSettle();

        expect(find.textContaining('التحويلات بالدينار'), findsOneWidget);
        expect(find.textContaining('بريدي موب'), findsWidgets);
        expect(find.text('•••• 1234'), findsOneWidget);
        expect(find.text('•••• 5678'), findsOneWidget);
      },
    );

    testWidgets(
      'PayoutDetailScreen renders cleanly in Arabic RTL with readable EUR and DZD',
      (tester) async {
        final backend = FakeBackend();
        backend.on(
          'GET',
          '/api/payouts/po-ref-123',
          FakeResponse(200, payoutMobileFixture()),
        );

        await pumpRouted(
          tester,
          const PayoutDetailScreen(reference: 'po-ref-123'),
          container: _payoutDetailContainer(backend),
          device: DeviceProfile.iphone,
          locale: const Locale('ar'),
        );
        await tester.pumpAndSettle();

        // RTL directionality verified
        expect(
          Directionality.of(tester.element(find.byType(PayoutDetailScreen))),
          TextDirection.rtl,
        );

        // EUR and DZD amounts readable
        expect(find.textContaining('45'), findsWidgets);
        expect(find.textContaining('700'), findsOneWidget);
        expect(find.text('po-ref-123'), findsWidgets);
      },
    );
  });
}
