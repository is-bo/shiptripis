/// Money.
///
/// The product rule is that Flutter never computes an authoritative amount.
/// That is enforced by [Money] having no arithmetic operators at all, so the
/// first test here is a source-level assertion that they have not been added
/// back — the one change that would quietly re-open the door.
///
/// The rest covers the parsing the API actually requires: integer cents, a
/// zero-decimal dinar, and the few decimal-string fields, which must not go
/// through `double`.
library;

import 'dart:io';
import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/format/locale_formats.dart';
import 'package:shiptrip/core/money/money.dart';

void main() {
  setUpAll(LocaleFormats.ensureInitialized);

  group('no client-side arithmetic', () {
    test('Money defines no arithmetic operators', () {
      final source = File('lib/core/money/money.dart').readAsStringSync();
      for (final op in [
        'operator +',
        'operator -',
        'operator *',
        'operator /',
      ]) {
        expect(
          source,
          isNot(contains(op)),
          reason:
              'Money must stay operator-free: it is what makes "the client '
              'never computes money" a compile error rather than a review note',
        );
      }
    });
  });

  group('parsing', () {
    test('reads integer EUR cents', () {
      final money = Money.eurCentsOrNull(2750)!;
      expect(money.minorUnits, 2750);
      expect(money.currency, 'EUR');
      expect(money.exponent, 2);
    });

    test('refuses a non-integer cents value rather than rounding it', () {
      // A fractional cent means the contract changed. Guessing would put a
      // wrong number on a payment screen.
      expect(Money.eurCentsOrNull(27.5), isNull);
      expect(Money.eurCentsOrNull('2750'), isNull);
      expect(Money.eurCentsOrNull(null), isNull);
    });

    test('DZD is a zero-decimal currency', () {
      // Chargily charges whole dinars. Treating DZD as two-decimal would
      // inflate every converted amount by a hundred.
      expect(Money.defaultExponentFor('DZD'), 0);
      final dzd = Money.minorOrNull(40500, currency: 'DZD', exponent: 0)!;
      expect(dzd.minorUnits, 40500);
      expect(dzd.exponent, 0);
    });

    test('decimal strings parse exactly, not through a double', () {
      // `37.50` must never arrive as 3749 because of binary floating point.
      expect(Money.decimalStringOrNull('37.50')!.minorUnits, 3750);
      expect(Money.decimalStringOrNull('0.01')!.minorUnits, 1);
      expect(Money.decimalStringOrNull('1000000.00')!.minorUnits, 100000000);
      expect(Money.decimalStringOrNull('-12.34')!.minorUnits, -1234);
    });

    test('a malformed decimal string is null, never zero', () {
      // Zero is a lie about money; absent is the truth.
      expect(Money.decimalStringOrNull('twelve'), isNull);
      expect(Money.decimalStringOrNull(''), isNull);
      expect(Money.decimalStringOrNull('1,50'), isNull);
    });
  });

  group('formatting', () {
    test('renders in the viewer locale', () {
      final money = Money.eurCentsOrNull(2750)!;
      // Formatting differs per locale; what matters is that the digits and the
      // currency survive.
      for (final locale in [Locale('en'), Locale('fr'), Locale('ar')]) {
        final text = money.format(locale);
        expect(text, contains('27'));
        expect(text, contains('50'));
      }
    });

    test('the Maghreb gets Latin digits in Arabic', () {
      // `ar` alone renders Arabic-Indic numerals; `ar_DZ` does not, and the
      // corridor this product serves reads Latin digits.
      expect(LocaleFormats.intlTag(const Locale('ar')), 'ar_DZ');
      final text = Money.eurCentsOrNull(2750)!.format(const Locale('ar'));
      expect(RegExp('[0-9]').hasMatch(text), isTrue);
      expect(RegExp('[٠-٩]').hasMatch(text), isFalse);
    });
  });

  group('comparison', () {
    test('orders amounts of the same currency', () {
      final small = Money.eurCentsOrNull(100)!;
      final large = Money.eurCentsOrNull(500)!;
      expect(small.compareTo(large), lessThan(0));
      expect(large.compareTo(small), greaterThan(0));
      expect(small.compareTo(Money.eurCentsOrNull(100)!), 0);
    });

    test('zero and positive are distinguishable', () {
      expect(Money.zeroEur.isZero, isTrue);
      expect(Money.zeroEur.isPositive, isFalse);
      expect(Money.eurCentsOrNull(1)!.isPositive, isTrue);
    });
  });
}
