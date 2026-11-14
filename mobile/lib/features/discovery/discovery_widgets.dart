/// The pieces public discovery is built from.
///
/// Cards render **only what the server sent** (spec 4.2): a first name, a
/// verified flag, a rating that may honestly be absent, cities rather than
/// addresses, and dates. There is no field here for a surname, a phone, a
/// street, a distance or a recipient, because the server never sends one and
/// the client has nothing to fall back on.
///
/// Every card is the same shape on Home, in Browse and on a person's page, so a
/// listing recognised in one place is recognised in the next.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart' show AccountScopedValue, DiscoveryFeed;
import '../../core/format/locale_formats.dart';
import '../../core/money/money.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/discovery.dart' show DiscoveryCandidate;
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/traveler_candidate_card.dart';

// ---------------------------------------------------------------------------
// Places and copy
// ---------------------------------------------------------------------------

/// The route of a card as inline stops. A leg with no label is dropped rather
/// than printed as a blank.
List<InlineRouteStop> placeStops(Iterable<PlaceRef?> places) => [
  for (final place in places)
    if (place != null && place.label.isNotEmpty)
      InlineRouteStop(label: place.label),
];

/// A launch country's name, in the app's own language.
String countryName(L l, String code) => switch (code) {
  'DZ' => l.countryAlgeria,
  'FR' => l.countryFrance,
  'ES' => l.countrySpain,
  'DE' => l.countryGermany,
  _ => code,
};

String capacityBandLabel(L l, CapacityBand band) => switch (band) {
  CapacityBand.under5kg => l.tripCapacityUnder5,
  CapacityBand.fiveToTenKg => l.tripCapacity5to10,
  CapacityBand.tenToTwentyKg => l.tripCapacity10to20,
  CapacityBand.twentyKgPlus => l.tripCapacity20Plus,
  CapacityBand.unknown => '',
};

/// "Samira, Paris to Algiers" — what a screen reader says for a card.
String _spoken(Iterable<String> parts) =>
    parts.where((part) => part.trim().isNotEmpty).join(' · ');

// ---------------------------------------------------------------------------
// A person on a card
// ---------------------------------------------------------------------------

/// Avatar, first name and the trust summary. An unrated person is "New", never
/// a number.
class PublicPersonRow extends StatelessWidget {
  const PublicPersonRow({
    required this.person,
    this.avatarSize = 34,
    this.nameStyle,
    super.key,
  });

  final PublicPerson person;
  final double avatarSize;
  final TextStyle? nameStyle;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final name = person.displayName.trim();

    return Row(
      children: [
        AppAvatar(
          initials: travelerInitial(name),
          name: name,
          size: avatarSize,
          isVerified: person.identityVerified,
        ),
        const SizedBox(width: AppSpace.sm),
        Expanded(
          child: Text(
            name,
            style:
                nameStyle ??
                text.titleSmall?.copyWith(
                  fontWeight: FontWeight.w700,
                  color: c.textPrimary,
                ),
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
          ),
        ),
        const SizedBox(width: AppSpace.xs),
        RatingOrNew(person: person, l: l),
      ],
    );
  }
}

/// A star and a number, or the "New" pill. Never both and never a made-up
/// number.
class RatingOrNew extends StatelessWidget {
  const RatingOrNew({required this.person, required this.l, super.key});

  final PublicPerson person;
  final L l;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final rating = person.rating;

    if (rating.hasScore) {
      final value = rating.average!.toStringAsFixed(1);
      return Semantics(
        label: l.publicRatingA11y(value),
        excludeSemantics: true,
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.star_rounded, size: 16, color: c.attention),
            const SizedBox(width: 2),
            Text(
              value,
              style: text.labelMedium?.copyWith(
                fontWeight: FontWeight.w700,
                color: c.textPrimary,
              ),
            ),
          ],
        ),
      );
    }

    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2),
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
    );
  }
}

// ---------------------------------------------------------------------------
// Cards
// ---------------------------------------------------------------------------

