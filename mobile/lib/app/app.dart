import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../design/theme.dart';
import '../l10n/app_localizations.dart';
import '../core/push/push_coordinator.dart';
import 'app_settings.dart';
import 'router.dart';

class ShipTripApp extends ConsumerWidget {
  const ShipTripApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final locale = ref.watch(localeProvider);
    final themeMode = ref.watch(themeModeProvider);
    final router = ref.watch(routerProvider);
    ref.watch(pushCoordinatorProvider);

    // The theme is locale-dependent: Arabic swaps the whole type stack rather
    // than falling back glyph-by-glyph, so it has to be rebuilt when the
    // language changes.
    final Locale resolved = locale ?? ref.watch(effectiveLocaleProvider);

    return MaterialApp.router(
      title: 'ShipTrip',
      debugShowCheckedModeBanner: false,
      routerConfig: router,

      locale: locale,
      supportedLocales: supportedLocales,
      localizationsDelegates: const [
        L.delegate,
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],

      theme: buildAppTheme(brightness: Brightness.light, locale: resolved),
      darkTheme: buildAppTheme(brightness: Brightness.dark, locale: resolved),
      themeMode: themeMode,

      builder: (context, child) {
        // Text scale is honoured, but capped. Above ~1.6 a lifecycle timeline
        // or a money breakdown stops fitting on a small phone at all; below
        // that everything in the design system is built to reflow. The cap is
        // generous enough to satisfy the accessibility requirement while
        // keeping payment screens legible.
        final media = MediaQuery.of(context);
        return MediaQuery(
          data: media.copyWith(
            textScaler: media.textScaler.clamp(
              minScaleFactor: 0.85,
              maxScaleFactor: 1.6,
            ),
          ),
          child: child ?? const SizedBox.shrink(),
        );
      },
    );
  }
}
