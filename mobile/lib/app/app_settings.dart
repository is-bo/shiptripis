/// Device-level app settings: language and appearance.
///
/// Both are stored, both default to following the device, and both apply
/// without a restart.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/session/session.dart';

/// The languages ShipTrip ships. All three are launch languages, not
/// afterthoughts: French and Arabic are the corridor's own languages and
/// English is the fallback.
const supportedLocales = <Locale>[Locale('en'), Locale('fr'), Locale('ar')];

/// `null` means "follow the device".
final localeProvider = NotifierProvider<LocaleController, Locale?>(
  LocaleController.new,
);

class LocaleController extends Notifier<Locale?> {
  @override
  Locale? build() {
    unawaited(_hydrate());
    return null;
  }

  Future<void> _hydrate() async {
    final tag = await ref.read(tokenStoreProvider).readLocale();
    if (tag == null || tag.isEmpty) return;
    final match = supportedLocales
        .where((l) => l.languageCode == tag)
        .firstOrNull;
    if (match != null) state = match;
  }

  /// Pass null to go back to following the device.
  void set(Locale? locale) {
    state = locale;
    unawaited(ref.read(tokenStoreProvider).writeLocale(locale?.languageCode));
  }
}

final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(
  ThemeModeController.new,
);

class ThemeModeController extends Notifier<ThemeMode> {
  /// Light, not `system`.
  ///
  /// ShipTrip is a parchment app. The whole identity — the paper ground, the
  /// grain, the stamps, the ink — is a light-mode design, and the original
  /// build shipped no dark theme at all. Following the device meant that
  /// every user with dark mode switched on opened a dark navy app that looks
  /// nothing like the product, without ever choosing it.
  ///
  /// The dark theme still exists and is still complete; it is now something
  /// a user opts into from Profile → Appearance rather than something the
  /// operating system decides on their behalf.
  @override
  ThemeMode build() => ThemeMode.light;

  void set(ThemeMode mode) => state = mode;
}

/// Resolves the locale actually in force, for the code that formats money and
/// dates and cannot ask the widget tree.
///
/// `Localizations.localeOf` is the right answer inside a build method; this is
/// for controllers and repositories, which have no context.
final effectiveLocaleProvider = Provider<Locale>((ref) {
  final chosen = ref.watch(localeProvider);
  if (chosen != null) return chosen;

  final device = WidgetsBinding.instance.platformDispatcher.locales;
  for (final candidate in device) {
    final match = supportedLocales
        .where((l) => l.languageCode == candidate.languageCode)
        .firstOrNull;
    if (match != null) return match;
  }
  return const Locale('en');
});

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull {
    final it = iterator;
    return it.moveNext() ? it.current : null;
  }
}