/// A published trip, as a sender browses it.
class TripListingCard extends StatelessWidget {
  const TripListingCard({required this.card, required this.onTap, super.key});

  final TripCard card;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final stops = placeStops(card.stops);
    final when = card.nextDepartureAt ?? card.departsAt;
    final capacity = capacityBandLabel(l, card.capacityBand);
    final modes = card.modes;
    final price = card.price;
    final priceLine = price == null
        ? ''
        : l.tripPriceFrom(
            Money.eurCents(price.perKgEurCents).format(locale),
            Money.eurCents(price.minimumEurCents).format(locale),
          );

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: _spoken([
        card.traveler.displayName,
        routeSemanticLabel(stops: stops, locale: locale),
        if (when != null) l.tripLeaves(LocaleFormats.dayMonth(locale, when)),
        capacity,
        if (price != null) priceLine,
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PublicPersonRow(person: card.traveler),
          const SizedBox(height: AppSpace.sm),
          InlineRoute(stops: stops),
          const SizedBox(height: AppSpace.sm),
          Wrap(
            alignment: WrapAlignment.spaceBetween,
            crossAxisAlignment: WrapCrossAlignment.center,
            spacing: AppSpace.sm,
            runSpacing: AppSpace.xs,
            children: [
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  for (final mode in modes) ...[
                    Icon(
                      mode.icon,
                      size: 14,
                      color: modeAccentColor(context, mode),
                    ),
                    const SizedBox(width: AppSpace.xs),
                  ],
                  if (when != null)
                    Flexible(
                      child: Text(
                        l.tripLeaves(LocaleFormats.dayMonth(locale, when)),
                        style: text.bodySmall?.copyWith(
                          color: c.textSecondary,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ),
                ],
              ),
              if (capacity.isNotEmpty)
                Text(
                  capacity,
                  style: text.labelMedium?.copyWith(
                    color: c.brandInk,
                    fontWeight: FontWeight.w600,
                  ),
                ),
            ],
          ),
          if (price != null) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              priceLine,
              style: text.labelLarge?.copyWith(
                color: c.brandInk,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
          if (card.traveler.completedDeliveries > 0) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              l.findTravelersDeliveries(card.traveler.completedDeliveries),
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}

/// An open request, as a traveler browses it.
class RequestListingCard extends StatelessWidget {
  const RequestListingCard({
    required this.card,
    required this.onTap,
    super.key,
  });

  final RequestCard card;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final stops = placeStops([card.pickup, card.delivery]);
    final deadline = card.deadlineAt;
    final reward = card.totalOfferedReward;

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: _spoken([
        card.title,
        routeSemanticLabel(stops: stops, locale: locale),
        formatWeight(context, card.weightKg),
        if (reward != null) reward.format(locale),
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  card.title,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w700),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (card.fragile) ...[
                const SizedBox(width: AppSpace.sm),
                StatusPill(
                  label: l.requestFragile,
                  tone: StatusTone.waiting,
                  icon: Icons.warning_amber_rounded,
                  compact: true,
                ),
              ],
            ],
          ),
          const SizedBox(height: AppSpace.sm),
          InlineRoute(stops: stops),
          const SizedBox(height: AppSpace.sm),
          Row(
            children: [
              Expanded(
                child: Wrap(
                  spacing: AppSpace.md,
                  runSpacing: AppSpace.xs,
                  children: [
                    if (card.weightKg != null)
                      Text(
                        formatWeight(context, card.weightKg),
                        style: text.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                    if (deadline != null)
                      Text(
                        l.requestCardDeadline(
                          LocaleFormats.dayMonth(locale, deadline),
                        ),
                        style: text.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                  ],
                ),
              ),
              if (reward != null) ...[
                const SizedBox(width: AppSpace.sm),
                MoneyText(
                  reward,
                  size: 15,
                  color: c.textPrimary,
                  semanticPrefix: l.requestOfferedReward,
                ),
              ],
            ],
          ),
          if (card.sender.isNotEmpty) ...[
            const SizedBox(height: AppSpace.xs),
            Text(
              l.requestCardFrom(card.sender),
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],
        ],
      ),
    );
  }
}

/// A traveler's open request in "Matches for you", as the compatible-requests
/// engine published it. No detour, no recommendation: the traveler side never
/// had one.
class CompatibleRequestCard extends StatelessWidget {
  const CompatibleRequestCard({
    required this.candidate,
    required this.onTap,
    this.onCarry,
    this.carrying = false,
    super.key,
  });

