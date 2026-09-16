/// Find Travelers — Senders browsing travellers going their way.
///
/// Every candidate on this screen is a **server verdict** from the frozen J4
/// contract `GET /api/matches/find-travelers`. The client does not rank, does
/// not filter, does not score, does not classify fit and does not price. It
/// renders what arrived.
///
/// Key UX requirements (ShipTrip J5):
/// - Compact, route-first candidate cards (~155dp UX target, ~3-4 visible on 390x844).
/// - Reusable inline route visualization preserving strict semantic travel order in RTL.
/// - Authoritative server actions for both `view_journey` and `propose_offer`.
/// - Match explanation sheet ("Why this trip fits") rendering backend match reasons.
/// - Redesigned proposal sheet displaying base reward, Additive Boost, and total reward.
/// - Safe state handling for `results`, `no_candidates`, `request_ineligible`, and errors.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart' show ChangeNotifierProvider;

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/money/money.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/find_travelers.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';
import 'checkout_section.dart';

// ---------------------------------------------------------------------------
// State Management
// ---------------------------------------------------------------------------

@immutable
class FindTravelersState {
  const FindTravelersState({
    required this.requestId,
    this.sort = 'best_match',
    this.page,
    this.candidates = const [],
    this.requestSummary,
    this.envelopeState = DiscoveryState.results,
    this.ineligibleReason,
    this.requestStatus,
    this.isLoadingMore = false,
    this.paginationError,
  });

  final int requestId;
  final String sort;
  final FindTravelersPage? page;
  final List<TravelerCandidate> candidates;
  final DiscoveryRequestSummary? requestSummary;
  final DiscoveryState envelopeState;
  final IneligibleReason? ineligibleReason;
  final String? requestStatus;
  final bool isLoadingMore;
  final Object? paginationError;

  bool get hasMore => page?.page.hasMore ?? false;
  int? get nextOffset => page?.page.nextOffset;
  int get total => page?.page.total ?? candidates.length;

  FindTravelersState copyWith({
    String? sort,
    FindTravelersPage? page,
    List<TravelerCandidate>? candidates,
    DiscoveryRequestSummary? requestSummary,
    DiscoveryState? envelopeState,
    IneligibleReason? ineligibleReason,
    String? requestStatus,
    bool? isLoadingMore,
    Object? paginationError,
    bool clearPaginationError = false,
  }) {
    return FindTravelersState(
      requestId: requestId,
      sort: sort ?? this.sort,
      page: page ?? this.page,
      candidates: candidates ?? this.candidates,
      requestSummary: requestSummary ?? this.requestSummary,
      envelopeState: envelopeState ?? this.envelopeState,
      ineligibleReason: ineligibleReason ?? this.ineligibleReason,
      requestStatus: requestStatus ?? this.requestStatus,
      isLoadingMore: isLoadingMore ?? this.isLoadingMore,
      paginationError: clearPaginationError
          ? null
          : (paginationError ?? this.paginationError),
    );
  }
}

class FindTravelersController extends ChangeNotifier {
  FindTravelersController({required this.requestId, required this.repository}) {
    loadInitial();
  }

  final int requestId;
  final MatchingRepository repository;

  bool isLoading = true;
  Object? initialError;
  FindTravelersState? state;

