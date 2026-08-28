/// ShipTrip design tokens.
///
/// Every colour, radius, space and duration the product uses lives here as a
/// *semantic* token — `surface`, `danger`, `moneyPositive` — never as a raw
/// hex at the call site. Screens read them through [AppTheme.of], which
/// resolves the active [ThemeData], so a widget cannot accidentally hard-code
/// a light-mode colour into a dark-mode build.
///
/// The palette keeps the Mediterranean/heritage character the product started
/// with — warm neutral ground, Algerian emerald, Saharan terracotta — but
/// re-tuned for a money-and-trust product: the ground is lifted so text
/// contrast clears WCAG AA, and terracotta/amber are reserved for states that
/// genuinely need attention rather than used as decoration.
library;

import 'package:flutter/material.dart';

// ---------------------------------------------------------------------------
// Raw ramps. Private on purpose: nothing outside this file may name a hex.
// ---------------------------------------------------------------------------

class _Ramp {
  const _Ramp._();

  // Warm neutral ground. Differentiates from the blue-white every fintech app
  // ships, while staying desaturated enough that money reads calmly on it.
  static const sand0 = Color(0xFFFDFBF7);
  static const sand1 = Color(0xFFF8F5EF);
  static const sand2 = Color(0xFFF1ECE2);
  static const sand3 = Color(0xFFE6DFD1);
  static const sand4 = Color(0xFFD5CCB9);

  // Sea ink — the text/structure ramp.
  static const ink0 = Color(0xFF0B1A24);
  static const ink1 = Color(0xFF152A38);
  static const ink2 = Color(0xFF2B4353);
  static const ink3 = Color(0xFF546A79);
  static const ink4 = Color(0xFF8496A2);
  static const ink5 = Color(0xFFB9C5CD);

  // Emerald — brand + primary action + "confirmed".
  static const emerald0 = Color(0xFF042F28);
  static const emerald1 = Color(0xFF0A4A40);
  static const emerald2 = Color(0xFF0E5A4F);
  static const emerald3 = Color(0xFF1C7A6B);
  static const emerald4 = Color(0xFF4FA697);
  static const emerald5 = Color(0xFFBFE0D9);
  static const emerald6 = Color(0xFFE6F2EF);

  // Terracotta — attention / action-required. Never decorative.
  static const clay0 = Color(0xFF6E2C0E);
  static const clay1 = Color(0xFF9B4318);
  static const clay2 = Color(0xFFC75E26);
  static const clay3 = Color(0xFFE8763A);
  static const clay4 = Color(0xFFF4B48D);
  static const clay5 = Color(0xFFFCEBE0);

  // Amber — waiting / in-progress / protection window.
  static const amber0 = Color(0xFF6B4A05);
  static const amber1 = Color(0xFF9A6D08);
  static const amber2 = Color(0xFFC98F10);
  static const amber3 = Color(0xFFE2AC2E);
  static const amber4 = Color(0xFFF6DFA4);
  static const amber5 = Color(0xFFFDF5E2);

  // Rust — failure / destructive.
  static const rust0 = Color(0xFF5C1A13);
  static const rust1 = Color(0xFF8C2B20);
  static const rust2 = Color(0xFFB23A2E);
  static const rust3 = Color(0xFFD35F52);
  static const rust4 = Color(0xFFF2BDB6);
  static const rust5 = Color(0xFFFCEDEB);

  // Lapis — informational, and the "flight" transport mode.
  static const lapis0 = Color(0xFF102A4C);
  static const lapis1 = Color(0xFF1B4477);
  static const lapis2 = Color(0xFF2A62A6);
  static const lapis3 = Color(0xFF5A8FCC);
  static const lapis4 = Color(0xFFB6D0EB);
  static const lapis5 = Color(0xFFEAF2FB);

  static const white = Color(0xFFFFFFFF);
  static const black = Color(0xFF000000);
}