  final DiscoveryCandidate candidate;
  final VoidCallback onTap;

  /// "I can carry this". Null hides the action.
  final VoidCallback? onCarry;
  final bool carrying;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final request = candidate.request;
    if (request == null) return const SizedBox.shrink();
    final minimum = candidate.pricing?.minimumReward;
    final stops = [
      for (final label in [
        request.pickup?.coarseLabel ?? '',
        request.delivery?.coarseLabel ?? '',
      ])
        if (label.isNotEmpty) InlineRouteStop(label: label),
    ];

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: _spoken([
        routeSemanticLabel(stops: stops, locale: locale),
        formatWeight(context, request.actualWeightKg),
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          InlineRoute(stops: stops),
          const SizedBox(height: AppSpace.sm),
          Wrap(
            spacing: AppSpace.md,
            runSpacing: AppSpace.xs,
            children: [
              if (request.actualWeightKg != null)
                Text(
                  formatWeight(context, request.actualWeightKg),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
              if (request.deadlineAt != null)
                Text(
                  l.requestCardDeadline(
                    LocaleFormats.dayMonth(locale, request.deadlineAt!),
                  ),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
              // The enforced floor, as on the journey screen. The traveler
              // side has never been shown a recommendation.
              if (minimum != null)
                Text(
                  '${l.moneyMinimumReward}: ${minimum.format(locale)}',
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
            ],
          ),
          if (onCarry != null) ...[
            const SizedBox(height: AppSpace.sm),
            Align(
              alignment: AlignmentDirectional.centerEnd,
              child: AppButton(
                label: l.requestCarryAction,
                variant: AppButtonVariant.secondary,
                expand: false,
                isLoading: carrying,
                onPressed: onCarry,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// A person in a horizontal row on Home, and in the People list.
class ProfileTile extends StatelessWidget {
  const ProfileTile({
    required this.card,
    required this.onTap,
    this.width = 232,
    super.key,
  });

  final ProfileCard card;
  final VoidCallback? onTap;
  final double? width;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final since = card.memberSince;
    final route = card.usualRoutes.isEmpty ? null : card.usualRoutes.first;

    final tile = AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: _spoken([
        card.person.displayName,
        if (since != null)
          l.profileMemberSince(LocaleFormats.monthYear(locale, since)),
      ]),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          PublicPersonRow(person: card.person, avatarSize: 40),
          const SizedBox(height: AppSpace.sm),
          if (card.person.completedDeliveries > 0)
            Text(
              l.findTravelersDeliveries(card.person.completedDeliveries),
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          if (since != null)
            Text(
              l.profileMemberSince(LocaleFormats.monthYear(locale, since)),
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          const SizedBox(height: AppSpace.sm),
          if (route != null)
            InlineRoute(
              stops: placeStops([route.origin, route.destination]),
              style: text.labelMedium?.copyWith(color: c.textPrimary),
            )
          else
            Text(
              l.profileNoUsualRoutes,
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
        ],
      ),
    );

    return width == null ? tile : SizedBox(width: width, child: tile);
  }
}

// ---------------------------------------------------------------------------
// Sections
// ---------------------------------------------------------------------------

/// The frame every Home discovery section shares.
///
/// Loads on its own: a failure here is an [InlineFailure] with a retry, and
/// the rest of the page stays usable. When a refresh fails but earlier content
/// exists, the content stays and says so — a calm "showing what we loaded
/// earlier" instead of a screen that suddenly goes blank.
class DiscoverySection<T> extends StatelessWidget {
  const DiscoverySection({
    required this.value,
    required this.data,
    required this.onRetry,
    this.skeleton,
    super.key,
  });

  final AsyncValue<T> value;
  final Widget Function(T data) data;
  final VoidCallback onRetry;
  final Widget? skeleton;

  @override
  Widget build(BuildContext context) {
    final current = value.ofCurrentAccount;
    if (current.hasValue) {
      final content = data(current.requireValue);
      if (!current.hasError) return content;
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StaleNote(onRetry: onRetry),
          content,
        ],
      );
    }
    if (current.hasError) {
      return Padding(
        padding: const EdgeInsets.only(top: AppSpace.lg),
        child: InlineFailure(error: current.error, onRetry: onRetry),
      );
    }
    return skeleton ?? const SkeletonCardList(count: 2);
  }
}

/// "Showing what we loaded earlier", with a retry.
class StaleNote extends StatelessWidget {
  const StaleNote({required this.onRetry, super.key});

  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(top: AppSpace.md),
      child: Semantics(
        liveRegion: true,
        child: Row(
          children: [
            Icon(Icons.history_rounded, size: 15, color: c.textTertiary),
            const SizedBox(width: AppSpace.sm),
            Expanded(
              child: Text(
                l.discoveryShowingEarlier,
                style: text.labelMedium?.copyWith(color: c.textSecondary),
              ),
            ),
            TextButton(onPressed: onRetry, child: Text(l.actionRetry)),
          ],
        ),
      ),
    );
  }
}

/// A row of person-tile skeletons, the loading shape of the People section.
class PeopleSkeleton extends StatelessWidget {
  const PeopleSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return Semantics(
      label: l.a11yLoadingContent,
      liveRegion: true,
      child: SingleChildScrollView(
        scrollDirection: Axis.horizontal,
        physics: const NeverScrollableScrollPhysics(),
        child: Row(
          children: [
            for (var i = 0; i < 3; i++) ...[
              if (i > 0) const SizedBox(width: AppSpace.md),
              const SizedBox(
                width: 232,
                child: AppCard(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          SkeletonBox(
                            width: 40,
                            height: 40,
                            radius: AppRadius.rPill,
                          ),
                          SizedBox(width: AppSpace.md),
                          SkeletonBox(width: 100, height: 13),
                        ],
                      ),
                      SizedBox(height: AppSpace.md),
                      SkeletonBox(width: 120, height: 11),
                      SizedBox(height: AppSpace.sm),
                      SkeletonBox(width: 160, height: 11),
                    ],
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// A horizontal run of cards that is as tall as its tallest card.
class HorizontalCards extends StatelessWidget {
  const HorizontalCards({required this.children, super.key});

  final List<Widget> children;

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    scrollDirection: Axis.horizontal,
    child: IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          for (var i = 0; i < children.length; i++) ...[
            if (i > 0) const SizedBox(width: AppSpace.md),
            children[i],
          ],
        ],
      ),
    ),
  );
}

// ---------------------------------------------------------------------------
// Corridor chips
// ---------------------------------------------------------------------------

/// "All routes" and one chip per launch corridor.
class CorridorChips extends StatelessWidget {
  const CorridorChips({
    required this.selected,
    required this.onSelected,
    super.key,
  });

  final Corridor? selected;
  final ValueChanged<Corridor?> onSelected;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          _CorridorChip(
            selected: selected == null,
            semanticLabel: l.corridorAll,
            onTap: () => onSelected(null),
            child: Text(l.corridorAll),
          ),
          for (final corridor in Corridor.launchCorridors) ...[
            const SizedBox(width: AppSpace.sm),
            _CorridorChip(
              selected: selected == corridor,
              semanticLabel: l.corridorA11y(
                countryName(l, corridor.originCountry),
                countryName(l, corridor.destinationCountry),
              ),
              onTap: () => onSelected(corridor),
              child: InlineRoute(
                wrap: false,
                stops: [
                  InlineRouteStop(
                    label: countryName(l, corridor.originCountry),
                  ),
                  InlineRouteStop(
                    label: countryName(l, corridor.destinationCountry),
                  ),
                ],
                style: Theme.of(context).textTheme.labelLarge,
                arrowColor: context.colors.textTertiary,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _CorridorChip extends StatelessWidget {
  const _CorridorChip({
    required this.selected,
    required this.semanticLabel,
    required this.onTap,
    required this.child,
  });

  final bool selected;
  final String semanticLabel;
  final VoidCallback onTap;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final foreground = selected ? c.onBrand : c.textPrimary;

    return Semantics(
      button: true,
      selected: selected,
      label: semanticLabel,
      excludeSemantics: true,
      onTap: onTap,
      child: Material(
        color: selected ? c.brand : c.surface,
        borderRadius: AppRadius.rPill,
        child: InkWell(
          onTap: onTap,
          borderRadius: AppRadius.rPill,
          child: Container(
            constraints: const BoxConstraints(minHeight: AppSpace.minTapTarget),
            padding: const EdgeInsets.symmetric(horizontal: AppSpace.lg),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: AppRadius.rPill,
              border: Border.all(color: selected ? c.brandInk : c.hairline),
            ),
            child: DefaultTextStyle.merge(
              style: text.labelLarge?.copyWith(
                color: foreground,
                fontWeight: selected ? FontWeight.w700 : FontWeight.w500,
              ),
              child: child,
            ),
          ),
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Paging footer
// ---------------------------------------------------------------------------

/// The end of a paged list: a spinner while the next page loads, a retry when it
/// failed, and nothing when the server said there is no more.
class FeedFooter extends StatelessWidget {
  const FeedFooter({
    required this.loadingMore,
    required this.error,
    required this.onRetry,
    super.key,
  });

  final bool loadingMore;
  final Object? error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    if (loadingMore) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpace.lg),
        child: Center(
          child: Semantics(
            label: l.a11yLoadingContent,
            child: const SizedBox(
              width: 24,
              height: 24,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            ),
          ),
        ),
      );
    }
    if (error != null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpace.md),
        child: Center(
          child: AppButton(
            label: l.actionRetry,
            variant: AppButtonVariant.secondary,
            expand: false,
            onPressed: onRetry,
          ),
        ),
      );
    }
    return const SizedBox(height: AppSpace.xl);
  }
}

/// A lazy list that asks for the next page when the end comes into reach.
///
/// [header] scrolls with the rows, so a summary above a list is not a second
/// scroll view.
class PagedFeedList<T> extends StatelessWidget {
  const PagedFeedList({
    required this.feed,
    required this.itemBuilder,
    required this.onLoadMore,
    this.header,
    super.key,
  });

  final DiscoveryFeed<T> feed;
  final Widget Function(BuildContext, T) itemBuilder;
  final Future<void> Function() onLoadMore;
  final Widget? header;

  @override
  Widget build(BuildContext context) {
    final lead = header == null ? 0 : 1;
    return NotificationListener<ScrollNotification>(
      onNotification: (notification) {
        if (feed.hasMore &&
            !feed.loadingMore &&
            feed.loadMoreError == null &&
            notification.metrics.pixels >=
                notification.metrics.maxScrollExtent - 240) {
          unawaited(onLoadMore());
        }
        return false;
      },
      child: ListView.builder(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: AppScrollPadding.page(context, top: AppSpace.sm),
        itemCount: lead + feed.items.length + 1,
        itemBuilder: (context, index) {
          if (lead == 1 && index == 0) return header;
          final row = index - lead;
          if (row == feed.items.length) {
            return FeedFooter(
              loadingMore: feed.loadingMore,
              error: feed.loadMoreError,
              onRetry: () => unawaited(onLoadMore()),
            );
          }
          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpace.md),
            child: itemBuilder(context, feed.items[row]),
          );
        },
      ),
    );
  }
}
