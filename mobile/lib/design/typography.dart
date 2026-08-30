/// Type scale.
///
/// Sizes map to Material's type-scale roles rather than being chosen per
/// screen, so a title on Deliveries is the same title on Profile and the OS
/// font-size setting scales the whole app coherently.
///
/// Four bundled variable faces:
///
/// * **Fraunces** — display and headline roles, and the single hero money
///   figure. Rationed on purpose: a serif on every label reads boutique, not
///   trustworthy.
/// * **DM Sans** — every other Latin role.
/// * **Noto Sans Arabic** — every role under an Arabic locale. Fraunces has no
///   Arabic coverage, so Arabic display text takes Noto's heaviest weight
///   instead of falling back glyph-by-glyph to whatever the OS has.
/// * **JetBrains Mono** — handover codes and reference strings, where a human
///   reads digits aloud and `0` must not look like `O`.
///
/// Weight is applied as a variable-font axis *and* as `fontWeight`. The axis
/// picks the real instance; `fontWeight` keeps Flutter from synthesising a
/// fake bold on top of it and keeps fallback faces in step.
library;

import 'package:flutter/material.dart';

abstract final class AppFonts {
  static const display = 'Fraunces';
  static const sans = 'DMSans';
  static const arabic = 'NotoSansArabic';
  static const mono = 'JetBrainsMono';

  /// Latin-first stack. Arabic is still listed so a French string containing
  /// an Arabic place name renders in a designed face rather than a system
  /// substitute.
  static const latinStack = <String>[sans, arabic];

  /// Arabic-first stack, with DM Sans behind it for Latin runs inside Arabic
  /// copy — flight numbers, IATA codes, `€`, brand names.
  static const arabicStack = <String>[arabic, sans];
}

/// Digits that line up in a column. Applied to every money and countdown
/// value; without it `€9.00` and `€19.00` set at different widths and a
/// payment breakdown stops reading as a column of numbers.
const _tabular = <FontFeature>[
  FontFeature.tabularFigures(),
  FontFeature.slashedZero(),
];

List<FontVariation> _wght(double w) => [FontVariation('wght', w)];

/// Fraunces exposes an optical-size axis. Matching it to the rendered size is
/// the whole point of the face: at 34pt the letterforms tighten and the
/// contrast opens up, at 18pt they stay sturdy.
List<FontVariation> _fraunces(double w, double opticalSize) => [
  FontVariation('wght', w),
  FontVariation('opsz', opticalSize.clamp(9, 144)),
  // Wonk gives Fraunces its cocked ear and descenders. It is the reason this
  // face was chosen over any other serif, so it stays on where the face is
  // actually visible as display type.
  const FontVariation('WONK', 1),
  const FontVariation('SOFT', 0),
];

abstract final class AppTypography {
  /// The full Material [TextTheme] for a locale.
  ///
  /// Arabic swaps every family rather than relying on per-glyph fallback:
  /// mixing DM Sans metrics with a fallback Arabic face produces inconsistent
  /// line heights down a list, which is exactly the "translated, not
  /// localized" tell this rebuild is meant to remove.
  static TextTheme textTheme({
    required Locale locale,
    required Color onSurface,
  }) {
    final isArabic = locale.languageCode == 'ar';
    final ui = isArabic ? AppFonts.arabic : AppFonts.sans;
    final uiStack = isArabic ? AppFonts.arabicStack : AppFonts.latinStack;
    final displayFamily = isArabic ? AppFonts.arabic : AppFonts.display;

    TextStyle disp(double size, double weight, double height) => TextStyle(
      fontFamily: displayFamily,
      fontFamilyFallback: uiStack,
      fontSize: size,
      height: height,
      color: onSurface,
      fontWeight: _materialWeight(weight),
      fontVariations: isArabic ? _wght(weight) : _fraunces(weight, size),
      // A serif at display size needs its tracking pulled in; Arabic never
      // takes negative tracking, which would collide the joins.
      letterSpacing: isArabic ? 0 : -size * 0.018,
    );

    TextStyle text(
      double size,
      double weight,
      double height, {
      double tracking = 0,
    }) => TextStyle(
      fontFamily: ui,
      fontFamilyFallback: uiStack,
      fontSize: size,
      height: height,
      color: onSurface,
      fontWeight: _materialWeight(weight),
      fontVariations: _wght(weight),
      letterSpacing: isArabic ? 0 : tracking,
    );

    return TextTheme(
      // Reserved for the one number or word a screen is actually about.
      displayLarge: disp(40, 600, 1.06),
      displayMedium: disp(34, 600, 1.08),
      displaySmall: disp(28, 600, 1.12),

      // Screen titles.
      headlineLarge: disp(26, 600, 1.16),
      headlineMedium: disp(22, 600, 1.2),
      headlineSmall: disp(19, 600, 1.24),

      // Section and card headers inside a screen.
      titleLarge: text(19, 650, 1.28, tracking: -0.2),
      titleMedium: text(16, 650, 1.32, tracking: -0.1),
      titleSmall: text(14, 650, 1.36),

      bodyLarge: text(16, 400, 1.5),
      bodyMedium: text(14.5, 400, 1.5),
      bodySmall: text(13, 400, 1.45),

      // Buttons, chips, field labels, tab labels.
      labelLarge: text(15, 650, 1.2, tracking: 0.1),
      labelMedium: text(13, 600, 1.25, tracking: 0.15),
      labelSmall: text(11.5, 600, 1.3, tracking: 0.2),
    );
  }