// ---------------------------------------------------------------------------
// Semantic palette
// ---------------------------------------------------------------------------

/// The full semantic colour set for one brightness.
///
/// Screens never construct this — they read [AppTheme.of(context).colors].
@immutable
class AppColorScheme {
  const AppColorScheme({
    required this.brightness,
    required this.canvas,
    required this.surface,
    required this.surfaceRaised,
    required this.surfaceSunken,
    required this.surfaceInverse,
    required this.hairline,
    required this.hairlineStrong,
    required this.textPrimary,
    required this.textSecondary,
    required this.textTertiary,
    required this.textOnInverse,
    required this.brand,
    required this.brandStrong,
    required this.brandSoft,
    required this.onBrand,
    required this.success,
    required this.successSoft,
    required this.onSuccessSoft,
    required this.attention,
    required this.attentionSoft,
    required this.onAttentionSoft,
    required this.waiting,
    required this.waitingSoft,
    required this.onWaitingSoft,
    required this.danger,
    required this.dangerSoft,
    required this.onDangerSoft,
    required this.info,
    required this.infoSoft,
    required this.onInfoSoft,
    required this.neutralSoft,
    required this.onNeutralSoft,
    required this.focus,
    required this.scrim,
    required this.skeleton,
    required this.skeletonSheen,
    required this.modeFlight,
    required this.modeDrive,
  });

  final Brightness brightness;

  /// App background behind every scaffold.
  final Color canvas;

  /// Default card / sheet / bar fill.
  final Color surface;

  /// A card that must read as lifted off [surface].
  final Color surfaceRaised;

  /// Grouped/inset regions — form groups, code wells, summary blocks.
  final Color surfaceSunken;

  /// High-contrast fill used for the money summary and other "this is the
  /// authoritative number" surfaces.
  final Color surfaceInverse;

  final Color hairline;
  final Color hairlineStrong;

  final Color textPrimary;
  final Color textSecondary;
  final Color textTertiary;
  final Color textOnInverse;

  final Color brand;
  final Color brandStrong;
  final Color brandSoft;
  final Color onBrand;

  /// Terminal-good states: delivered, paid, approved, completed.
  final Color success;
  final Color successSoft;
  final Color onSuccessSoft;

  /// The user must do something: payment required, KYC action, proof rejected.
  final Color attention;
  final Color attentionSoft;
  final Color onAttentionSoft;

  /// Time is passing and nobody is blocked: processing, protection window,
  /// awaiting the counterparty.
  final Color waiting;
  final Color waitingSoft;
  final Color onWaitingSoft;

  /// Failed, cancelled, refunded-against, destructive.
  final Color danger;
  final Color dangerSoft;
  final Color onDangerSoft;

  final Color info;
  final Color infoSoft;
  final Color onInfoSoft;

  /// Inert chips: history, draft, expired.
  final Color neutralSoft;
  final Color onNeutralSoft;

  final Color focus;
  final Color scrim;
  final Color skeleton;
  final Color skeletonSheen;

  final Color modeFlight;
  final Color modeDrive;

