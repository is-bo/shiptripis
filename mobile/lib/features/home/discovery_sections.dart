/// Home's discovery sections.
///
/// Four sections, each reading its own provider, so one failing, one switched
/// off or one still loading never changes another:
///
/// * **Matches for you** — the first rows of Find Travelers for each of a
///   sender's open requests, or of the compatible-requests list for each of a
///   traveler's journeys. The same engines, the same rows.
/// * **Listings** — trips leaving soon for a sender, parcels looking for a
///   traveler for a traveler, narrowed with the launch corridor chips.
/// * **People** — members who opted in to a public profile, on the side the
///   viewer looks at.
/// * **The opt-in card** — one-time, dismissible, never blocks anything.
///
/// A tier that staff switched off is absent: no header, no chips, no error.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/discovery_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/tokens.dart';
import '../../domain/discovery.dart' show DiscoveryCandidate;
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import '../common/traveler_candidate_card.dart';
import '../discovery/discovery_actions.dart';
import '../discovery/discovery_widgets.dart';

/// How many matched items a section shows. Each item is one open request or
/// one journey, with at most three rows under it.
const _maxMatchGroups = 3;

// ---------------------------------------------------------------------------
// Matches for you
// ---------------------------------------------------------------------------

class MatchesSection extends ConsumerWidget {
  const MatchesSection({required this.isSender, super.key});

  final bool isSender;

  @override
  Widget build(BuildContext context, WidgetRef ref) =>
      isSender ? const _SenderMatches() : const _TravelerMatches();
}

class _SenderMatches extends ConsumerWidget {
  const _SenderMatches();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    return _MatchesFrame<SenderMatchGroup>(
      value: ref.watch(senderMatchesProvider),
      onRetry: () => ref.invalidate(senderMatchesProvider),
      emptyBody: (state) => state == MatchesState.noActiveItems
          ? l.homeMatchesSenderNone
          : l.homeMatchesSenderWaiting,
      emptyAction: l.homeCreateRequest,
      onEmptyAction: () => context.openRequestCreate(),
      groupBuilder: (context, group) => _MatchGroup(
        route: placeStops([group.pickup, group.delivery]),
        deadline: group.deadlineAt,
        onSeeAll: group.moreAvailable
            ? () => context.openDiscovery(group.requestId)
            : null,
        children: [
          for (final candidate in group.results)
            TravelerCandidateCard(
              candidate: candidate,
              onTap: () => context.openDiscovery(
                group.requestId,
                focusJourneyId: candidate.journeyId,
              ),
            ),
        ],
      ),
    );
  }
}

class _TravelerMatches extends ConsumerWidget {
  const _TravelerMatches();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    return _MatchesFrame<TravelerMatchGroup>(
      value: ref.watch(travelerMatchesProvider),
      onRetry: () => ref.invalidate(travelerMatchesProvider),
      emptyBody: (state) => state == MatchesState.noActiveItems
          ? l.homeMatchesTravelerNone
          : l.homeMatchesTravelerWaiting,
      emptyAction: l.homeCreateJourney,
      onEmptyAction: () => context.openJourneyCreate(),
      groupBuilder: (context, group) => _MatchGroup(
        route: placeStops([group.origin, group.destination]),
        deadline: null,
        onSeeAll: group.moreAvailable
            ? () => context.openJourney(group.journeyId)
            : null,
        children: [
          for (final candidate in group.results)
            _CarryableRequest(group: group, candidate: candidate),
        ],
      ),
    );
  }
}

/// The frame both roles share: header, loading, failure, empty and results.
class _MatchesFrame<G extends MatchGroup> extends StatelessWidget {
  const _MatchesFrame({
    required this.value,
    required this.onRetry,
    required this.emptyBody,
    required this.emptyAction,
    required this.onEmptyAction,
    required this.groupBuilder,
  });

  final AsyncValue<MatchesForYou<G>> value;
  final VoidCallback onRetry;
  final String Function(MatchesState state) emptyBody;
  final String emptyAction;
  final VoidCallback onEmptyAction;
  final Widget Function(BuildContext context, G group) groupBuilder;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.homeMatchesTitle),
        DiscoverySection<MatchesForYou<G>>(
          value: value,
          onRetry: onRetry,
          data: (data) {
            final groups = data.withResults.take(_maxMatchGroups).toList();
            if (groups.isEmpty) {
              return AppEmptyState(
                title: l.homeMatchesEmptyTitle,
                body: emptyBody(data.state),
                icon: Icons.handshake_outlined,
                compact: true,
                // Waiting is not a problem to fix: only "nothing to match"
                // has a next step.
                actionLabel: data.state == MatchesState.noActiveItems
                    ? emptyAction
                    : null,
                onAction: data.state == MatchesState.noActiveItems
                    ? onEmptyAction
                    : null,
              );
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                for (final group in groups) groupBuilder(context, group),
              ],
            );
          },
        ),
      ],
    );
  }
}

