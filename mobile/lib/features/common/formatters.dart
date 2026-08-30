/// Formatting of server-supplied numbers.
///
/// Everything here is **presentation only**. It turns a value the server sent
/// into a string in the user's locale — it never combines two values, never
/// rounds a price, and never decides anything. A distance band prints the
/// bounds the server published; it does not print a midpoint, because the
/// midpoint is precisely the thing the band exists to withhold.
library;

import 'package:flutter/widgets.dart';
import 'package:intl/intl.dart';

import '../../core/format/locale_formats.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';

/// `3.5 kg`, `12 kg` — trailing zeros dropped, locale decimal separator.
String formatWeight(BuildContext context, double? kg) {
  if (kg == null) return '';
  final locale = Localizations.localeOf(context);
  final tag = LocaleFormats.intlTag(locale);
  final text = NumberFormat.decimalPatternDigits(
    locale: tag,
    decimalDigits: kg == kg.roundToDouble() ? 0 : 2,
  ).format(kg);
  return L.of(context).unitWeightKg(text);
}

String formatCapacity(BuildContext context, double? kg) {
  if (kg == null) return '';
  final locale = Localizations.localeOf(context);
  final tag = LocaleFormats.intlTag(locale);
  final text = NumberFormat.decimalPatternDigits(
    locale: tag,
    decimalDigits: kg == kg.roundToDouble() ? 0 : 2,
  ).format(kg);
  return L.of(context).unitCapacityKg(text);
}

/// `30 × 20 × 15 cm`. Returns empty when the set is incomplete — the server
/// only ever stores all three or none.
String formatDimensions(
  BuildContext context,
  double? length,
  double? width,
  double? height,
) {
  if (length == null || width == null || height == null) return '';
  final locale = Localizations.localeOf(context);
  final tag = LocaleFormats.intlTag(locale);
  String one(double v) => NumberFormat.decimalPatternDigits(
    locale: tag,
    decimalDigits: v == v.roundToDouble() ? 0 : 1,
  ).format(v);
  return L.of(context).unitDimensions(one(length), one(width), one(height));
}

/// The distance band, printed as the bounds the server gave.
///
/// Never a single number: `matched_distance_band` is a privacy device, and
/// collapsing `100–300 km` to `200 km` would give away exactly the resolution
/// the server refused to publish.
String formatDistanceBand(BuildContext context, DistanceBand? band) {
  if (band == null) return '';
  final l = L.of(context);
  final locale = Localizations.localeOf(context);
  final tag = LocaleFormats.intlTag(locale);
  final format = NumberFormat.decimalPattern(tag);

  String km(int meters) => format.format(meters ~/ 1000);

  final min = band.minMeters;
  final max = band.maxMeters;

  if (max != null && (min == null || min == 0)) return l.distanceUnder(km(max));
  if (min != null && max == null) return l.distanceOver(km(min));
  if (min != null && max != null) return l.distanceBetween(km(min), km(max));
  return band.label;
}

/// How much the parcel adds to the traveller's route.
String formatDetour(BuildContext context, DetourBand band) {
  final l = L.of(context);
  return switch (band) {
    DetourBand.small => l.discoveryDetourSmall,
    DetourBand.moderate => l.discoveryDetourModerate,
    DetourBand.large => l.discoveryDetourLarge,
    DetourBand.unknown => '',
  };
}

/// `4h 30m`, `45m`.
String formatDuration(BuildContext context, Duration duration) {
  final l = L.of(context);
  final hours = duration.inHours;
  final minutes = duration.inMinutes.remainder(60);
  if (hours == 0) return l.unitDurationM(minutes);
  return l.unitDurationHm(hours, minutes);
}

/// A boost package's length, in whole days where it divides cleanly.
String formatBoostDuration(BuildContext context, int seconds) {
  final l = L.of(context);
  final duration = Duration(seconds: seconds);
  if (duration.inHours >= 24 && duration.inHours % 24 == 0) {
    return l.boostDurationDays(duration.inDays);
  }
  return formatDuration(context, duration);
}

/// Initials for an avatar, from whatever name the API gave.
///
/// Deliberately grapheme-aware: an Arabic or accented name must not be sliced
/// mid-character.
String initialsFor(String name) {
  final parts = name.trim().split(RegExp(r'\s+')).where((p) => p.isNotEmpty);
  if (parts.isEmpty) return '?';
  final letters = parts.take(2).map((p) => p.characters.first);
  return letters.join().toUpperCase();
}