  static const light = AppColorScheme(
    brightness: Brightness.light,
    canvas: _Ramp.sand1,
    surface: _Ramp.white,
    surfaceRaised: _Ramp.white,
    surfaceSunken: _Ramp.sand2,
    surfaceInverse: _Ramp.ink0,
    hairline: Color(0x14152A38),
    hairlineStrong: Color(0x33152A38),
    textPrimary: _Ramp.ink0,
    textSecondary: _Ramp.ink2,
    textTertiary: _Ramp.ink3,
    textOnInverse: _Ramp.sand0,
    brand: _Ramp.emerald2,
    brandStrong: _Ramp.emerald1,
    brandSoft: _Ramp.emerald6,
    onBrand: _Ramp.white,
    success: _Ramp.emerald2,
    successSoft: _Ramp.emerald6,
    onSuccessSoft: _Ramp.emerald0,
    attention: _Ramp.clay2,
    attentionSoft: _Ramp.clay5,
    onAttentionSoft: _Ramp.clay0,
    waiting: _Ramp.amber1,
    waitingSoft: _Ramp.amber5,
    onWaitingSoft: _Ramp.amber0,
    danger: _Ramp.rust2,
    dangerSoft: _Ramp.rust5,
    onDangerSoft: _Ramp.rust0,
    info: _Ramp.lapis2,
    infoSoft: _Ramp.lapis5,
    onInfoSoft: _Ramp.lapis0,
    neutralSoft: _Ramp.sand2,
    onNeutralSoft: _Ramp.ink2,
    focus: _Ramp.lapis2,
    scrim: Color(0x800B1A24),
    skeleton: _Ramp.sand2,
    skeletonSheen: _Ramp.sand0,
    modeFlight: _Ramp.lapis2,
    modeDrive: _Ramp.emerald3,
  );

  static const dark = AppColorScheme(
    brightness: Brightness.dark,
    canvas: Color(0xFF091620),
    surface: Color(0xFF11212C),
    surfaceRaised: Color(0xFF172A37),
    surfaceSunken: Color(0xFF0D1B25),
    surfaceInverse: _Ramp.sand1,
    hairline: Color(0x1FFFFFFF),
    hairlineStrong: Color(0x3DFFFFFF),
    textPrimary: Color(0xFFF2EEE6),
    textSecondary: Color(0xFFC2CDD5),
    textTertiary: _Ramp.ink4,
    textOnInverse: _Ramp.ink0,
    brand: _Ramp.emerald4,
    brandStrong: Color(0xFF6FBFB1),
    brandSoft: Color(0xFF0E332C),
    onBrand: Color(0xFF032420),
    success: _Ramp.emerald4,
    successSoft: Color(0xFF0E332C),
    onSuccessSoft: Color(0xFFA9DACF),
    attention: _Ramp.clay3,
    attentionSoft: Color(0xFF3A1E0E),
    onAttentionSoft: _Ramp.clay4,
    waiting: _Ramp.amber3,
    waitingSoft: Color(0xFF352706),
    onWaitingSoft: _Ramp.amber4,
    danger: _Ramp.rust3,
    dangerSoft: Color(0xFF361310),
    onDangerSoft: _Ramp.rust4,
    info: _Ramp.lapis3,
    infoSoft: Color(0xFF10243B),
    onInfoSoft: _Ramp.lapis4,
    neutralSoft: Color(0xFF1B2C38),
    onNeutralSoft: Color(0xFFC2CDD5),
    focus: _Ramp.lapis3,
    scrim: Color(0xB3000000),
    skeleton: Color(0xFF1A2A36),
    skeletonSheen: Color(0xFF233746),
    modeFlight: _Ramp.lapis3,
    modeDrive: _Ramp.emerald4,
  );

