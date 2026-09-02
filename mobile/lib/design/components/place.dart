/// How a catalogue place is put on screen — in one file, for every screen.
///
/// The geography catalogue hands the client three things that five different
/// screens were each deciding for themselves: which part of a row is the
/// *place*, which part is *context*, and whether the row is an airport. The
/// picker, the sender form, the journey form and the map header now all read
/// from here, so a commune looks like a commune everywhere and an airport is
/// unmistakable everywhere.
///
/// Two presentation rules this file owns:
///
/// * **An IATA code is never prose.** It renders as a monospaced badge locked
///   to [TextDirection.ltr], so `CDG` stays `CDG` inside an Arabic layout
///   rather than being reordered by the surrounding paragraph.
/// * **Context never repeats the name.** An Algerian commune whose wilaya
///   carries the same name (Jijel in Jijel, Sétif in Sétif) would otherwise
///   render as two stacked copies of one word, which reads as a choice
///   between two versions of the same place. The catalogue's parent tier
///   separates them — "Jijel" over "Jijel Wilaya" — and where the source
///   records no tier, the country is shown instead.
///
/// Nothing here decides matching. The catalogue's `matching_locality` is the
/// server's business and is deliberately never surfaced: a traveller flying
/// into CDG does not need to be told that CDG resolves to Paris.
library;

import 'package:country_flags/country_flags.dart';
import 'package:flutter/material.dart';

import '../../domain/canonical_place.dart';
import '../../l10n/app_localizations.dart';
import '../tokens.dart';
import '../typography.dart';
import 'primitives.dart';

// ---------------------------------------------------------------------------
// Labels
// ---------------------------------------------------------------------------

/// The four launch countries, named in the reader's language.
///
/// The catalogue serves one canonical (English) country name per row, which is
/// correct for a catalogue and wrong on an Arabic screen. The server name is
/// still the fallback, so a fifth country appearing in the API shows up under
/// its own name rather than not at all.
String countryDisplayName(L l, String code, {String? fallback}) =>
    switch (code.toUpperCase()) {
      'DZ' => l.countryNameAlgeria,
      'FR' => l.countryNameFrance,
      'ES' => l.countryNameSpain,
      'DE' => l.countryNameGermany,
      _ => fallback ?? code.toUpperCase(),
    };

/// The place, as one line of text — for a select field or a route stop.
///
/// Keeps the IATA in the string because the caller owns a plain `Text`. Where
/// the layout is ours, prefer [IataBadge].
String placeLabel(CanonicalPlace place) {
  final iata = place.iataCode;
  if (place.isAirport && iata != null && iata.isNotEmpty) {
    return '${place.name} ($iata)';
  }
  return place.name;
}

/// The parent's name qualified by its own administrative tier — "Jijel
/// Wilaya", "Nord department", "Madrid province".
///
/// The tier is the catalogue's `parent_admin_level`, served from the reviewed
/// source. A tier the catalogue does not name, or one this app has no phrasing
/// for, falls back to the bare parent name: a wrong tier is worse than none,
/// and the client is not allowed to infer one from the country.
String parentTierLabel(L l, String name, String adminLevel) =>
    switch (adminLevel.trim().toLowerCase()) {
      'wilaya' => l.placeTierWilaya(name),
      'department' => l.placeTierDepartment(name),
      'region' => l.placeTierRegion(name),
      'province' => l.placeTierProvince(name),
      'autonomous_community' => l.placeTierAutonomousCommunity(name),
      'state' => l.placeTierState(name),
      'district' => l.placeTierDistrict(name),
      _ => name,
    };

/// The supporting line under a place: its administrative parent named with its
/// own tier, or the country when the parent would only repeat the name.
String placeContext(BuildContext context, CanonicalPlace place) {
  final l = L.of(context);
  final parent = place.parentName.trim();
  final country = countryDisplayName(l, place.countryCode);
  if (parent.isEmpty) return country;
  final tiered = parentTierLabel(l, parent, place.parentAdminLevel);
  // A parent that only repeats the name says nothing — unless its tier makes
  // it a different thing: the commune Jijel sits inside Jijel Wilaya, and
  // saying so is more use than falling back to "Algeria".
  if (_sameName(tiered, place.name)) return country;
  return tiered;
}

