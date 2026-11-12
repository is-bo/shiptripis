/// The traveler row shared by Find Travelers and Home.
library;

import 'package:flutter/material.dart';

import '../../core/format/locale_formats.dart';
import '../../core/money/money.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/find_travelers.dart';
import '../../l10n/app_localizations.dart';
import 'status_copy.dart';

/// The initial shown in a traveler's avatar. A traveler with no name still gets
/// a disc, and a name in any script is cut on a grapheme, never mid-character.
String travelerInitial(String name) {
  final trimmed = name.trim();
  if (trimmed.isEmpty) return 'T';
  return trimmed.characters.first.toUpperCase();
}

/// The accent for a transport mode's icon.
Color modeAccentColor(BuildContext context, TransportMode mode) {
  final c = context.colors;
  return switch (mode) {
    TransportMode.flight => c.modeFlight,
    TransportMode.drive => c.modeDrive,
    TransportMode.sea => c.modeSea,
    TransportMode.unknown => c.textTertiary,
  };
}

/// One traveler on Find Travelers, and in Home's "Matches for you".
///
/// A server verdict rendered: route first, person second. The same card on both
/// screens, so a traveler recognised on Home is the row Find Travelers opens
/// onto. ~155dp tall, so three fit under a Home section heading.
class TravelerCandidateCard extends StatelessWidget {
  const TravelerCandidateCard({
    required this.candidate,
    required this.onTap,
    super.key,
  });

  final TravelerCandidate candidate;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final traveler = candidate.traveler;
    final canView = candidate.can(CandidateAction.viewJourney);

    // Stops for InlineRoute
    final stops = candidate.route.stops
        .map((s) => InlineRouteStop(label: s.label, airportIata: s.airportIata))
        .toList(growable: false);

    // Travel meta: Mode · Date
    final modeLabel = _modeSummary(context, candidate);
    final departureText = candidate.departsAt != null
        ? LocaleFormats.dayMonth(locale, candidate.departsAt!)
        : null;
    final travelMeta = departureText != null
        ? '$modeLabel · $departureText'
        : modeLabel;

    // A Traveler with no display name used to be labelled "View trip", which
    // read as a person called View trip. The row keeps its shape without
    // inventing one.
    final displayName = traveler.displayName.trim();
    final hasName = displayName.isNotEmpty;

