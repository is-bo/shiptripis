/// Phase 8F-F1: the posting-deposit screen explains the server quote.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/features/requests/deposit_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

FakeBackend depositBackend() => FakeBackend()
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
        'clamped': '',
      },
    }),
  );

Future<L> pumpDeposit(
  WidgetTester tester,
  Locale locale, {
  DeviceProfile device = DeviceProfile.android,
}) async {
  await pumpApp(
    tester,
    const DepositScreen(requestId: 42),
    container: containerFor(depositBackend()),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(DepositScreen)));
}

void main() {
  for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
    testWidgets(
      'guidance renders all server amounts in ${locale.languageCode}',
      (tester) async {
        final l = await pumpDeposit(tester, locale);
        expect(find.text(l.depositGuidanceTitle), findsOneWidget);
        expect(find.text(l.depositSuggestedTotal), findsOneWidget);
        expect(find.text(l.depositRecommended), findsOneWidget);
        expect(find.text(l.depositMinimumAllowed), findsOneWidget);
        expect(
          tester.getTopLeft(find.text(l.depositSuggestedTotal)).dy,
          lessThan(tester.getTopLeft(find.text(l.depositRecommended)).dy),
        );
        expect(
          find.bySemanticsLabel(RegExp(RegExp.escape(l.depositGuidanceTitle))),
          findsWidgets,
        );
        await tester.scrollUntilVisible(
          find.text(l.depositPayAction),
          180,
          scrollable: find.byType(Scrollable).first,
        );
        final action = find.ancestor(
          of: find.text(l.depositPayAction),
          matching: find.byType(AppButton),
        );
        expect(
          tester.getSize(action.first).height,
          greaterThanOrEqualTo(AppSpace.minTapTarget),
        );
      },
    );
  }

  testWidgets('Arabic deposit guidance remains RTL', (tester) async {
    await pumpDeposit(tester, const Locale('ar'));
    expect(
      Directionality.of(tester.element(find.byType(DepositScreen))),
      TextDirection.rtl,
    );
  });

  testWidgets('large text guidance remains scrollable', (tester) async {
    await pumpDeposit(
      tester,
      const Locale('fr'),
      device: DeviceProfile.largeText,
    );
    expect(tester.takeException(), isNull);
    expect(find.byType(Scrollable), findsWidgets);
  });
}
