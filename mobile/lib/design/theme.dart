/// Builds the Material [ThemeData] the app runs on.
///
/// Two things happen here that matter:
///
/// 1. The semantic tokens are mapped onto Material's own `ColorScheme` roles,
///    so stock Material widgets — snackbars, dialogs, switches, chips, date
///    pickers — come out in the product's colours without being restyled one
///    at a time. Anything not restyled below still looks like ShipTrip.
/// 2. [AppTheme] is registered as a theme extension, so the semantic tokens
///    travel with brightness. A widget reading `context.colors.attention`
///    gets the light or dark terracotta automatically.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'tokens.dart';
import 'typography.dart';

ThemeData buildAppTheme({
  required Brightness brightness,
  required Locale locale,
}) {
  final isDark = brightness == Brightness.dark;
  final c = isDark ? AppColorScheme.dark : AppColorScheme.light;
  final ext = isDark ? AppTheme.darkExtension : AppTheme.lightExtension;
  final text = AppTypography.textTheme(locale: locale, onSurface: c.textPrimary);

  final scheme = ColorScheme(
    brightness: brightness,
    primary: c.brand,
    onPrimary: c.onBrand,
    primaryContainer: c.brandSoft,
    onPrimaryContainer: c.onSuccessSoft,
    secondary: c.attention,
    onSecondary: isDark ? const Color(0xFF2A1206) : Colors.white,
    secondaryContainer: c.attentionSoft,
    onSecondaryContainer: c.onAttentionSoft,
    tertiary: c.info,
    onTertiary: Colors.white,
    tertiaryContainer: c.infoSoft,
    onTertiaryContainer: c.onInfoSoft,
    error: c.danger,
    onError: Colors.white,
    errorContainer: c.dangerSoft,
    onErrorContainer: c.onDangerSoft,
    surface: c.surface,
    onSurface: c.textPrimary,
    surfaceContainerLowest: c.surface,
    surfaceContainerLow: c.canvas,
    surfaceContainer: c.surfaceSunken,
    surfaceContainerHigh: c.surfaceSunken,
    surfaceContainerHighest: c.surfaceSunken,
    onSurfaceVariant: c.textSecondary,
    outline: c.hairlineStrong,
    outlineVariant: c.hairline,
    inverseSurface: c.surfaceInverse,
    onInverseSurface: c.textOnInverse,
    inversePrimary: isDark ? AppColorScheme.light.brand : AppColorScheme.dark.brand,
    scrim: c.scrim,
    shadow: Colors.black,
  );

  return ThemeData(
    useMaterial3: true,
    brightness: brightness,
    colorScheme: scheme,
    scaffoldBackgroundColor: c.canvas,
    canvasColor: c.canvas,
    extensions: [ext],
    textTheme: text,
    primaryTextTheme: text,
    splashFactory: InkSparkle.splashFactory,

    // Material's default is a tinted overlay that shifts every card a little
    // toward primary as it elevates. The palette here already separates
    // surfaces deliberately, so the automatic tint only muddies it.
    applyElevationOverlayColor: false,

    appBarTheme: AppBarTheme(
      backgroundColor: c.canvas,
      foregroundColor: c.textPrimary,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      scrolledUnderElevation: 0,
      centerTitle: false,
      titleTextStyle: text.headlineSmall,
      systemOverlayStyle: isDark
          ? SystemUiOverlayStyle.light.copyWith(
              statusBarColor: Colors.transparent,
              systemNavigationBarColor: Colors.transparent,
            )
          : SystemUiOverlayStyle.dark.copyWith(
              statusBarColor: Colors.transparent,
              systemNavigationBarColor: Colors.transparent,
            ),
    ),

    dividerTheme: DividerThemeData(
      color: c.hairline,
      thickness: 1,
      space: 1,
    ),

    cardTheme: CardThemeData(
      color: c.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: const RoundedRectangleBorder(borderRadius: AppRadius.rLg),
    ),

    // Transient feedback. Floating so it clears the navigation bar; the shell
    // additionally lifts it above the bar via `AppSnack`.
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: c.surfaceInverse,
      contentTextStyle: text.bodyMedium?.copyWith(color: c.textOnInverse),
      actionTextColor: isDark ? AppColorScheme.light.brand : c.brandStrong,
      shape: const RoundedRectangleBorder(borderRadius: AppRadius.rMd),
      insetPadding: const EdgeInsets.symmetric(
        horizontal: AppSpace.lg,
        vertical: AppSpace.sm,
      ),
      elevation: 0,
    ),

    dialogTheme: DialogThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      shape: const RoundedRectangleBorder(borderRadius: AppRadius.rXl),
      titleTextStyle: text.titleLarge,
      contentTextStyle: text.bodyMedium?.copyWith(color: c.textSecondary),
    ),

    bottomSheetTheme: BottomSheetThemeData(
      backgroundColor: c.surface,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      showDragHandle: true,
      dragHandleColor: c.hairlineStrong,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(AppRadius.xl)),
      ),
      clipBehavior: Clip.antiAlias,
    ),

    // Fields are drawn on the sunken surface with no fill-on-focus flicker;
    // focus is carried by the border and by the focus ring, both of which stay
    // visible for keyboard users.
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: c.surfaceSunken,
      hintStyle: text.bodyMedium?.copyWith(color: c.textTertiary),
      labelStyle: text.bodyMedium?.copyWith(color: c.textSecondary),
      floatingLabelStyle: text.labelMedium?.copyWith(color: c.brand),
      errorStyle: text.bodySmall?.copyWith(color: c.danger),
      helperStyle: text.bodySmall?.copyWith(color: c.textTertiary),
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppSpace.lg,
        vertical: AppSpace.lg,
      ),
      border: const OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide.none,
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide(color: c.hairline),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide(color: c.brand, width: 2),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide(color: c.danger),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide(color: c.danger, width: 2),
      ),
      disabledBorder: OutlineInputBorder(
        borderRadius: AppRadius.rMd,
        borderSide: BorderSide(color: c.hairline),
      ),
    ),

    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: c.brand,
        foregroundColor: c.onBrand,
        disabledBackgroundColor: c.neutralSoft,
        disabledForegroundColor: c.textTertiary,
        minimumSize: const Size(0, AppSpace.minTapTarget + 4),
        padding: const EdgeInsets.symmetric(horizontal: AppSpace.xxl),
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.rMd),
        textStyle: text.labelLarge,
        elevation: 0,
      ),
    ),

    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: c.textPrimary,
        disabledForegroundColor: c.textTertiary,
        side: BorderSide(color: c.hairlineStrong),
        minimumSize: const Size(0, AppSpace.minTapTarget + 4),
        padding: const EdgeInsets.symmetric(horizontal: AppSpace.xxl),
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.rMd),
        textStyle: text.labelLarge,
      ),
    ),

    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        foregroundColor: c.brandStrong,
        disabledForegroundColor: c.textTertiary,
        minimumSize: const Size(0, AppSpace.minTapTarget),
        padding: const EdgeInsets.symmetric(horizontal: AppSpace.md),
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.rSm),
        textStyle: text.labelLarge,
      ),
    ),

    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        foregroundColor: c.textSecondary,
        minimumSize: const Size.square(AppSpace.minTapTarget),
        shape: const RoundedRectangleBorder(borderRadius: AppRadius.rSm),
      ),
    ),

    iconTheme: IconThemeData(color: c.textSecondary, size: 22),

    chipTheme: ChipThemeData(
      backgroundColor: c.surfaceSunken,
      selectedColor: c.brandSoft,
      disabledColor: c.neutralSoft,
      side: BorderSide(color: c.hairline),
      labelStyle: text.labelMedium!,
      secondaryLabelStyle: text.labelMedium!,
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpace.md,
        vertical: AppSpace.sm,
      ),
      shape: const RoundedRectangleBorder(borderRadius: AppRadius.rPill),
      showCheckmark: false,
    ),

    listTileTheme: ListTileThemeData(
      iconColor: c.textSecondary,
      textColor: c.textPrimary,
      titleTextStyle: text.titleSmall,
      subtitleTextStyle: text.bodySmall?.copyWith(color: c.textSecondary),
      minVerticalPadding: AppSpace.md,
      shape: const RoundedRectangleBorder(borderRadius: AppRadius.rMd),
    ),

    switchTheme: SwitchThemeData(
      thumbColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? c.onBrand : c.surface,
      ),
      trackColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? c.brand : c.neutralSoft,
      ),
      trackOutlineColor: WidgetStateProperty.resolveWith(
        (s) => s.contains(WidgetState.selected) ? c.brand : c.hairlineStrong,
      ),
    ),

    progressIndicatorTheme: ProgressIndicatorThemeData(
      color: c.brand,
      linearTrackColor: c.neutralSoft,
      circularTrackColor: c.neutralSoft,
      linearMinHeight: 4,
    ),

    tabBarTheme: TabBarThemeData(
      labelColor: c.textPrimary,
      unselectedLabelColor: c.textTertiary,
      labelStyle: text.labelLarge,
      unselectedLabelStyle: text.labelLarge,
      indicatorColor: c.brand,
      indicatorSize: TabBarIndicatorSize.label,
      dividerColor: c.hairline,
      overlayColor: WidgetStatePropertyAll(c.brandSoft.withValues(alpha: 0.5)),
    ),

    tooltipTheme: TooltipThemeData(
      decoration: BoxDecoration(
        color: c.surfaceInverse,
        borderRadius: AppRadius.rSm,
      ),
      textStyle: text.bodySmall?.copyWith(color: c.textOnInverse),
      padding: const EdgeInsets.symmetric(
        horizontal: AppSpace.md,
        vertical: AppSpace.sm,
      ),
    ),

    // A visible focus ring is the difference between "keyboard accessible" and
    // "keyboard accessible on paper".
    focusColor: c.focus.withValues(alpha: 0.14),
    highlightColor: c.brandSoft.withValues(alpha: 0.4),

    pageTransitionsTheme: const PageTransitionsTheme(
      builders: {
        // Cupertino on iOS keeps the left-edge back gesture alive, which is
        // muscle memory an Android-flavoured transition would silently break.
        TargetPlatform.iOS: CupertinoPageTransitionsBuilder(),
        TargetPlatform.macOS: CupertinoPageTransitionsBuilder(),
        TargetPlatform.android: PredictiveBackPageTransitionsBuilder(),
      },
    ),
  );
}