  AppColorScheme lerpTo(AppColorScheme other, double t) {
    Color c(Color a, Color b) => Color.lerp(a, b, t)!;
    return AppColorScheme(
      brightness: t < 0.5 ? brightness : other.brightness,
      canvas: c(canvas, other.canvas),
      surface: c(surface, other.surface),
      surfaceRaised: c(surfaceRaised, other.surfaceRaised),
      surfaceSunken: c(surfaceSunken, other.surfaceSunken),
      surfaceInverse: c(surfaceInverse, other.surfaceInverse),
      hairline: c(hairline, other.hairline),
      hairlineStrong: c(hairlineStrong, other.hairlineStrong),
      textPrimary: c(textPrimary, other.textPrimary),
      textSecondary: c(textSecondary, other.textSecondary),
      textTertiary: c(textTertiary, other.textTertiary),
      textOnInverse: c(textOnInverse, other.textOnInverse),
      brand: c(brand, other.brand),
      brandStrong: c(brandStrong, other.brandStrong),
      brandSoft: c(brandSoft, other.brandSoft),
      onBrand: c(onBrand, other.onBrand),
      success: c(success, other.success),
      successSoft: c(successSoft, other.successSoft),
      onSuccessSoft: c(onSuccessSoft, other.onSuccessSoft),
      attention: c(attention, other.attention),
      attentionSoft: c(attentionSoft, other.attentionSoft),
      onAttentionSoft: c(onAttentionSoft, other.onAttentionSoft),
      waiting: c(waiting, other.waiting),
      waitingSoft: c(waitingSoft, other.waitingSoft),
      onWaitingSoft: c(onWaitingSoft, other.onWaitingSoft),
      danger: c(danger, other.danger),
      dangerSoft: c(dangerSoft, other.dangerSoft),
      onDangerSoft: c(onDangerSoft, other.onDangerSoft),
      info: c(info, other.info),
      infoSoft: c(infoSoft, other.infoSoft),
      onInfoSoft: c(onInfoSoft, other.onInfoSoft),
      neutralSoft: c(neutralSoft, other.neutralSoft),
      onNeutralSoft: c(onNeutralSoft, other.onNeutralSoft),
      focus: c(focus, other.focus),
      scrim: c(scrim, other.scrim),
      skeleton: c(skeleton, other.skeleton),
      skeletonSheen: c(skeletonSheen, other.skeletonSheen),
      modeFlight: c(modeFlight, other.modeFlight),
      modeDrive: c(modeDrive, other.modeDrive),
    );
  }
}

// ---------------------------------------------------------------------------
// Space, radius, elevation, motion
// ---------------------------------------------------------------------------

/// 4pt spacing scale. Names are sizes, not positions, so they survive layout
/// changes: `AppSpace.md` stays correct when a row becomes a column.
abstract final class AppSpace {
  static const xxs = 2.0;
  static const xs = 4.0;
  static const sm = 8.0;
  static const md = 12.0;
  static const lg = 16.0;
  static const xl = 20.0;
  static const xxl = 24.0;
  static const x3l = 32.0;
  static const x4l = 40.0;
  static const x5l = 48.0;
  static const x6l = 64.0;

  /// Horizontal page gutter. One value, used by every screen, so nothing
  /// drifts a few pixels out of alignment with the screen next to it.
  static const gutter = 20.0;

  /// Minimum tappable size (WCAG 2.5.5 / Material). Enforced by AppTapTarget.
  static const minTapTarget = 48.0;
}

abstract final class AppRadius {
  static const xs = 6.0;
  static const sm = 10.0;
  static const md = 14.0;
  static const lg = 20.0;
  static const xl = 28.0;
  static const pill = 999.0;

  static const rXs = BorderRadius.all(Radius.circular(xs));
  static const rSm = BorderRadius.all(Radius.circular(sm));
  static const rMd = BorderRadius.all(Radius.circular(md));
  static const rLg = BorderRadius.all(Radius.circular(lg));
  static const rXl = BorderRadius.all(Radius.circular(xl));
  static const rPill = BorderRadius.all(Radius.circular(pill));
}

/// Shadows are brightness-dependent: a dark theme separates surfaces with
/// lightness, not with black shadow, so the dark set is deliberately flatter.
@immutable
class AppElevation {
  const AppElevation({
    required this.card,
    required this.raised,
    required this.overlay,
    required this.navBar,
  });

  final List<BoxShadow> card;
  final List<BoxShadow> raised;
  final List<BoxShadow> overlay;
  final List<BoxShadow> navBar;

  static const light = AppElevation(
    card: [
      BoxShadow(color: Color(0x0D0B1A24), blurRadius: 16, offset: Offset(0, 4)),
    ],
    raised: [
      BoxShadow(color: Color(0x140B1A24), blurRadius: 28, offset: Offset(0, 10)),
      BoxShadow(color: Color(0x0A0B1A24), blurRadius: 6, offset: Offset(0, 2)),
    ],
    overlay: [
      BoxShadow(color: Color(0x260B1A24), blurRadius: 48, offset: Offset(0, 20)),
    ],
    navBar: [
      BoxShadow(color: Color(0x0F0B1A24), blurRadius: 20, offset: Offset(0, -6)),
    ],
  );

