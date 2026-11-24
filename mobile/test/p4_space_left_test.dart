/// P4: a trip card and its preview sheet show the real kilos left.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';

Future<void> _open(
  WidgetTester tester, {
  required int? kg,
  Locale locale = const Locale('en'),
}) async {
  final backend = discoveryBackend()
    ..on(
      'GET',
      '/api/discovery/trips',
      discoveryPage([
        {...tripCardFixture(11, name: 'Nadia'), 'free_weight_kg': kg},
      ]),
    );
  await pumpDiscovery(
    tester,
    const BrowseTripsScreen(),
    backend,
    locale: locale,
  );
}

Future<void> _openSheet(WidgetTester tester) async {
  await tester.tap(find.text('Nadia'));
  await tester.pumpAndSettle();
}

void main() {
  group('Space left on the trip card and the preview sheet', () {
    testWidgets('English: "14 kg left" on the card, "14 kg" beside the label', (
      tester,
    ) async {
      await _open(tester, kg: 14);
      expect(find.text('14 kg left'), findsOneWidget);

      await _openSheet(tester);
      expect(find.text('Space left'), findsOneWidget);
      expect(find.text('14 kg'), findsOneWidget);
      expect(find.text('14 kg left'), findsOneWidget, reason: 'only the card');
    });

    testWidgets('English: under one kilo reads "Less than 1 kg left"', (
      tester,
    ) async {
      await _open(tester, kg: 0);
      expect(find.text('Less than 1 kg left'), findsOneWidget);

      await _openSheet(tester);
      expect(find.text('Less than 1 kg'), findsOneWidget);
      expect(find.text('0 kg left'), findsNothing);
    });

    testWidgets('French, without a repeated "left"', (tester) async {
      await _open(tester, kg: 14, locale: const Locale('fr'));
      expect(find.text('Il reste 14 kg'), findsOneWidget);

      await _openSheet(tester);
      expect(find.text('Place disponible'), findsOneWidget);
      expect(find.text('14 kg'), findsOneWidget);
    });

    testWidgets('Arabic in Modern Standard Arabic, one kilo', (tester) async {
      await _open(tester, kg: 1, locale: const Locale('ar'));
      expect(find.text('المساحة المتبقية: 1 كغ'), findsOneWidget);

      await _openSheet(tester);
      expect(find.text('1 كغ'), findsOneWidget);
    });

    testWidgets('Arabic under one kilo', (tester) async {
      await _open(tester, kg: 0, locale: const Locale('ar'));
      expect(find.text('المساحة المتبقية: أقل من 1 كغ'), findsOneWidget);

      await _openSheet(tester);
      expect(find.text('أقل من 1 كغ'), findsOneWidget);
    });

    testWidgets('a card with no figure shows no space line', (tester) async {
      await _open(tester, kg: null);

      expect(find.textContaining('kg'), findsNothing);
      await _openSheet(tester);
      expect(find.text('Space left'), findsNothing);
    });
  });
}