  /// The hero money figure — the single amount a payment screen is about.
  /// Serif, because this is where the brand voice earns its place.
  static TextStyle heroMoney(BuildContext context, {Color? color}) {
    final base = Theme.of(context).textTheme.displayMedium!;
    final isArabic = Directionality.of(context) == TextDirection.rtl;
    return base.copyWith(
      color: color ?? base.color,
      fontFeatures: _tabular,
      // Arabic keeps the sans face here; Fraunces has no Arabic glyphs and a
      // mixed-face amount looks broken.
      fontFamily: isArabic ? AppFonts.arabic : AppFonts.display,
    );
  }

  /// Money inside a breakdown, list row or table. Sans with tabular figures,
  /// so a column of amounts reads as a column.
  static TextStyle money(
    BuildContext context, {
    Color? color,
    double size = 15,
    double weight = 650,
  }) => TextStyle(
    fontFamily: Directionality.of(context) == TextDirection.rtl
        ? AppFonts.arabic
        : AppFonts.sans,
    fontFamilyFallback: AppFonts.latinStack,
    fontSize: size,
    height: 1.3,
    color: color ?? Theme.of(context).textTheme.bodyMedium?.color,
    fontWeight: _materialWeight(weight),
    fontVariations: _wght(weight),
    fontFeatures: _tabular,
  );

  /// A countdown or duration. Tabular so the digits do not jitter as the
  /// clock ticks — a countdown that reflows every second is unreadable.
  static TextStyle timer(
    BuildContext context, {
    Color? color,
    double size = 15,
  }) => money(context, color: color, size: size, weight: 600);

  /// Handover codes and provider references. Always LTR: a delivery code is a
  /// machine token, and mirroring it in Arabic would change what the user
  /// reads aloud.
  static TextStyle code({
    required Color color,
    double size = 30,
    double weight = 600,
  }) => TextStyle(
    fontFamily: AppFonts.mono,
    fontSize: size,
    height: 1.2,
    color: color,
    fontWeight: _materialWeight(weight),
    fontVariations: _wght(weight),
    fontFeatures: _tabular,
    letterSpacing: size * 0.14,
  );

  /// The eyebrow — a small, wide-tracked, upper-case label sitting above a
  /// display headline. It is one of the two or three things that make a
  /// ShipTrip screen recognisable from across a room, so it is a real type
  /// role rather than a `copyWith` that each screen re-invents.
  ///
  /// Arabic takes no tracking and is not upper-cased: Arabic script has no
  /// case, and letter-spacing breaks the joins between characters.
  static TextStyle eyebrow(BuildContext context, {Color? color}) {
    final isArabic = Directionality.of(context) == TextDirection.rtl;
    return TextStyle(
      fontFamily: isArabic ? AppFonts.arabic : AppFonts.sans,
      fontFamilyFallback: isArabic ? AppFonts.arabicStack : AppFonts.latinStack,
      fontSize: isArabic ? 12 : 11,
      height: 1.3,
      color: color ?? Theme.of(context).textTheme.bodySmall?.color,
      fontWeight: _materialWeight(600),
      fontVariations: _wght(600),
      letterSpacing: isArabic ? 0 : 1.6,
    );
  }

  /// The text inside a passport stamp. Same idea as [eyebrow], one notch
  /// heavier and wider, because it is being read through a dashed border.
  static TextStyle stamp(BuildContext context, {required Color color}) {
    final isArabic = Directionality.of(context) == TextDirection.rtl;
    return eyebrow(context, color: color).copyWith(
      fontWeight: _materialWeight(700),
      fontVariations: _wght(700),
      letterSpacing: isArabic ? 0 : 1.8,
    );
  }

  /// Small monospaced data — an IATA code, a duration, a reference under a
  /// route. Distinct from [code], which is the large handover-code face.
  static TextStyle monoLabel(
    BuildContext context, {
    Color? color,
    double size = 11,
    double weight = 600,
    double tracking = 1.2,
  }) => TextStyle(
    fontFamily: AppFonts.mono,
    fontSize: size,
    height: 1.3,
    color: color ?? Theme.of(context).textTheme.bodySmall?.color,
    fontWeight: _materialWeight(weight),
    fontVariations: _wght(weight),
    fontFeatures: _tabular,
    letterSpacing: tracking,
  );

  /// Variable `wght` is continuous; [FontWeight] is not. Round to the nearest
  /// hundred so Flutter's fallback selection and any synthesised face agree
  /// with the axis instead of fighting it.
  static FontWeight _materialWeight(double w) {
    final index = ((w / 100).round() - 1).clamp(0, 8);
    return FontWeight.values[index];
  }
}
