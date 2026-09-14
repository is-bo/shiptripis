import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/features/profile/payout_methods_screen.dart';

import 'phase8fh6b_payout_screens_test.dart' show payoutMethodsFixture;
import 'support/fake_api.dart';
import 'support/harness.dart';

void main() {
  testWidgets(
    'J1 deadline refreshes once and stops when detail is unobserved',
    (tester) async {
      final now = DateTime.utc(2026, 9, 14);
      var reads = 0;
      var expired = false;
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..handle('GET', '/api/deals/7', (_) {
          reads++;
          return FakeResponse(200, {
            ...dealFixture(status: 'protection_window'),
            'server_time':
                (!expired ? now : now.add(const Duration(seconds: 4)))
                    .toIso8601String(),
            'protection_ends_at': now
                .add(const Duration(seconds: 2))
                .toIso8601String(),
            'available_actions': !expired ? ['open_dispute'] : <String>[],
          });
        });
      final container = containerFor(backend);
      await pumpApp(
        tester,
        Consumer(
          builder: (context, ref, _) {
            final deal = ref.watch(dealDetailProvider(7)).value;
            return Text(
              deal?.availableActions.contains('open_dispute') == true
                  ? 'can dispute'
                  : 'closed',
            );
          },
        ),
        container: container,
      );
      await tester.pumpAndSettle();
      expect(find.text('can dispute'), findsOneWidget);
      final initialReads = reads;
      expired = true;
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();
      expect(find.text('closed'), findsOneWidget);
      expect(reads, initialReads + 1);
      await tester.pumpWidget(const SizedBox());
      await tester.pump(const Duration(days: 2));
      expect(reads, initialReads + 1);
    },
  );

  testWidgets('J1 first EUR preference requires an explicit supported country', (
    tester,
  ) async {
    final initial = payoutMethodsFixture(eurState: 'not_configured');
    initial['preference'] = null;
    initial['eur'] = Map<String, dynamic>.from(initial['eur'] as Map)
      ..['country'] = null;
    initial['eur']['supported_countries'] = ['FR'];
    initial['revisions'] = {'EUR': 0, 'DZD': 0};
    final backend = FakeBackend()
      ..on('GET', '/api/payouts/methods', FakeResponse(200, initial))
      ..on(
        'PATCH',
        '/api/payouts/methods',
        FakeResponse(200, payoutMethodsFixture(preference: 'eur_only')),
      );
    await pumpRouted(
      tester,
      const PayoutMethodsScreen(),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('EUR only'));
    // The pending action's spinner remains animated behind the country dialog.
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(SimpleDialog), findsOneWidget);
    expect(backend.to('PATCH', '/api/payouts/methods'), isEmpty);
    await tester.tap(find.text('France'));
    await tester.pumpAndSettle();
    final request = backend.to('PATCH', '/api/payouts/methods').single;
    expect(request.body['country'], 'FR');
    expect(request.body['eur_revision'], 0);
    expect(request.body['preference'], 'eur_only');
  });

  test('J1 onboarding and refresh decode nested method mobile state', () async {
    final mobile = payoutMethodsFixture()['eur'];
    final backend = FakeBackend()
      ..on(
        'POST',
        '/api/payouts/methods/stripe/onboarding',
        FakeResponse(200, {
          'onboarding_url': 'https://connect.stripe.com/setup/synthetic',
          'method': {'currency': 'EUR', 'mobile': mobile},
        }),
      )
      ..on(
        'POST',
        '/api/payouts/methods/stripe/refresh',
        FakeResponse(200, {
          'method': {'currency': 'EUR', 'mobile': mobile},
        }),
      );
    final container = containerFor(backend);
    addTearDown(container.dispose);
    final repo = container.read(paymentRepositoryProvider);
    final setup = await repo.startStripeOnboarding(country: 'FR');
    expect(setup.onboardingUrl, contains('connect.stripe.com'));
    expect(setup.method?.ready, isTrue);
    expect((await repo.refreshStripeReadiness())?.ready, isTrue);
  });
}