/// One of my requests or journeys, with the rows that fit it.
class _MatchGroup extends StatelessWidget {
  const _MatchGroup({
    required this.route,
    required this.deadline,
    required this.onSeeAll,
    required this.children,
  });

  final List<InlineRouteStop> route;
  final DateTime? deadline;
  final VoidCallback? onSeeAll;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.lg),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    InlineRoute(
                      stops: route,
                      style: text.titleSmall?.copyWith(
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if (deadline != null)
                      Text(
                        l.requestCardDeadline(
                          LocaleFormats.dayMonth(locale, deadline!),
                        ),
                        style: text.bodySmall?.copyWith(color: c.textTertiary),
                      ),
                  ],
                ),
              ),
              if (onSeeAll != null)
                TextButton(onPressed: onSeeAll, child: Text(l.actionSeeAll)),
            ],
          ),
          const SizedBox(height: AppSpace.sm),
          for (final child in children) ...[
            child,
            const SizedBox(height: AppSpace.md),
          ],
        ],
      ),
    );
  }
}

/// A traveler's matched request with "I can carry this".
class _CarryableRequest extends ConsumerStatefulWidget {
  const _CarryableRequest({required this.group, required this.candidate});

  final TravelerMatchGroup group;
  final DiscoveryCandidate candidate;

  @override
  ConsumerState<_CarryableRequest> createState() => _CarryableRequestState();
}

class _CarryableRequestState extends ConsumerState<_CarryableRequest> {
  bool _busy = false;
  bool _sent = false;

  Future<void> _carry() async {
    final requestId = widget.candidate.request?.id;
    if (requestId == null) return;
    final l = L.of(context);
    setState(() => _busy = true);
    final outcome = await sendCarrySignal(
      context,
      ref,
      requestId: requestId,
      journeyId: widget.group.journeyId,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _sent = outcome is CarrySent;
    });
    switch (outcome) {
      case CarrySent(:final created):
        AppSnack.success(
          context,
          created ? l.carrySentTitle : l.carryAlreadySentTitle,
        );
      case CarryRefused(:final message):
        AppSnack.info(context, message);
    }
  }

  @override
  Widget build(BuildContext context) => CompatibleRequestCard(
    candidate: widget.candidate,
    carrying: _busy,
    onCarry: _sent ? null : _carry,
    onTap: () => context.openJourney(widget.group.journeyId),
  );
}

// ---------------------------------------------------------------------------
// Listings
// ---------------------------------------------------------------------------

/// Trips leaving soon (sender) or parcels looking for a traveler (traveler).
class ListingsSection extends ConsumerStatefulWidget {
  const ListingsSection({required this.isSender, super.key});

  final bool isSender;

  @override
  ConsumerState<ListingsSection> createState() => _ListingsSectionState();
}

class _ListingsSectionState extends ConsumerState<ListingsSection> {
  Corridor? _corridor;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final isSender = widget.isSender;