  Future<void> loadInitial() async {
    isLoading = true;
    initialError = null;
    notifyListeners();

    try {
      final response = await repository.findTravelers(
        parcelId: requestId,
        limit: 10,
        offset: 0,
        sort: 'best_match',
      );
      state = FindTravelersState(
        requestId: requestId,
        sort: response.sort.isEmpty ? 'best_match' : response.sort,
        page: response,
        candidates: response.candidates,
        requestSummary: response.request,
        envelopeState: response.state,
        ineligibleReason: response.reason,
        requestStatus: response.requestStatus,
      );
    } catch (error) {
      initialError = error;
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> refresh() async {
    final current = state;
    final sort = current?.sort ?? 'best_match';
    try {
      final response = await repository.findTravelers(
        parcelId: requestId,
        limit: 10,
        offset: 0,
        sort: sort,
      );
      state = FindTravelersState(
        requestId: requestId,
        sort: response.sort.isEmpty ? sort : response.sort,
        page: response,
        candidates: response.candidates,
        requestSummary: response.request,
        envelopeState: response.state,
        ineligibleReason: response.reason,
        requestStatus: response.requestStatus,
      );
      initialError = null;
    } catch (error) {
      if (state == null) {
        initialError = error;
      }
      // Retain existing results on refresh failure
    } finally {
      notifyListeners();
    }
  }

  Future<void> setSort(String newSort) async {
    final current = state;
    if (current == null || current.sort == newSort) return;

    isLoading = true;
    notifyListeners();

    try {
      final response = await repository.findTravelers(
        parcelId: requestId,
        limit: 10,
        offset: 0,
        sort: newSort,
      );
      state = FindTravelersState(
        requestId: requestId,
        sort: newSort,
        page: response,
        candidates: response.candidates,
        requestSummary: response.request,
        envelopeState: response.state,
        ineligibleReason: response.reason,
        requestStatus: response.requestStatus,
      );
      initialError = null;
    } catch (error) {
      initialError = error;
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loadMore() async {
    final current = state;
    if (current == null ||
        current.isLoadingMore ||
        !current.hasMore ||
        current.nextOffset == null) {
      return;
    }

    state = current.copyWith(isLoadingMore: true, clearPaginationError: true);
    notifyListeners();

    try {
      final response = await repository.findTravelers(
        parcelId: requestId,
        limit: 10,
        offset: current.nextOffset,
        sort: current.sort,
      );

      final existingIds = current.candidates.map((c) => c.journeyId).toSet();
      final deduplicatedNew = response.candidates
          .where((c) => !existingIds.contains(c.journeyId))
          .toList();

      state = current.copyWith(
        page: response,
        candidates: [...current.candidates, ...deduplicatedNew],
        requestSummary: response.request ?? current.requestSummary,
        isLoadingMore: false,
      );
    } catch (error) {
      state = current.copyWith(isLoadingMore: false, paginationError: error);
    } finally {
      notifyListeners();
    }
  }
}

final findTravelersControllerProvider = ChangeNotifierProvider.autoDispose
    .family<FindTravelersController, int>((ref, requestId) {
      return FindTravelersController(
        requestId: requestId,
        repository: ref.watch(matchingRepositoryProvider),
      );
    });

// ---------------------------------------------------------------------------
// Screen
// ---------------------------------------------------------------------------

class DiscoveryScreen extends ConsumerWidget {
  const DiscoveryScreen({required this.requestId, super.key});

  final int requestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final controller = ref.watch(findTravelersControllerProvider(requestId));

    return AppScaffold(
      topBar: AppTopBar(title: l.discoveryTravelersTitle, showBack: true),
      body: Builder(
        builder: (context) {
          if (controller.isLoading) {
            return ListView(
              padding: AppScrollPadding.page(context),
              children: const [_LoadingSkeleton()],
            );
          }

          if (controller.initialError != null && controller.state == null) {
            return Center(
              child: Padding(
                padding: AppScrollPadding.page(context),
                child: AppErrorState(
                  error: controller.initialError!,
                  onRetry: () => controller.refresh(),
                ),
              ),
            );
          }

          final state = controller.state;
          if (state == null) {
            return const SizedBox.shrink();
          }

          return switch (state.envelopeState) {
            DiscoveryState.noCandidates => _NoCandidatesView(
              requestId: requestId,
              onRefresh: () => controller.refresh(),
            ),
            DiscoveryState.requestIneligible => _IneligibleView(
              requestId: requestId,
              reason: state.ineligibleReason,
            ),
            DiscoveryState.results || DiscoveryState.unknown =>
              state.candidates.isEmpty
                  ? _NoCandidatesView(
                      requestId: requestId,
                      onRefresh: () => controller.refresh(),
                    )
                  : _CandidateListView(
                      state: state,
                      onRefresh: () => controller.refresh(),
                      onLoadMore: () => controller.loadMore(),
                      onSortChanged: (sort) => controller.setSort(sort),
                      onCandidateTap: (candidate) =>
                          _openTripDetail(context, ref, candidate, state),
                    ),
          };
        },
      ),
    );
  }

  Future<void> _openTripDetail(
    BuildContext context,
    WidgetRef ref,
    TravelerCandidate candidate,
    FindTravelersState state,
  ) async {
    // Authoritative check: view_journey action must be available
    if (!candidate.can(CandidateAction.viewJourney)) return;

    final outcome = await showAppSheet<_ProposeOutcome>(
      context,
      builder: (sheetContext) => _TripDetailSheet(
        candidate: candidate,
        requestSummary: state.requestSummary,
        onPropose: () =>
            _openProposeSheet(context, ref, candidate, state.requestSummary),
      ),
    );

    if (outcome == null || !context.mounted) return;

    if (outcome.staleCode != null) {
      ref.read(findTravelersControllerProvider(requestId)).refresh();
      return;
    }

    final matchId = outcome.matchId;
    if (matchId != null) {
      ref.read(findTravelersControllerProvider(requestId)).refresh();
      AppSnack.success(context, L.of(context).discoveryProposalSent);
      context.openNegotiation(matchId);
    }
  }

  Future<_ProposeOutcome?> _openProposeSheet(
    BuildContext context,
    WidgetRef ref,
    TravelerCandidate candidate,
    DiscoveryRequestSummary? requestSummary,
  ) async {
    // Authoritative check: propose_offer action must be available
    if (!candidate.can(CandidateAction.proposeOffer)) return null;

    final outcome = await showAppSheet<_ProposeOutcome>(
      context,
      builder: (sheetContext) =>
          _ProposeSheet(candidate: candidate, requestSummary: requestSummary),
    );

    if (outcome == null || !context.mounted) return null;

    if (outcome.staleCode != null) {
      ref.read(findTravelersControllerProvider(requestId)).refresh();
      return outcome;
    }

    final matchId = outcome.matchId;
    if (matchId != null) {
      ref.read(findTravelersControllerProvider(requestId)).refresh();
      AppSnack.success(context, L.of(context).discoveryProposalSent);
      context.openNegotiation(matchId);
    }
    return outcome;
  }
}

// ---------------------------------------------------------------------------
// Candidate List View with Sorting and Pagination
// ---------------------------------------------------------------------------

class _CandidateListView extends StatelessWidget {
  const _CandidateListView({
    required this.state,
    required this.onRefresh,
    required this.onLoadMore,
    required this.onSortChanged,
    required this.onCandidateTap,
  });

  final FindTravelersState state;
  final Future<void> Function() onRefresh;
  final VoidCallback onLoadMore;
  final ValueChanged<String> onSortChanged;
  final ValueChanged<TravelerCandidate> onCandidateTap;

  @override
  Widget build(BuildContext context) {
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: NotificationListener<ScrollNotification>(
        onNotification: (scrollInfo) {
          if (scrollInfo.metrics.pixels >=
                  scrollInfo.metrics.maxScrollExtent - 200 &&
              state.hasMore &&
              !state.isLoadingMore) {
            onLoadMore();
          }
          return false;
        },
        child: ListView.builder(
          padding: AppScrollPadding.page(context),
          itemCount: state.candidates.length + 2, // header + items + footer
          itemBuilder: (context, index) {
            if (index == 0) {
              return _SortHeader(
                currentSort: state.sort,
                total: state.total,
                onSortChanged: onSortChanged,
              );
            }

            final candidateIndex = index - 1;
            if (candidateIndex < state.candidates.length) {
              final candidate = state.candidates[candidateIndex];
              return Padding(
                padding: const EdgeInsets.only(bottom: AppSpace.md),
                child: _TravelerCard(
                  candidate: candidate,
                  onTap: candidate.can(CandidateAction.viewJourney)
                      ? () => onCandidateTap(candidate)
                      : null,
                ),
              );
            }

            // Footer / pagination indicator
            return _ListFooter(
              hasMore: state.hasMore,
              isLoadingMore: state.isLoadingMore,
              error: state.paginationError,
              onRetry: onLoadMore,
              onShowMore: onLoadMore,
            );
          },
        ),
      ),
    );
  }
}

class _SortHeader extends StatelessWidget {
  const _SortHeader({
    required this.currentSort,
    required this.total,
    required this.onSortChanged,
  });

  final String currentSort;
  final int total;
  final ValueChanged<String> onSortChanged;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.md),
      child: Wrap(
        alignment: WrapAlignment.spaceBetween,
        runAlignment: WrapAlignment.center,
        crossAxisAlignment: WrapCrossAlignment.center,
        spacing: AppSpace.sm,
        runSpacing: AppSpace.xs,
        children: [
          Text(
            '$total',
            style: text.labelMedium?.copyWith(
              color: c.textSecondary,
              fontWeight: FontWeight.w600,
            ),
          ),
          Wrap(
            spacing: AppSpace.xs,
            runSpacing: AppSpace.xs,
            children: [
              _SortPill(
                label: l.findTravelersSortBestMatch,
                isSelected: currentSort == 'best_match',
                onTap: () => onSortChanged('best_match'),
              ),
              _SortPill(
                label: l.findTravelersSortSoonest,
                isSelected: currentSort == 'soonest_departure',
                onTap: () => onSortChanged('soonest_departure'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _SortPill extends StatelessWidget {
  const _SortPill({
    required this.label,
    required this.isSelected,
    required this.onTap,
  });

  final String label;
  final bool isSelected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return Material(
      color: isSelected ? c.brand : c.surface,
      borderRadius: AppRadius.rPill,
      elevation: isSelected ? 0 : 0.5,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppRadius.rPill,
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
          decoration: BoxDecoration(
            borderRadius: AppRadius.rPill,
            border: Border.all(color: isSelected ? c.brand : c.hairline),
          ),
          child: Text(
            label,
            style: text.labelSmall?.copyWith(
              color: isSelected ? c.onBrand : c.textSecondary,
              fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
            ),
          ),
        ),
      ),
    );
  }
}

class _ListFooter extends StatelessWidget {
  const _ListFooter({
    required this.hasMore,
    required this.isLoadingMore,
    required this.error,
    required this.onRetry,
    required this.onShowMore,
  });

  final bool hasMore;
  final bool isLoadingMore;
  final Object? error;
  final VoidCallback onRetry;
  final VoidCallback onShowMore;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    if (isLoadingMore) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: AppSpace.lg),
        child: Center(
          child: SizedBox(
            width: 24,
            height: 24,
            child: CircularProgressIndicator(strokeWidth: 2.5),
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

    if (hasMore) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpace.sm),
        child: Center(
          child: AppButton(
            label: l.findTravelersShowMore,
            variant: AppButtonVariant.tertiary,
            expand: false,
            onPressed: onShowMore,
          ),
        ),
      );
    }

    return const SizedBox(height: AppSpace.xl);
  }
}

// ---------------------------------------------------------------------------
// Compact Candidate Card (~155dp UX target)
// ---------------------------------------------------------------------------

class _TravelerCard extends StatelessWidget {
  const _TravelerCard({required this.candidate, required this.onTap});

  final TravelerCandidate candidate;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final isRtl = context.isRtl;

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

    final displayName = traveler.displayName.isNotEmpty
        ? traveler.displayName
        : l.findTravelersViewTrip;

    return AppCard(
      onTap: onTap,
      padding: const EdgeInsets.all(AppSpace.md),
      semanticLabel: l.discoveryTravelersTitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          // Row 1 — Person: Avatar / Name / Rating or New
          Row(
            children: [
              AppAvatar(
                initials: _initial(traveler.displayName),
                name: displayName,
                size: 34,
                isVerified: traveler.identityVerified,
              ),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  displayName,
                  style: text.titleSmall?.copyWith(
                    fontWeight: FontWeight.w700,
                    color: c.textPrimary,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
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
                      color: _modeAccent(context, candidate.primaryMode),
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
                        color: c.brand,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(width: 2),
                    Icon(
                      isRtl
                          ? Icons.chevron_left_rounded
                          : Icons.chevron_right_rounded,
                      size: 16,
                      color: c.brand,
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

  static String _initial(String name) {
    final trimmed = name.trim();
    if (trimmed.isEmpty) return 'T';
    return trimmed.characters.first.toUpperCase();
  }

  static String _modeSummary(
    BuildContext context,
    TravelerCandidate candidate,
  ) {
    final modes = candidate.route.segments
        .map((s) => s.mode)
        .where((m) => m != TransportMode.unknown)
        .toSet();

    if (modes.contains(TransportMode.flight) &&
        modes.contains(TransportMode.drive)) {
      return '${transportModeLabel(context, TransportMode.flight)} + ${transportModeLabel(context, TransportMode.drive)}';
    }
    return transportModeLabel(context, candidate.primaryMode);
  }

  static Color _modeAccent(BuildContext context, TransportMode mode) {
    final c = context.colors;
    return switch (mode) {
      TransportMode.flight => c.modeFlight,
      TransportMode.drive => c.modeDrive,
      TransportMode.unknown => c.textTertiary,
    };
  }
}

class _RouteFitBadge extends StatelessWidget {
  const _RouteFitBadge({required this.routeFit});

  final RouteFit routeFit;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;

    final (label, tone) = switch (routeFit) {
      RouteFit.excellent => (l.findTravelersRouteFitExcellent, StatusTone.good),
      RouteFit.good => (l.findTravelersRouteFitGood, StatusTone.progress),
      RouteFit.compatible => (
        l.findTravelersRouteFitCompatible,
        StatusTone.neutral,
      ),
      RouteFit.unknown => (
        l.findTravelersRouteFitCompatible,
        StatusTone.neutral,
      ),
    };

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

// ---------------------------------------------------------------------------
// Candidate Detail / "View Trip" Sheet
// ---------------------------------------------------------------------------

class _TripDetailSheet extends StatelessWidget {
  const _TripDetailSheet({
    required this.candidate,
    required this.requestSummary,
    required this.onPropose,
  });

  final TravelerCandidate candidate;
  final DiscoveryRequestSummary? requestSummary;
  final VoidCallback onPropose;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final traveler = candidate.traveler;
    final canPropose = candidate.can(CandidateAction.proposeOffer);

    return AppSheet(
      title: l.findTravelersViewTrip,
      subtitle: traveler.displayName.isNotEmpty ? traveler.displayName : null,
      footer: AppButton(
        label: l.offerProposeTitle,
        onPressed: canPropose ? onPropose : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // Traveler Trust Block
          Container(
            padding: const EdgeInsets.all(AppSpace.md),
            decoration: BoxDecoration(
              color: c.surface,
              borderRadius: AppRadius.rMd,
              border: Border.all(color: c.hairline),
            ),
            child: Row(
              children: [
                AppAvatar(
                  initials: _TravelerCard._initial(traveler.displayName),
                  name: traveler.displayName,
                  size: 44,
                  isVerified: traveler.identityVerified,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Flexible(
                            child: Text(
                              traveler.displayName.isNotEmpty
                                  ? traveler.displayName
                                  : l.findTravelersViewTrip,
                              style: text.titleMedium?.copyWith(
                                fontWeight: FontWeight.w700,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          if (traveler.identityVerified) ...[
                            const SizedBox(width: AppSpace.xs),
                            Icon(
                              Icons.verified_rounded,
                              size: 16,
                              color: c.success,
                            ),
                          ],
                        ],
                      ),
                      const SizedBox(height: AppSpace.xxs),
                      Wrap(
                        crossAxisAlignment: WrapCrossAlignment.center,
                        spacing: AppSpace.xs,
                        runSpacing: AppSpace.xxs,
                        children: [
                          if (traveler.rating.hasScore) ...[
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Icon(
                                  Icons.star_rounded,
                                  size: 15,
                                  color: c.attention,
                                ),
                                const SizedBox(width: 2),
                                Text(
                                  traveler.rating.average!.toStringAsFixed(1),
                                  style: text.bodySmall?.copyWith(
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                Text(
                                  ' (${traveler.rating.count})',
                                  style: text.bodySmall?.copyWith(
                                    color: c.textTertiary,
                                  ),
                                ),
                              ],
                            ),
                          ] else
                            Text(
                              l.findTravelersNewTraveller,
                              style: text.bodySmall?.copyWith(
                                color: c.brandStrong,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          if (traveler.completedDeliveries > 0) ...[
                            Text(
                              '·',
                              style: text.bodySmall?.copyWith(
                                color: c.textTertiary,
                              ),
                            ),
                            Text(
                              l.findTravelersDeliveries(
                                traveler.completedDeliveries,
                              ),
                              style: text.bodySmall?.copyWith(
                                color: c.textSecondary,
                              ),
                            ),
                          ],
                        ],
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: AppSpace.lg),

          // Route Details
          _DetailedRouteStops(candidate: candidate),

          const SizedBox(height: AppSpace.lg),

          // Match Quality & Timing Fit
          Text(
            l.findTravelersWhyThisFits,
            style: text.titleSmall?.copyWith(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: AppSpace.sm),
          _WhyThisTripFits(
            candidate: candidate,
            requestSummary: requestSummary,
          ),

          if (!canPropose) ...[
            const SizedBox(height: AppSpace.md),
            InfoNotice(
              message: l.discoveryProposeBlocked,
              tone: StatusTone.waiting,
              icon: Icons.info_outline_rounded,
            ),
          ],
        ],
      ),
    );
  }
}

class _DetailedRouteStops extends StatelessWidget {
  const _DetailedRouteStops({required this.candidate});

  final TravelerCandidate candidate;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final stops = candidate.route.stops;

    return Container(
      padding: const EdgeInsets.all(AppSpace.md),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: AppRadius.rMd,
        border: Border.all(color: c.hairline),
      ),
      child: Column(
        children: [
          for (var i = 0; i < stops.length; i++) ...[
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Column(
                  children: [
                    Container(
                      width: 10,
                      height: 10,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: i == 0 || i == stops.length - 1
                            ? c.brand
                            : c.textTertiary,
                      ),
                    ),
                    if (i < stops.length - 1)
                      Container(width: 2, height: 32, color: c.hairlineStrong),
                  ],
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        stops[i].airportIata != null
                            ? '${stops[i].label} · ${stops[i].airportIata}'
                            : stops[i].label,
                        style: text.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: c.textPrimary,
                        ),
                      ),
                      if (stops[i].departAt != null)
                        Text(
                          LocaleFormats.dateTime(locale, stops[i].departAt!),
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                        )
                      else if (stops[i].arriveAt != null)
                        Text(
                          LocaleFormats.dateTime(locale, stops[i].arriveAt!),
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _WhyThisTripFits extends StatelessWidget {
  const _WhyThisTripFits({
    required this.candidate,
    required this.requestSummary,
  });

  final TravelerCandidate candidate;
  final DiscoveryRequestSummary? requestSummary;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final reasons = candidate.matchReasons;
    final items = <String>[];

    for (final reason in reasons) {
      final rendered = switch (reason.code) {
        'picks_up_in' =>
          reason.place != null ? l.findTravelersPicksUpIn(reason.place!) : null,
        'arrives_in' =>
          reason.place != null ? l.findTravelersArrivesIn(reason.place!) : null,
        'direct_leg' => l.findTravelersDirectLeg,
        'transfers' =>
          reason.count != null ? l.findTravelersTransfers(reason.count!) : null,
        'whole_trip_matches' => l.findTravelersWholeTripMatches,
        'arrives_before_deadline' =>
          reason.arrivesAt != null && reason.deadlineAt != null
              ? l.findTravelersArrivesBeforeDeadline(
                  LocaleFormats.dateTime(locale, reason.arrivesAt!),
                  LocaleFormats.dateTime(locale, reason.deadlineAt!),
                )
              : null,
        'has_room_for' =>
          reason.weightKg != null
              ? l.findTravelersHasRoomFor(reason.weightKg!)
              : null,
        'identity_verified' => l.findTravelersIdentityVerified,
        'flight_proof_approved' => l.findTravelersFlightProofApproved,
        // Unknown future code safely ignored per specification
        _ => null,
      };
      if (rendered != null && !items.contains(rendered)) {
        items.add(rendered);
      }
    }

    // Add timing fit label if not already present
    if (candidate.timingFit != null) {
      final timingText = switch (candidate.timingFit!) {
        TimingFit.comfortable => l.findTravelersTimingComfortable,
        TimingFit.fits => l.findTravelersTimingFits,
        TimingFit.unknown => null,
      };
      if (timingText != null && !items.contains(timingText)) {
        items.add(timingText);
      }
    }

    if (items.isEmpty) {
      return const SizedBox.shrink();
    }

    return Container(
      padding: const EdgeInsets.all(AppSpace.md),
      decoration: BoxDecoration(
        color: c.surface,
        borderRadius: AppRadius.rMd,
        border: Border.all(color: c.hairline),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final item in items)
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 3),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Icon(
                      Icons.check_circle_rounded,
                      size: 16,
                      color: c.success,
                    ),
                  ),
                  const SizedBox(width: AppSpace.sm),
                  Expanded(
                    child: Text(
                      item,
                      style: text.bodyMedium?.copyWith(color: c.textSecondary),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Propose Sheet with Additive Boost
// ---------------------------------------------------------------------------

@immutable
class _ProposeOutcome {
  const _ProposeOutcome.sent(this.matchId) : staleCode = null;
  const _ProposeOutcome.stale(this.staleCode) : matchId = null;

  final int? matchId;
  final ApiErrorCode? staleCode;
}

class _ProposeSheet extends ConsumerStatefulWidget {
  const _ProposeSheet({required this.candidate, required this.requestSummary});

  final TravelerCandidate candidate;
  final DiscoveryRequestSummary? requestSummary;

  @override
  ConsumerState<_ProposeSheet> createState() => _ProposeSheetState();
}

class _ProposeSheetState extends ConsumerState<_ProposeSheet> {
  final _reward = TextEditingController();
  bool _busy = false;
  String? _rewardError;
  String? _notice;

  @override
  void initState() {
    super.initState();
    final suggested =
        widget.candidate.economics?.recommendedReward ??
        widget.candidate.economics?.minimumReward ??
        widget.requestSummary?.totalOfferedRewardEurCents;
    if (suggested != null) {
      _reward.text = amountFieldText(Money.eurCents(suggested));
    }
  }

  @override
  void dispose() {
    _reward.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final l = L.of(context);
    final target = widget.candidate.proposal;
    final cents = AppAmountField.centsOf(_reward);

    if (target == null) {
      setState(() => _notice = l.discoveryProposeBlocked);
      return;
    }
    if (cents == null || cents <= 0) {
      setState(() => _rewardError = l.validationMustBePositive);
      return;
    }

    setState(() {
      _busy = true;
      _rewardError = null;
      _notice = null;
    });

    try {
      final offer = await ref
          .read(matchingRepositoryProvider)
          .propose(
            parcelId: widget.requestSummary?.id ?? target.journeyId,
            journeyId: target.journeyId,
            startLegId: target.startLegId,
            endLegId: target.endLegId,
            travelerRewardEurCents: cents,
          );
      if (!mounted) return;
      refreshVolatileState(ref);
      Navigator.of(context).pop(_ProposeOutcome.sent(offer.matchId));
    } on ApiException catch (error) {
      if (!mounted) return;
      _handle(error);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _handle(ApiException error) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    // Floor moved: correct the field directly
    if (error.code == ApiErrorCode.rewardBelowMinimum) {
      final minimum = error.intExtra('minimum_reward_eur_cents');
      setState(
        () => _rewardError = minimum == null
            ? l.staleRewardBelowMinimum
            : l.offerBelowMinimum(Money.eurCents(minimum).format(locale)),
      );
      return;
    }

    // Known authoritative conflict/stale causes
    final closing = switch (error.code) {
      ApiErrorCode.capacityExceeded => l.staleCapacityExceeded,
      ApiErrorCode.requestNotOpen => l.staleRequestNotOpen,
      ApiErrorCode.requestAlreadyMatched => l.staleRequestAlreadyMatched,
      ApiErrorCode.journeyNotActive => l.staleJourneyNotActive,
      ApiErrorCode.invalidLegRange => l.discoveryLegRangeMoved,
      ApiErrorCode.incompatibleCandidate => l.discoveryIncompatibleCount(
        error.stringListExtra('rejection_codes').length,
      ),
      _ => null,
    };

    if (closing != null) {
      AppSnack.info(context, closing);
      Navigator.of(context).pop(_ProposeOutcome.stale(error.code));
      return;
    }

    // Safe fallback for unmapped 409 conflict or stale response
    if (error.statusCode == 409 || error.code.impliesStaleClientState) {
      AppSnack.info(context, staleMessage(context, error.code));
      Navigator.of(context).pop(_ProposeOutcome.stale(error.code));
      return;
    }

    AppSnack.failure(context, error);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final traveler = widget.candidate.traveler;
    final economics = widget.candidate.economics;
    final request = widget.requestSummary;
    final canPropose = widget.candidate.proposal != null;

    final hasBoost = request != null && request.boostEurCents > 0;
    final minimumReward = economics?.minimumReward != null
        ? Money.eurCents(economics!.minimumReward!)
        : null;
    final recommendedReward = economics?.recommendedReward != null
        ? Money.eurCents(economics!.recommendedReward!)
        : null;

    return AppSheet(
      title: l.offerProposeTitle,
      subtitle: traveler.displayName.isNotEmpty ? traveler.displayName : null,
      footer: AppButton(
        label: l.offerSend,
        isLoading: _busy,
        onPressed: canPropose ? _send : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (_notice != null) ...[
            InfoNotice(
              message: _notice!,
              tone: StatusTone.waiting,
              icon: Icons.sync_problem_rounded,
            ),
            const SizedBox(height: AppSpace.md),
          ],

          // Route Summary
          InlineRoute(
            stops: widget.candidate.route.stops
                .map(
                  (s) => InlineRouteStop(
                    label: s.label,
                    airportIata: s.airportIata,
                  ),
                )
                .toList(),
          ),

          const SizedBox(height: AppSpace.lg),

          // Additive Boost Breakdown (when boost is present)
          if (hasBoost) ...[
            Container(
              padding: const EdgeInsets.all(AppSpace.md),
              decoration: BoxDecoration(
                color: c.brandSoft,
                borderRadius: AppRadius.rMd,
                border: Border.all(color: c.brand.withValues(alpha: 0.2)),
              ),
              child: Column(
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        l.moneyBaseReward,
                        style: text.bodySmall?.copyWith(color: c.textSecondary),
                      ),
                      Text(
                        Money.eurCents(
                          request.chosenRewardEurCents,
                        ).format(locale),
                        style: text.bodySmall?.copyWith(
                          fontWeight: FontWeight.w600,
                          color: c.textPrimary,
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpace.xxs),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        l.boostTitle,
                        style: text.bodySmall?.copyWith(color: c.brandStrong),
                      ),
                      Text(
                        '+${Money.eurCents(request.boostEurCents).format(locale)}',
                        style: text.bodySmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: c.brandStrong,
                        ),
                      ),
                    ],
                  ),
                  const Divider(height: 16),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        l.moneyTravelerReceives,
                        style: text.bodyMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: c.textPrimary,
                        ),
                      ),
                      Text(
                        Money.eurCents(
                          request.totalOfferedRewardEurCents,
                        ).format(locale),
                        style: text.titleSmall?.copyWith(
                          fontWeight: FontWeight.w700,
                          color: c.brandStrong,
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpace.lg),
          ],

          // Amount Field
          AppAmountField(
            label: l.offerRewardLabel,
            controller: _reward,
            helper: minimumReward == null
                ? null
                : l.offerBelowMinimum(minimumReward.format(locale)),
            errorText: _rewardError,
            enabled: !_busy,
            onChanged: (_) => setState(() {}),
          ),

          if (recommendedReward != null) ...[
            const SizedBox(height: AppSpace.xs),
            AppButton(
              label: l.offerUseRecommended,
              variant: AppButtonVariant.tertiary,
              expand: false,
              onPressed: () => setState(
                () => _reward.text = amountFieldText(recommendedReward),
              ),
            ),
          ],

          const SizedBox(height: AppSpace.md),

          // Authoritative Economics Breakdown
          _EconomicsBreakdown(
            economics: economics,
            entered: AppAmountField.centsOf(_reward),
          ),
        ],
      ),
    );
  }
}

class _EconomicsBreakdown extends StatelessWidget {
  const _EconomicsBreakdown({required this.economics, required this.entered});

  final CandidateEconomics? economics;
  final int? entered;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final econ = economics;
    if (econ == null) return const SizedBox.shrink();

    // Consume authoritative server economics block
    final matchesMin = entered != null && entered == econ.minimumReward;
    final block = matchesMin
        ? econ.minimumEconomics
        : econ.recommendedEconomics ?? econ.minimumEconomics;
    if (block == null) return const SizedBox.shrink();

    final travelerReward = Money.eurCentsOrNull(block['traveler_reward_minor']);
    final platformFee = Money.eurCentsOrNull(block['platform_fee_minor']);
    final senderTotal = Money.eurCentsOrNull(block['sender_total_minor']);

    final matchesEntered =
        entered != null && entered == travelerReward?.minorUnits;

    return MoneyBreakdown(
      title: l.moneyBreakdownTitle,
      explainer: matchesEntered
          ? l.moneyRewardNotReduced
          : l.discoveryBreakdownNote,
      lines: [
        if (travelerReward != null)
          MoneyLine(label: l.moneyTravelerReceives, amount: travelerReward),
        if (platformFee != null)
          MoneyLine(label: l.moneyPlatformFee, amount: platformFee),
        if (senderTotal != null)
          MoneyLine.total(label: l.moneyYouPay, amount: senderTotal),
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// Screen State Views (No candidates, Ineligible, Loading)
// ---------------------------------------------------------------------------

class _NoCandidatesView extends StatelessWidget {
  const _NoCandidatesView({required this.requestId, required this.onRefresh});

  final int requestId;
  final VoidCallback onRefresh;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    // Per J5 instruction: DO NOT show "Boost request" here.
    // Boost does not create compatibility or alter traveler ordering on Find Travelers.
    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        AppEmptyState(
          title: l.findTravelersEmptyTitle,
          body: l.findTravelersEmptyBody,
          icon: Icons.travel_explore_rounded,
          actionLabel: l.actionBack,
          onAction: () => context.openRequest(requestId),
          secondaryLabel: l.actionRefresh,
          onSecondary: onRefresh,
        ),
      ],
    );
  }
}

class _IneligibleView extends StatelessWidget {
  const _IneligibleView({required this.requestId, required this.reason});

  final int requestId;
  final IneligibleReason? reason;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);

    final (title, body, actionLabel, onAction) = switch (reason) {
      IneligibleReason.awaitingDeposit => (
        l.depositTitle,
        l.findTravelersIneligibleAwaitingDeposit,
        l.actionContinue,
        () => context.openDeposit(requestId),
      ),
      IneligibleReason.alreadyMatched => (
        l.findTravelersIneligibleAlreadyMatched,
        '',
        l.actionBack,
        () => context.openRequest(requestId),
      ),
      IneligibleReason.closed => (
        l.findTravelersIneligibleClosed,
        '',
        l.actionBack,
        () => context.openRequest(requestId),
      ),
      IneligibleReason.inProgress => (
        l.findTravelersIneligibleInProgress,
        '',
        l.actionBack,
        () => context.openRequest(requestId),
      ),
      null || IneligibleReason.unknown => (
        l.findTravelersIneligibleClosed,
        '',
        l.actionBack,
        () => context.openRequest(requestId),
      ),
    };

    return ListView(
      padding: AppScrollPadding.page(context),
      children: [
        AppEmptyState(
          title: title,
          body: body,
          icon: switch (reason) {
            IneligibleReason.awaitingDeposit => Icons.payment_rounded,
            IneligibleReason.alreadyMatched => Icons.handshake_rounded,
            IneligibleReason.inProgress => Icons.local_shipping_rounded,
            _ => Icons.block_rounded,
          },
          actionLabel: actionLabel,
          onAction: onAction,
        ),
      ],
    );
  }
}

class _LoadingSkeleton extends StatelessWidget {
  const _LoadingSkeleton();

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        for (var i = 0; i < 4; i++) ...[
          const AppCard(
            padding: EdgeInsets.all(AppSpace.md),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    SkeletonBox(width: 34, height: 34, radius: AppRadius.rPill),
                    SizedBox(width: AppSpace.sm),
                    SkeletonBox(width: 100, height: 16),
                    Spacer(),
                    SkeletonBox(width: 40, height: 16),
                  ],
                ),
                SizedBox(height: AppSpace.md),
                SkeletonBox(width: 200, height: 16),
                SizedBox(height: AppSpace.md),
                Row(
                  children: [
                    SkeletonBox(width: 120, height: 14),
                    Spacer(),
                    SkeletonBox(width: 80, height: 14),
                  ],
                ),
                SizedBox(height: AppSpace.sm),
                Row(
                  children: [
                    SkeletonBox(width: 70, height: 12),
                    Spacer(),
                    SkeletonBox(width: 60, height: 12),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: AppSpace.md),
        ],
      ],
    );
  }
}
