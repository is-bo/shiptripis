/// Device-level app settings: language and appearance.
///
/// Both are stored, both default to following the device, and both apply
/// without a restart.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/format/locale_formats.dart';
import '../core/session/session.dart';
import '../l10n/app_localizations.dart';

/// The languages ShipTrip ships. All three are launch languages, not
/// afterthoughts: French and Arabic are the corridor's own languages and
/// English is the fallback.
const supportedLocales = <Locale>[Locale('en'), Locale('fr'), Locale('ar')];

/// The app's strings plus Flutter's own, with Material formatting dates and
/// numbers the way the rest of the app does (see [LocaleFormats]).
const appLocalizationsDelegates = <LocalizationsDelegate<Object>>[
  L.delegate,
  LocaleFormats.materialDelegate,
  GlobalWidgetsLocalizations.delegate,
  GlobalCupertinoLocalizations.delegate,
];

/// The phone's language and appearance. They belong to the device, not to a
/// member: `main()` creates them once, outside every member's container, so
/// the screens after a sign-out show the same language and theme.
class DeviceSettings {
  /// `null` means "follow the device".
  Locale? locale;

  /// Whether the stored language has been read into [locale], or a choice
  /// made since has overtaken that read.
  bool localeRead = false;

  ThemeMode themeMode = ThemeMode.light;
}

/// The one [DeviceSettings]. `main()` passes its own into every member's
/// container; a container built without it (a test) has its own.
final deviceSettingsProvider = Provider<DeviceSettings>(
  (ref) => DeviceSettings(),
);

/// `null` means "follow the device".
final localeProvider = NotifierProvider<LocaleController, Locale?>(
  LocaleController.new,
);

class LocaleController extends Notifier<Locale?> {
  DeviceSettings get _settings => ref.read(deviceSettingsProvider);

  @override
  Locale? build() {
    if (!_settings.localeRead) unawaited(_hydrate());
    return _settings.locale;
  }

  Future<void> _hydrate() async {
    final tag = await ref.read(tokenStoreProvider).readLocale();
    if (!ref.mounted || _settings.localeRead) return;
    _settings.localeRead = true;
    if (tag == null || tag.isEmpty) return;
    final match = supportedLocales
        .where((l) => l.languageCode == tag)
        .firstOrNull;
    if (match != null) state = _settings.locale = match;
  }

  /// Pass null to go back to following the device.
  void set(Locale? locale) {
    _settings.localeRead = true;
    state = _settings.locale = locale;
    unawaited(ref.read(tokenStoreProvider).writeLocale(locale?.languageCode));
  }
}

final themeModeProvider = NotifierProvider<ThemeModeController, ThemeMode>(
  ThemeModeController.new,
);

class ThemeModeController extends Notifier<ThemeMode> {
  /// Light, not `system`, until the person chooses.
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
  ThemeMode build() => ref.read(deviceSettingsProvider).themeMode;

  void set(ThemeMode mode) =>
      state = ref.read(deviceSettingsProvider).themeMode = mode;
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