  static const dark = AppElevation(
    card: [
      BoxShadow(color: Color(0x40000000), blurRadius: 14, offset: Offset(0, 3)),
    ],
    raised: [
      BoxShadow(color: Color(0x59000000), blurRadius: 24, offset: Offset(0, 8)),
    ],
    overlay: [
      BoxShadow(color: Color(0x80000000), blurRadius: 44, offset: Offset(0, 18)),
    ],
    navBar: [
      BoxShadow(color: Color(0x4D000000), blurRadius: 18, offset: Offset(0, -6)),
    ],
  );
}

/// Motion. Durations are short by default because this app is used one-handed
/// on a phone while standing at a door handing over a parcel.
abstract final class AppMotion {
  static const instant = Duration(milliseconds: 90);
  static const fast = Duration(milliseconds: 160);
  static const normal = Duration(milliseconds: 260);
  static const slow = Duration(milliseconds: 420);

  /// Expressive ease-out. Everything that enters uses this.
  static const enter = Cubic(0.16, 1, 0.3, 1);

  /// Symmetric ease for things that move in place.
  static const standard = Curves.easeInOutCubic;

  /// Honour the platform "reduce motion" setting. Callers pass their intended
  /// duration and get [Duration.zero] back when animation is disabled, which
  /// keeps every animated widget correct without a per-widget branch.
  static Duration respecting(BuildContext context, Duration d) =>
      MediaQuery.disableAnimationsOf(context) ? Duration.zero : d;
}

// ---------------------------------------------------------------------------
// ThemeExtension wiring
// ---------------------------------------------------------------------------

/// Carries the semantic tokens through [ThemeData] so `AppTheme.of(context)`
/// always returns the set matching the brightness actually being rendered.
@immutable
class AppTheme extends ThemeExtension<AppTheme> {
  const AppTheme({required this.colors, required this.elevation});

  final AppColorScheme colors;
  final AppElevation elevation;

  static const lightExtension = AppTheme(
    colors: AppColorScheme.light,
    elevation: AppElevation.light,
  );
  static const darkExtension = AppTheme(
    colors: AppColorScheme.dark,
    elevation: AppElevation.dark,
  );

  /// Falls back to the light set rather than throwing: a widget rendered in a
  /// bare `MaterialApp` inside a test should still lay out.
  static AppTheme of(BuildContext context) =>
      Theme.of(context).extension<AppTheme>() ?? lightExtension;

  @override
  AppTheme copyWith({AppColorScheme? colors, AppElevation? elevation}) =>
      AppTheme(
        colors: colors ?? this.colors,
        elevation: elevation ?? this.elevation,
      );

  @override
  AppTheme lerp(covariant ThemeExtension<AppTheme>? other, double t) {
    if (other is! AppTheme) return this;
    return AppTheme(
      colors: colors.lerpTo(other.colors, t),
      // Shadow lists are swapped rather than interpolated; blending two
      // different-length lists produces artefacts and nobody perceives a
      // 260ms shadow cross-fade anyway.
      elevation: t < 0.5 ? elevation : other.elevation,
    );
  }
}

/// Shorthand so screens read `context.colors.brand` instead of
/// `AppTheme.of(context).colors.brand` twenty times per build method.
extension AppThemeContext on BuildContext {
  AppColorScheme get colors => AppTheme.of(this).colors;
  AppElevation get elevation => AppTheme.of(this).elevation;

  /// True when the active locale renders right-to-left. Used by the few
  /// widgets that must mirror something Flutter cannot mirror for them, such
  /// as a hand-painted route timeline.
  bool get isRtl => Directionality.of(this) == TextDirection.rtl;
}