    return isSender
        ? _frame<TripCard>(
            context,
            title: l.homeTripsTitle,
            value: ref.watch(previewTripsProvider(_corridor)),
            retry: () => ref.invalidate(previewTripsProvider(_corridor)),
            browse: () => context.openBrowseTrips(corridor: _corridor),
            card: (card) => TripListingCard(
              card: card,
              onTap: () => showTripPreview(context, card),
            ),
            emptyBody: l.homeTripsEmptyBody,
            emptyAction: l.homeCreateRequest,
            onEmptyAction: () => context.openRequestCreate(),
            emptyIcon: Icons.flight_takeoff_rounded,
          )
        : _frame<RequestCard>(
            context,
            title: l.homeRequestsTitle,
            value: ref.watch(previewRequestsProvider(_corridor)),
            retry: () => ref.invalidate(previewRequestsProvider(_corridor)),
            browse: () => context.openBrowseRequests(corridor: _corridor),
            card: (card) => RequestListingCard(
              card: card,
              onTap: () => showRequestPreview(context, card),
            ),
            emptyBody: l.homeRequestsEmptyBody,
            emptyAction: l.homeCreateJourney,
            onEmptyAction: () => context.openJourneyCreate(),
            emptyIcon: Icons.inventory_2_outlined,
          );
  }

  Widget _frame<T>(
    BuildContext context, {
    required String title,
    required AsyncValue<DiscoveryPage<T>> value,
    required VoidCallback retry,
    required VoidCallback browse,
    required Widget Function(T card) card,
    required String emptyBody,
    required String emptyAction,
    required VoidCallback onEmptyAction,
    required IconData emptyIcon,
  }) {
    final l = L.of(context);
    // A tier staff switched off is absent, not an error and not a header over
    // nothing.
    if (value.ofCurrentAccount.value?.isDisabled ?? false) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: title,
          actionLabel: l.actionSeeAll,
          onAction: browse,
        ),
        CorridorChips(
          selected: _corridor,
          onSelected: (corridor) => setState(() => _corridor = corridor),
        ),
        const SizedBox(height: AppSpace.md),
        DiscoverySection<DiscoveryPage<T>>(
          value: value,
          onRetry: retry,
          data: (page) {
            if (page.results.isEmpty) {
              return AppEmptyState(
                title: _corridor == null
                    ? l.homeListingsEmptyTitle
                    : l.homeListingsEmptyRouteTitle,
                body: emptyBody,
                icon: emptyIcon,
                compact: true,
                actionLabel: emptyAction,
                onAction: onEmptyAction,
                secondaryLabel: _corridor == null ? null : l.corridorAll,
                onSecondary: _corridor == null
                    ? null
                    : () => setState(() => _corridor = null),
              );
            }
            return Column(
              children: [
                for (final item in page.results) ...[
                  card(item),
                  const SizedBox(height: AppSpace.md),
                ],
              ],
            );
          },
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// People
// ---------------------------------------------------------------------------

/// Members who opted in, on the side the viewer looks at. A sender sees
/// travelers, a traveler sees senders.
class PeopleSection extends ConsumerWidget {
  const PeopleSection({required this.isSender, super.key});

  final bool isSender;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final value = ref.watch(previewPeopleProvider(isSender));
    if (value.ofCurrentAccount.value?.isDisabled ?? false) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(
          title: isSender ? l.homePeopleSenderTitle : l.homePeopleTravelerTitle,
          actionLabel: l.actionSeeAll,
          onAction: () => context.openBrowsePeople(),
        ),
        DiscoverySection<DiscoveryPage<ProfileCard>>(
          value: value,
          onRetry: () => ref.invalidate(previewPeopleProvider(isSender)),
          skeleton: const PeopleSkeleton(),
          data: (page) => page.results.isEmpty
              ? AppEmptyState(
                  title: l.homePeopleEmptyTitle,
                  body: l.homePeopleEmptyBody,
                  icon: Icons.groups_2_outlined,
                  compact: true,
                )
              : HorizontalCards(
                  children: [
                    for (final card in page.results)
                      ProfileTile(
                        card: card,
                        onTap: card.id == null
                            ? null
                            : () => context.openPerson(card.id!),
                      ),
                  ],
                ),
        ),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Opt-in
// ---------------------------------------------------------------------------

/// The one-time card that offers a public profile (spec 4.3).
///
/// The server decides when it shows (`show_prompt`): profiles on, the member
/// has not chosen yet, is not hidden and has not said "Not now". It previews
/// the exact card others would see. A failed read simply leaves it out; it is
/// an offer, not content the page owes anyone.
class ProfileOptInCard extends ConsumerStatefulWidget {
  const ProfileOptInCard({super.key});

  @override
  ConsumerState<ProfileOptInCard> createState() => _ProfileOptInCardState();
}

class _ProfileOptInCardState extends ConsumerState<ProfileOptInCard> {
  bool _busy = false;

  Future<void> _choose({required bool show}) async {
    final l = L.of(context);
    setState(() => _busy = true);
    final controller = ref.read(ownProfileProvider.notifier);
    try {
      await (show
          ? controller.setDiscoverable(true)
          : controller.dismissPrompt());
      if (mounted && show) AppSnack.success(context, l.publicProfileOn);
    } on Object catch (error) {
      if (!mounted) return;
      AppSnack.failure(
        context,
        error,
        fallback: discoveryFailureMessage(context, error),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final profile = ref.watch(ownProfileProvider).ofCurrentAccount.value;
    if (profile == null ||
        !profile.showPrompt ||
        profile.state == OwnProfileState.disabled) {
      return const SizedBox.shrink();
    }

    return Padding(
      padding: const EdgeInsets.only(top: AppSpace.xl),
      child: AppInsetGroup(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              l.optInTitle,
              style: text.titleMedium?.copyWith(fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: AppSpace.xs),
            Text(
              l.optInBody,
              style: text.bodyMedium?.copyWith(color: c.textSecondary),
            ),
            const SizedBox(height: AppSpace.md),
            Text(
              l.optInPreviewLabel,
              style: text.labelMedium?.copyWith(color: c.textTertiary),
            ),
            const SizedBox(height: AppSpace.xs),
            ProfileTile(card: profile.card, width: null, onTap: null),
            const SizedBox(height: AppSpace.lg),
            AppButton(
              label: l.optInShow,
              isLoading: _busy,
              onPressed: _busy ? null : () => _choose(show: true),
            ),
            const SizedBox(height: AppSpace.sm),
            AppButton(
              label: l.optInNotNow,
              variant: AppButtonVariant.tertiary,
              onPressed: _busy ? null : () => _choose(show: false),
            ),
          ],
        ),
      ),
    );
  }
}
