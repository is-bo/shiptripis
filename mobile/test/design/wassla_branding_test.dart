import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/identity.dart';
import 'package:shiptrip/design/theme.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

double contrast(Color a, Color b) {
  final first = a.computeLuminance();
  final second = b.computeLuminance();
  return (first > second
      ? (first + .05) / (second + .05)
      : (second + .05) / (first + .05));
}

void main() {
  test(
    'brand fills and readable ink are independent of success and accents',
    () {
      for (final c in [AppColorScheme.light, AppColorScheme.dark]) {
        expect(c.brand, const Color(0xFF042D49));
        expect(c.accent, const Color(0xFFFBBC04));
        expect(c.attentionVivid, const Color(0xFFE8763A));
        expect(contrast(c.brand, c.onBrand), greaterThanOrEqualTo(4.5));
        expect(contrast(c.brandInk, c.canvas), greaterThanOrEqualTo(4.5));
        expect(contrast(c.brandStrong, c.brandSoft), greaterThanOrEqualTo(4.5));
        expect(c.brand, isNot(c.success));
      }
      expect(AppColorScheme.light.success, const Color(0xFF0E5A4F));
      expect(AppColorScheme.dark.success, const Color(0xFF4FA697));
      expect(AppColorScheme.light.canvas, const Color(0xFFF4EFE6));
      expect(AppColorScheme.dark.canvas, const Color(0xFF091620));
    },
  );

  for (final locale in L.supportedLocales) {
    test('Wassla is named consistently in ${locale.languageCode}', () async {
      final strings = await L.delegate.load(locale);
      expect(strings.appName, 'Wassla');
    });
  }

  for (final brightness in Brightness.values) {
    testWidgets('supplied logo stays proportional in $brightness', (
      tester,
    ) async {
      final semantics = tester.ensureSemantics();

      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(
            brightness: brightness,
            locale: const Locale('en'),
          ),
          home: const Scaffold(body: Center(child: ShipTripMark(size: 40))),
        ),
      );
      await tester.pumpAndSettle();
      final logo = tester.widget<Image>(find.byType(Image));
      final path = (logo.image as AssetImage).assetName;
      expect(path, contains(brightness == Brightness.dark ? 'ivory' : 'navy'));
      expect(logo.fit, BoxFit.contain);
      final size = tester.getSize(find.byType(Image));
      expect(size.width / size.height, closeTo(1360 / 346, .001));
      expect(find.bySemanticsLabel('Wassla'), findsOneWidget);
      expect(tester.takeException(), isNull);
      semantics.dispose();
    });
  }
}
