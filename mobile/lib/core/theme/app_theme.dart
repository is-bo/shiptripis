import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';
import 'tokens.dart';

ThemeData buildAppTheme() {
  final base = ThemeData.light(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: AppColors.parchment,
    colorScheme: const ColorScheme.light(
      primary: AppColors.emerald,
      onPrimary: AppColors.parchmentSoft,
      secondary: AppColors.terracotta,
      onSecondary: Colors.white,
      surface: AppColors.parchmentSoft,
      onSurface: AppColors.ink,
      error: AppColors.danger,
      onError: Colors.white,
    ),
    textTheme: GoogleFonts.dmSansTextTheme(base.textTheme).apply(
      bodyColor: AppColors.ink,
      displayColor: AppColors.ink,
    ),
    splashFactory: InkSparkle.splashFactory,
    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        TargetPlatform.android: ZoomPageTransitionsBuilder(),
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
      },
    ),
  );
}