/// What a screen reader should hear for a whole row: the place, whether it is
/// an airport, its code spelled as a code, and its context.
String placeSemanticLabel(BuildContext context, CanonicalPlace place) {
  final l = L.of(context);
  final iata = place.iataCode;
  return [
    place.name,
    if (place.isAirport) l.locationTypeAirport,
    if (place.isAirport && iata != null && iata.isNotEmpty)
      iata.split('').join(' '),
    placeContext(context, place),
  ].where((part) => part.isNotEmpty).join(', ');
}

/// Case- and accent-insensitive enough for "is the parent just the name
/// again?". Not a matching decision — matching is the server's, on IDs.
bool _sameName(String a, String b) =>
    a.toLowerCase().trim() == b.toLowerCase().trim();

// ---------------------------------------------------------------------------
// Marks
// ---------------------------------------------------------------------------

/// An IATA code as a stamped monospaced badge.
///
/// Locked to LTR: the three letters are a code, not a word, and must not be
/// re-ordered by an Arabic paragraph around them.
class IataBadge extends StatelessWidget {
  const IataBadge({required this.code, this.tone, super.key});

  final String code;
  final Color? tone;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final tint = tone ?? c.modeFlight;
    return Semantics(
      label: code.split('').join(' '),
      excludeSemantics: true,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: c.surfaceSunken,
          borderRadius: AppRadius.rXs,
          border: Border.all(color: tint.withValues(alpha: 0.35)),
        ),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Text(
            code.toUpperCase(),
            style: AppTypography.monoLabel(context, color: tint, size: 11),
          ),
        ),
      ),
    );
  }
}

/// The square glyph tile that opens a place row.
///
/// A plane on the flight tone for an airport, a skyline on the drive tone for
/// a locality. It is the fastest of the three airport signals on the row (tile,
/// badge, word) and the only one that survives a glance.
class PlaceGlyph extends StatelessWidget {
  const PlaceGlyph({required this.place, this.size = 38, super.key});

  final CanonicalPlace place;
  final double size;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final tint = place.isAirport ? c.modeFlight : c.modeDrive;
    return ExcludeSemantics(
      child: Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          color: tint.withValues(alpha: 0.12),
          borderRadius: AppRadius.rSm,
          border: Border.all(color: tint.withValues(alpha: 0.28)),
        ),
        child: Icon(
          place.isAirport
              ? Icons.flight_takeoff_rounded
              : Icons.location_city_rounded,
          size: size * 0.5,
          color: tint,
        ),
      ),
    );
  }
}

/// A country as a tappable pill: flag, name in the reader's language, and a
/// selected state that is a filled surface *and* a check, never colour alone.
class CountryChoiceTile extends StatelessWidget {
  const CountryChoiceTile({
    required this.code,
    required this.name,
    required this.selected,
    required this.onTap,
    super.key,
  });

