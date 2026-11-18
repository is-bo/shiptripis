/// Locale-aware formatting for the things this product shows constantly:
/// money, dates, relative times and countdowns.
///
/// ## Why Arabic here uses Latin digits
///
/// `intl`'s bare `ar` locale renders Arabic-Indic numerals (٠١٢٣٤). Those are
/// standard in the Mashriq — Egypt, the Gulf — but **not** in the Maghreb.
/// Algeria, Morocco and Tunisia use Western digits in everyday life, on price
/// tags, on invoices and on bank statements. Rendering `٣٧٫٥٠` to an Algerian
/// sender would look foreign, not localized.
///
/// So the app's ARB locale stays `ar` (one translation file), while every
/// number and date goes through `ar_DZ`, which `intl` already defines with
/// Latin numerals and the Algerian month names (جانفي, فيفري ... أوت), never
/// the Mashriq ones (يناير, أغسطس). [intlTag] is the single place that
/// mapping lives, and [materialDelegate] hands the same formats to Flutter's
/// own widgets: the date and time pickers and `MaterialLocalizations`.
library;

import 'package:flutter/foundation.dart' show SynchronousFuture;
import 'package:flutter/material.dart'
    show MaterialLocalizations, TimeOfDayFormat;
import 'package:flutter/widgets.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:intl/date_symbol_data_custom.dart';
import 'package:intl/date_symbol_data_local.dart' show dateTimeSymbolMap;
import 'package:intl/date_time_patterns.dart';
import 'package:intl/intl.dart';

abstract final class LocaleFormats {
  /// Loads the date symbol data for every locale the app ships. Must complete
  /// before the first `DateFormat` call; `main` awaits it.
  static Future<void> ensureInitialized() async => _loadDateData();

  /// Adds `en`, `fr` and `ar_DZ` to `intl`'s date data. Synchronous, and safe
  /// to repeat: it adds to whatever Flutter has already registered instead of
  /// depending on which of the two ran first.
  static void _loadDateData() {
    final symbols = dateTimeSymbolMap();
    final patterns = dateTimePatternMap();
    for (final tag in const ['en', 'fr', 'ar_DZ']) {
      initializeDateFormattingCustom(
        locale: tag,
        symbols: symbols[tag],
        patterns: patterns[tag],
      );
    }
  }

  /// The tag handed to `intl`, which is not always the tag used for
  /// translations. See the note at the top of this file.
  static String intlTag(Locale locale) => switch (locale.languageCode) {
    'ar' => 'ar_DZ',
    'fr' => 'fr_FR',
    _ => 'en',
  };

  /// Registered in place of `GlobalMaterialLocalizations.delegate`. Flutter
  /// would format Arabic through the bare `ar` locale, so the date picker,
  /// the time picker and `MaterialLocalizations.formatFullDate` would show
  /// Arabic-Indic digits and أغسطس.
  static const LocalizationsDelegate<MaterialLocalizations> materialDelegate =
      _MaterialDelegate();

  // -------------------------------------------------------------------------
  // Dates and times
  // -------------------------------------------------------------------------

  /// `14 Mar` / `14 mars` — for a row where the year is obvious.
  static String dayMonth(Locale locale, DateTime when) =>
      DateFormat.MMMd(intlTag(locale)).format(when.toLocal());

  /// `November 2026` / `novembre 2026` — for "member since", where the day is
  /// deliberately not shown.
  static String monthYear(Locale locale, DateTime when) =>
      DateFormat.yMMMM(intlTag(locale)).format(when);

  /// `14 March 2026`
  static String fullDate(Locale locale, DateTime when) =>
      DateFormat.yMMMMd(intlTag(locale)).format(when.toLocal());

  /// `09:40`. Always the locale's own clock convention — a French user gets
  /// 24-hour, an English one may get 12-hour.
  static String time(Locale locale, DateTime when) =>
      DateFormat.Hm(intlTag(locale)).format(when.toLocal());

  /// `14 Mar, 09:40` — the default for a timestamp inside a lifecycle event.
  static String dateTime(Locale locale, DateTime when) =>
      '${dayMonth(locale, when)}${_comma(locale)}${time(locale, when)}';

  /// `14 March 2026 at 09:40` — for a deadline the user is being asked to
  /// rely on, where an abbreviated month is not reassuring enough.
  static String preciseDateTime(Locale locale, DateTime when) =>
      DateFormat.yMMMMd(intlTag(locale)).add_Hm().format(when.toLocal());

