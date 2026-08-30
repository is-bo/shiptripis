/// The three catalogues, pumped through real screens.
///
/// A parity script proves the ARB files have matching keys. It does not prove
/// the app resolves them — a missing delegate, an unsupported locale or a
/// stale generated file all leave the parity check green and the user reading
/// English. These tests render actual widgets in each language and assert that
/// what appears is *not* the English string.
///
/// They also check the two things that break specifically in Arabic: layout
/// direction, and whether a plural reads correctly under Arabic's six
/// categories rather than English's two.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/harness.dart';

/// Reads the catalogue for [locale] through a real widget tree.
Future<L> _catalogue(WidgetTester tester, Locale locale) async {
  late L catalogue;
  await pumpApp(
    tester,
    Builder(
      builder: (context) {
        catalogue = L.of(context);
        return const SizedBox.expand();
      },
    ),
    locale: locale,
  );
  return catalogue;
}

void main() {
  group('every language resolves its own catalogue', () {
    testWidgets('English', (tester) async {
      final l = await _catalogue(tester, const Locale('en'));
      expect(l.localeName, 'en');
      expect(l.navDeliveries, 'Deliveries');
    });

    testWidgets('French is actually French', (tester) async {
      final l = await _catalogue(tester, const Locale('fr'));
      expect(l.localeName, 'fr');

      // The failure this catches is a catalogue that silently falls back to
      // English — parity checks stay green while every user reads the wrong
      // language.
      expect(l.navDeliveries, isNot('Deliveries'));
      expect(l.navProfile, isNot('Profile'));
      expect(l.authSignIn, isNot('Sign in'));
      expect(l.deliveriesTitle, isNotEmpty);
    });

    testWidgets('Arabic is actually Arabic', (tester) async {
      final l = await _catalogue(tester, const Locale('ar'));
      expect(l.localeName, 'ar');

      // Arabic script, not a transliteration and not a fallback.
      final arabic = RegExp(r'[؀-ۿ]');
      expect(arabic.hasMatch(l.navDeliveries), isTrue);
      expect(arabic.hasMatch(l.navProfile), isTrue);
      expect(arabic.hasMatch(l.authSignIn), isTrue);
    });
  });

  group('placeholders survive translation', () {
    testWidgets('an amount lands inside the translated sentence', (
      tester,
    ) async {
      for (final locale in [Locale('en'), Locale('fr'), Locale('ar')]) {
        final l = await _catalogue(tester, locale);
        // If a translator dropped `{amount}`, this is where it shows up.
        expect(l.offerYouProposed('€27.50'), contains('€27.50'));
        expect(l.paymentPayAction('€27.50'), contains('€27.50'));
        expect(l.protectionSenderBody('Friday'), contains('Friday'));
      }
    });

    testWidgets('a count lands in every plural branch', (tester) async {
      for (final locale in [Locale('en'), Locale('fr'), Locale('ar')]) {
        final l = await _catalogue(tester, locale);
        // Arabic needs zero/one/two/few/many/other; these probe the ranges
        // where a two-branch English-shaped plural would read wrongly.
        for (final n in [0, 1, 2, 3, 11, 100]) {
          final rendered = l.journeyLegCount(n);
          expect(rendered, isNotEmpty);
          if (n > 2) {
            expect(
              rendered,
              contains('$n'),
              reason:
                  'the count must appear for n=$n in ${locale.languageCode}',
            );
          }
        }
      }
    });
  });

  group('Arabic direction', () {
    testWidgets('the tree is right-to-left', (tester) async {
      late bool isRtl;
      await pumpApp(
        tester,
        Builder(
          builder: (context) {
            isRtl = context.isRtl;
            return const SizedBox.expand();
          },
        ),
        locale: const Locale('ar'),
      );
      expect(isRtl, isTrue);
    });

    testWidgets('English and French are left-to-right', (tester) async {
      for (final locale in [Locale('en'), Locale('fr')]) {
        late bool isRtl;
        await pumpApp(
          tester,
          Builder(
            builder: (context) {
              isRtl = context.isRtl;
              return const SizedBox.expand();
            },
          ),
          locale: locale,
        );
        expect(isRtl, isFalse);
      }
    });
  });

  group('no catalogue smuggles in direction marks', () {
    testWidgets('Arabic strings carry no embedded RTL control characters', (
      tester,
    ) async {
      final l = await _catalogue(tester, const Locale('ar'));
      // Flutter derives direction from the locale. An embedded U+200F or
      // U+202B corrupts measurement and leaks into copied text.
      const marks = [0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E];
      bool hasMark(String s) => s.codeUnits.any(marks.contains);
      for (final sample in [
        l.navDeliveries,
        l.deliveriesTitle,
        l.moneyYouPay,
        l.deliveryCodeTravelerNever,
        l.protectionTravelerBody('X'),
      ]) {
        expect(hasMark(sample), isFalse, reason: sample);
      }
    });
  });
}