  final String code;
  final String name;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Semantics(
      button: true,
      selected: selected,
      label: name,
      onTap: onTap,
      child: ExcludeSemantics(
        child: Material(
          color: selected ? c.surfaceInverse : c.surface,
          borderRadius: AppRadius.rPill,
          child: InkWell(
            onTap: onTap,
            borderRadius: AppRadius.rPill,
            child: Container(
              constraints: const BoxConstraints(
                minHeight: AppSpace.minTapTarget,
              ),
              padding: const EdgeInsetsDirectional.fromSTEB(
                AppSpace.md,
                AppSpace.sm,
                AppSpace.lg,
                AppSpace.sm,
              ),
              decoration: BoxDecoration(
                borderRadius: AppRadius.rPill,
                border: Border.all(
                  color: selected ? c.surfaceInverse : c.hairlineStrong,
                ),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  ClipRRect(
                    borderRadius: BorderRadius.circular(3),
                    child: SizedBox(
                      height: 16,
                      width: 24,
                      child: CountryFlag.fromCountryCode(code),
                    ),
                  ),
                  const SizedBox(width: AppSpace.sm),
                  Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: text.titleSmall?.copyWith(
                      color: selected ? c.textOnInverse : c.textPrimary,
                    ),
                  ),
                  if (selected) ...[
                    const SizedBox(width: AppSpace.sm),
                    Icon(Icons.check_rounded, size: 16, color: c.textOnInverse),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Rows
// ---------------------------------------------------------------------------

/// One catalogue place in a list of results.
///
/// [selected] marks the choice the caller arrived with, so re-opening the
/// picker to change a city is not a blank screen that has forgotten what was
/// already chosen.
class PlaceResultRow extends StatelessWidget {
  const PlaceResultRow({
    required this.place,
    required this.onTap,
    this.selected = false,
    super.key,
  });

  final CanonicalPlace place;
  final VoidCallback onTap;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final iata = place.iataCode;
    final showIata = place.isAirport && iata != null && iata.isNotEmpty;

    return Semantics(
      button: true,
      selected: selected,
      label: placeSemanticLabel(context, place),
      onTap: onTap,
      child: ExcludeSemantics(
        child: AppCard(
          onTap: onTap,
          padding: const EdgeInsets.all(AppSpace.md),
          child: Row(
            children: [
              PlaceGlyph(place: place),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      place.name,
                      style: text.titleSmall,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    Row(
                      children: [
                        if (place.isAirport) ...[
                          Text(
                            l.locationTypeAirport.toUpperCase(),
                            style: AppTypography.monoLabel(
                              context,
                              color: c.modeFlight,
                              size: 10,
                            ),
                            maxLines: 1,
                          ),
                          const SizedBox(width: AppSpace.sm),
                        ],
                        Flexible(
                          child: Text(
                            placeContext(context, place),
                            style: text.bodySmall?.copyWith(
                              color: c.textSecondary,
                            ),
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              if (showIata) ...[
                IataBadge(code: iata),
                const SizedBox(width: AppSpace.sm),
              ],
              Icon(
                selected
                    ? Icons.check_circle_rounded
                    : (context.isRtl
                          ? Icons.chevron_left_rounded
                          : Icons.chevron_right_rounded),
                size: 20,
                color: selected ? c.brand : c.textTertiary,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// The already-chosen place, restated where the user needs to keep seeing it:
/// above a map they are dropping a pin inside, and above a search they opened
/// to change it.
class PlaceContextStrip extends StatelessWidget {
  const PlaceContextStrip({
    required this.place,
    required this.caption,
    super.key,
  });

  final CanonicalPlace place;

  /// What this place *is* to the screen showing it — "Choosing a point inside
  /// Jijel", "Currently selected". Carried by the caller because the same
  /// strip means different things on the map and in the picker.
  final String caption;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final iata = place.iataCode;
    final showIata = place.isAirport && iata != null && iata.isNotEmpty;

    return Semantics(
      label: '$caption, ${placeSemanticLabel(context, place)}',
      child: ExcludeSemantics(
        child: Container(
          padding: const EdgeInsets.all(AppSpace.md),
          decoration: BoxDecoration(
            color: c.surfaceSunken,
            borderRadius: AppRadius.rMd,
            border: Border.all(color: c.hairline),
          ),
          child: Row(
            children: [
              PlaceGlyph(place: place, size: 32),
              const SizedBox(width: AppSpace.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      caption,
                      style: AppTypography.eyebrow(
                        context,
                        color: c.textTertiary,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: AppSpace.xxs),
                    Text(
                      place.name,
                      style: text.titleSmall,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    Text(
                      placeContext(context, place),
                      style: text.bodySmall?.copyWith(color: c.textSecondary),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                  ],
                ),
              ),
              if (showIata) ...[
                const SizedBox(width: AppSpace.sm),
                IataBadge(code: iata),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