  /// Arabic writes its own comma (،) between a date and a time.
  static String _comma(Locale locale) =>
      locale.languageCode == 'ar' ? '، ' : ', ';

  /// A date range across one or two days, e.g. a pickup window.
  static String range(Locale locale, DateTime from, DateTime to) {
    final sameDay =
        from.toLocal().year == to.toLocal().year &&
        from.toLocal().month == to.toLocal().month &&
        from.toLocal().day == to.toLocal().day;
    if (sameDay) {
      return '${dayMonth(locale, from)}${_comma(locale)}'
          '${time(locale, from)}–${time(locale, to)}';
    }
    return '${dateTime(locale, from)} – ${dateTime(locale, to)}';
  }
}

class _MaterialDelegate extends LocalizationsDelegate<MaterialLocalizations> {
  const _MaterialDelegate();

  @override
  bool isSupported(Locale locale) =>
      GlobalMaterialLocalizations.delegate.isSupported(locale);

  @override
  Future<MaterialLocalizations> load(Locale locale) {
    if (locale.languageCode != 'ar') {
      return GlobalMaterialLocalizations.delegate.load(locale);
    }
    LocaleFormats._loadDateData();
    final tag = LocaleFormats.intlTag(locale);
    return SynchronousFuture(
      _AlgerianMaterialLocalizations(
        localeName: tag,
        fullYearFormat: DateFormat.y(tag),
        compactDateFormat: DateFormat.yMd(tag),
        shortDateFormat: DateFormat.yMMMd(tag),
        mediumDateFormat: DateFormat.MMMEd(tag),
        longDateFormat: DateFormat.yMMMMEEEEd(tag),
        yearMonthFormat: DateFormat.yMMMM(tag),
        shortMonthDayFormat: DateFormat.MMMd(tag),
        decimalFormat: NumberFormat.decimalPattern(tag),
        twoDigitZeroPaddedFormat: NumberFormat('00', tag),
      ),
    );
  }

  @override
  bool shouldReload(_MaterialDelegate old) => false;
}

/// Flutter's Arabic strings with the app's clock: 24-hour, like every time
/// [LocaleFormats.time] prints, rather than a 12-hour dial with ص and م.
class _AlgerianMaterialLocalizations extends MaterialLocalizationAr {
  const _AlgerianMaterialLocalizations({
    required super.localeName,
    required super.fullYearFormat,
    required super.compactDateFormat,
    required super.shortDateFormat,
    required super.mediumDateFormat,
    required super.longDateFormat,
    required super.yearMonthFormat,
    required super.shortMonthDayFormat,
    required super.decimalFormat,
    required super.twoDigitZeroPaddedFormat,
  });

  @override
  TimeOfDayFormat timeOfDayFormat({bool alwaysUse24HourFormat = false}) =>
      TimeOfDayFormat.HH_colon_mm;
}

/// A countdown broken into parts, so the UI can render each unit in its own
/// localized noun rather than interpolating an English `"2h 14m"`.
///
/// Always computed from a **server-supplied absolute instant**, never from a
/// client-side start time plus a duration. That is what keeps a countdown
/// honest after the phone has been asleep for six hours.
@immutable
class CountdownParts {
  const CountdownParts({
    required this.days,
    required this.hours,
    required this.minutes,
    required this.seconds,
    required this.hasElapsed,
  });

  factory CountdownParts.until(DateTime target, {DateTime? now}) {
    final remaining = target.difference(now ?? DateTime.now());
    if (remaining.isNegative || remaining == Duration.zero) {
      return const CountdownParts(
        days: 0,
        hours: 0,
        minutes: 0,
        seconds: 0,
        hasElapsed: true,
      );
    }
    return CountdownParts(
      days: remaining.inDays,
      hours: remaining.inHours % 24,
      minutes: remaining.inMinutes % 60,
      seconds: remaining.inSeconds % 60,
      hasElapsed: false,
    );
  }

  final int days;
  final int hours;
  final int minutes;
  final int seconds;
  final bool hasElapsed;

  /// How often the UI needs to rebuild to stay truthful. A 47-hour protection
  /// window does not need a one-second timer waking the device.
  Duration get tickInterval {
    if (hasElapsed) return const Duration(days: 1);
    if (days > 0 || hours > 0) return const Duration(minutes: 1);
    return const Duration(seconds: 1);
  }
}
