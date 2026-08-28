/// Money.
///
/// ## The important part
///
/// [Money] has **no arithmetic**. No `+`, no `-`, no `*`, no percentage
/// helper. That is not an oversight — it is the mechanism that enforces the
/// product invariant that the server owns every authoritative amount.
///
/// A breakdown like
///
/// ```
/// Traveler receives    €30.00
/// ShipTrip fee          €7.50
/// You pay              €37.50
/// ```
///
/// is three server values rendered side by side, never two values and a sum.
/// If a screen needs a total that the API does not return, that is an API gap
/// to report, not a subtraction to write in Dart. Making the operator absent
/// means the compiler catches the mistake instead of a reviewer having to.
///
/// ## Representation
///
/// Amounts are integer **minor units** with an explicit exponent, matching the
/// backend: EUR is cents (exponent 2), DZD is whole dinars (exponent 0). No
/// double ever holds a monetary value.
library;

import 'dart:ui' show Locale;

import 'package:flutter/foundation.dart' show immutable;
import 'package:intl/intl.dart';

import '../format/locale_formats.dart';

@immutable
class Money implements Comparable<Money> {
  const Money._(this.minorUnits, this.currency, this.exponent);

  /// The canonical marketplace currency. Every price, reward, fee, deposit,
  /// refund and payout obligation in the product is EUR.
  factory Money.eurCents(int cents) => Money._(cents, 'EUR', 2);

  /// A provider settlement amount — currently only Chargily's DZD. The
  /// exponent comes from the API (`provider_amount_exponent`) rather than
  /// being assumed, because DZD is quoted in whole dinars while EUR is not.
  factory Money.minor(int minorUnits, String currency, int exponent) =>
      Money._(minorUnits, currency.toUpperCase(), exponent);

  static const zeroEur = Money._(0, 'EUR', 2);

  /// Amount in the smallest unit of [currency]. Integer, always.
  final int minorUnits;

  final String currency;

  /// Decimal places [currency] uses. 2 for EUR, 0 for DZD.
  final int exponent;

  bool get isZero => minorUnits == 0;
  bool get isPositive => minorUnits > 0;

  // -------------------------------------------------------------------------
  // Parsing
  // -------------------------------------------------------------------------

  /// Reads an integer-cent EUR field such as `amount_eur_cents`.
  ///
  /// Returns null for a missing or non-integer value rather than throwing: a
  /// screen that loses one optional amount should render without it, not
  /// crash the tab.
  static Money? eurCentsOrNull(Object? raw) {
    if (raw is int) return Money.eurCents(raw);
    if (raw is num && raw == raw.roundToDouble()) {
      return Money.eurCents(raw.toInt());
    }
    return null;
  }

  /// Reads an integer minor-unit field carrying its own currency, such as the
  /// Deal terms block (`traveler_reward_minor` + `currency`).
  static Money? minorOrNull(
    Object? raw, {
    required String? currency,
    int? exponent,
  }) {
    if (raw is! int) return null;
    final code = (currency ?? 'EUR').toUpperCase();
    return Money.minor(raw, code, exponent ?? defaultExponentFor(code));
  }

  /// Reads one of the few decimal-string money fields the API still uses
  /// (`payment_amount`, `payout_amount`).
  ///
  /// Parsed through [BigInt] on the digit string rather than through
  /// [double], so `"37.50"` can never arrive as `3749`.
  static Money? decimalStringOrNull(Object? raw, {String currency = 'EUR'}) {
    if (raw is int) {
      return Money.minor(raw, currency, defaultExponentFor(currency));
    }
    if (raw is! String) return null;
    final text = raw.trim();
    if (text.isEmpty) return null;

    final match = RegExp(r'^([+-]?)(\d+)(?:\.(\d*))?$').firstMatch(text);
    if (match == null) return null;

    final code = currency.toUpperCase();
    final exp = defaultExponentFor(code);
    final sign = match.group(1) == '-' ? -1 : 1;
    final whole = match.group(2)!;
    final fractionRaw = match.group(3) ?? '';

    // Pad or truncate the fraction to the currency's exponent. Truncation
    // only ever discards digits the currency cannot express.
    final fraction = fractionRaw.length >= exp
        ? fractionRaw.substring(0, exp)
        : fractionRaw.padRight(exp, '0');

    final combined = BigInt.tryParse('$whole$fraction');
    if (combined == null || !combined.isValidInt) return null;
    return Money.minor(sign * combined.toInt(), code, exp);
  }

  /// ISO 4217 minor-unit exponents for the currencies this product touches.
  /// DZD is a zero-decimal currency; treating it as 2 would inflate every
  /// Chargily amount by a hundred.
  static int defaultExponentFor(String currency) =>
      switch (currency.toUpperCase()) {
        'DZD' => 0,
        'JPY' || 'KRW' || 'XOF' || 'XAF' => 0,
        _ => 2,
      };

  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  /// The amount as a decimal, for formatting only.
  ///
  /// Deliberately private-ish in intent: it exists so [NumberFormat] can be
  /// handed a number. Do not route business logic through it.
  double get _asDecimal => minorUnits / _scale;

  int get _scale {
    var s = 1;
    for (var i = 0; i < exponent; i++) {
      s *= 10;
    }
    return s;
  }

  /// Locale-aware money string — `€37.50`, `37,50 €`, `37,50 €` in Arabic
  /// with Latin digits (see [LocaleFormats] for why Algeria gets Latin
  /// numerals rather than Arabic-Indic ones).
  String format(Locale locale, {bool showCurrency = true}) {
    final tag = LocaleFormats.intlTag(locale);
    final fmt = showCurrency
        ? NumberFormat.currency(
            locale: tag,
            name: currency,
            symbol: symbolFor(currency),
            decimalDigits: exponent,
          )
        : NumberFormat.decimalPatternDigits(
            locale: tag,
            decimalDigits: exponent,
          );
    return fmt.format(_asDecimal);
  }

  /// Same as [format] but never abbreviates and never drops the minor units,
  /// for the places a user is checking an exact figure against a bank
  /// statement.
  String formatExact(Locale locale) => format(locale);

  static String symbolFor(String currency) => switch (currency.toUpperCase()) {
    'EUR' => '€',
    'DZD' => 'DA',
    _ => currency.toUpperCase(),
  };

  @override
  int compareTo(Money other) {
    assert(
      other.currency == currency,
      'Refusing to compare $currency with ${other.currency}. Cross-currency '
      'comparison needs a server-supplied rate, which the client never holds.',
    );
    return minorUnits.compareTo(other.minorUnits);
  }

  @override
  bool operator ==(Object other) =>
      other is Money &&
      other.minorUnits == minorUnits &&
      other.currency == currency &&
      other.exponent == exponent;

  @override
  int get hashCode => Object.hash(minorUnits, currency, exponent);

  /// Debug only. Never shown to a user — it is not localized.
  @override
  String toString() => '$currency ${_asDecimal.toStringAsFixed(exponent)}';
}