    // Was `discoveryTravelersTitle`, so a screen reader read "Travelers for
    // this parcel" once per card and never said who or where.
    final routeLabel = candidate.route.stops
        .map((s) => s.label)
        .where((label) => label.isNotEmpty)
        .join(' — ');

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: [
        if (hasName) displayName,
        if (routeLabel.isNotEmpty) routeLabel,
        travelMeta,
        if (candidate.economics?.listed case final listed?)
          l.findTravelersListedPrice(
            Money.eurCents(listed.reward).format(locale),
          ),
      ].join(' · '),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Row 1 — Person: Avatar / Name / Rating or New
          Row(
            children: [
              AppAvatar(
                initials: travelerInitial(traveler.displayName),
                name: hasName ? displayName : '',
                size: 34,
                isVerified: traveler.identityVerified,
              ),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: hasName
                    ? Text(
                        displayName,
                        style: text.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: c.textPrimary,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      )
                    : const SizedBox.shrink(),
              ),
              const SizedBox(width: AppSpace.xs),
              if (traveler.rating.hasScore)
                Semantics(
                  label: '${traveler.rating.average!.toStringAsFixed(1)} stars',
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(Icons.star_rounded, size: 16, color: c.attention),
                      const SizedBox(width: 2),
                      Text(
                        traveler.rating.average!.toStringAsFixed(1),
                        style: text.labelMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: c.textPrimary,
                        ),
                      ),
                    ],
                  ),
                )
              else
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 7,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: c.brandSoft,
                    borderRadius: AppRadius.rPill,
                  ),
                  child: Text(
                    l.findTravelersNewTraveller,
                    style: text.labelSmall?.copyWith(
                      color: c.brandStrong,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
            ],
          ),

          const SizedBox(height: AppSpace.sm),

          // Row 2 — Route: Horizontal InlineRoute with strict RTL travel sequence
          InlineRoute(
            stops: stops,
            continuesBefore: candidate.route.continuesBefore,
            continuesAfter: candidate.route.continuesAfter,
          ),

          const SizedBox(height: AppSpace.sm),

          // Row 3 — Travel meta (Mode · Date) + Match quality (Route fit)
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppSpace.sm,
            runSpacing: AppSpace.xs,
            children: [
              ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: MediaQuery.of(context).size.width - 64,
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      candidate.primaryMode.icon,
                      size: 14,
                      color: modeAccentColor(context, candidate.primaryMode),
                    ),
                    const SizedBox(width: AppSpace.xs),
                    Flexible(
                      child: Text(
                        travelMeta,
                        style: text.bodySmall?.copyWith(
                          color: c.textSecondary,
                          fontWeight: FontWeight.w500,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                  ],
                ),
              ),
              _RouteFitBadge(routeFit: candidate.routeFit),
            ],
          ),

          // Row 3b — what this traveller would charge for this parcel, from
          // the server. Absent when the journey has no price.
          if (candidate.economics?.listed case final listed?) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              l.findTravelersListedPrice(
                Money.eurCents(listed.reward).format(locale),
              ),
              style: text.titleSmall?.copyWith(
                fontWeight: FontWeight.w700,
                color: c.brandInk,
              ),
            ),
          ],

          const SizedBox(height: AppSpace.sm),

          // Row 4 — Trust + Action (Deliveries count + View trip)
          Row(
            children: [
              Expanded(
                child: traveler.completedDeliveries > 0
                    ? Text(
                        l.findTravelersDeliveries(traveler.completedDeliveries),
                        style: text.bodySmall?.copyWith(
                          color: c.textTertiary,
                          fontWeight: FontWeight.w500,
                        ),
                      )
                    : const SizedBox.shrink(),
              ),
              if (canView)
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      l.findTravelersViewTrip,
                      style: text.labelMedium?.copyWith(
                        color: c.brandInk,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 2),
                    Icon(
                      Icons.chevron_right_rounded,
                      size: 16,
                      color: c.brandInk,
                    ),
                  ],
                )
              else
                Text(
                  l.findTravelersViewTrip,
                  style: text.labelMedium?.copyWith(color: c.textTertiary),
                ),
            ],
          ),
        ],
      ),
    );
  }

  static String _modeSummary(
    BuildContext context,
    TravelerCandidate candidate,
  ) {
    final modes = candidate.route.segments
        .map((s) => s.mode)
        .where((m) => m != TransportMode.unknown)
        .toSet();

    // Every mode the route uses, always in the same order, so two trips that
    // fly and sail read alike.
    final used = [
      for (final mode in const [
        TransportMode.flight,
        TransportMode.sea,
        TransportMode.drive,
      ])
        if (modes.contains(mode)) transportModeLabel(context, mode),
    ];
    return used.length > 1
        ? used.join(' + ')
        : transportModeLabel(context, candidate.primaryMode);
  }
}

class _RouteFitBadge extends StatelessWidget {
  const _RouteFitBadge({required this.routeFit});

  final RouteFit routeFit;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;

    // A fit the client has never heard of is not a fit it may name. Claiming
    // "Compatible route" for an unknown verdict is the client scoring the match,
    // which is exactly what this screen does not do; the badge degrades away
    // instead and the rest of the card still reads.
    final (String label, StatusTone tone)? classified = switch (routeFit) {
      RouteFit.excellent => (l.findTravelersRouteFitExcellent, StatusTone.good),
      RouteFit.good => (l.findTravelersRouteFitGood, StatusTone.progress),
      RouteFit.compatible => (
        l.findTravelersRouteFitCompatible,
        StatusTone.neutral,
      ),
      RouteFit.unknown => null,
    };
    if (classified == null) return const SizedBox.shrink();
    final (label, tone) = classified;

    final style = StatusStyle.of(context, tone);

    return ConstrainedBox(
      constraints: BoxConstraints(
        maxWidth: MediaQuery.of(context).size.width - 64,
      ),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
        decoration: BoxDecoration(
          color: style.background,
          borderRadius: AppRadius.rPill,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            StatusDot(tone: tone, size: 6),
            const SizedBox(width: AppSpace.xs),
            Flexible(
              child: Text(
                label,
                style: text.labelSmall?.copyWith(
                  color: style.foreground,
                  fontWeight: FontWeight.w600,
                ),
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ],
        ),
      ),
    );
  }
}
