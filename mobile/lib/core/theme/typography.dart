import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'tokens.dart';

/// Display: Fraunces (variable serif, distinctive — opsz axis used for size-aware weight).
/// Body: DM Sans.
/// Mono: JetBrains Mono (used for codes, prices, ticker-like data).
class AppType {
  AppType._();

  static TextStyle display(double size, {Color? color, double? height, FontWeight w = FontWeight.w500}) =>
      GoogleFonts.fraunces(
        fontSize: size,
        fontWeight: w,
        color: color ?? AppColors.ink,
        letterSpacing: -size * 0.02,
        height: height ?? 1.02,
        fontFeatures: const [FontFeature.enable('opsz')],
      );

  static TextStyle body(double size, {Color? color, FontWeight w = FontWeight.w400, double? height}) =>
      GoogleFonts.dmSans(
        fontSize: size,
        fontWeight: w,
        color: color ?? AppColors.ink,
        height: height ?? 1.45,
      );

  static TextStyle mono(double size, {Color? color, FontWeight w = FontWeight.w500}) =>
      GoogleFonts.jetBrainsMono(
        fontSize: size,
        fontWeight: w,
        color: color ?? AppColors.ink,
        letterSpacing: 0.5,
      );

  static TextStyle eyebrow({Color? color}) => GoogleFonts.dmSans(
        fontSize: 11,
        fontWeight: FontWeight.w600,
        letterSpacing: 1.6,
        color: color ?? AppColors.inkMute,
      );
}
