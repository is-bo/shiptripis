/// One journey.
///
/// Three jobs, in the order a traveller needs them:
///
/// 1. **Show the route as a route.** The `RouteLine` motif, with each leg's
///    mode, times, capacity and — for a flight — its proof state.
/// 2. **Say precisely why it cannot go live yet.** Publishing is gated on
///    approved proof for every flight leg and on current KYC, and both of
///    those are actionable. A "Publish" button that fails with a shrug is
///    worse than no button.
/// 3. **Show what is out there**, without lying about what the traveller can
///    do with it. In V1 the **sender proposes first**: a traveller cannot
///    offer on a request. So the compatible-requests list is informational,
///    and says so, instead of rendering a dead "Apply".
///
/// The leg projection differs by viewer: the owner gets `distance_meters`, a
/// counterparty gets a `distance_band` in its place. `JourneyLeg.isOwnerView`
/// records which arrived, and this screen branches rather than assuming.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/discovery.dart';
import '../../domain/journey.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';
import 'journey_labels.dart';

final _compatibleRequestsProvider = FutureProvider.autoDispose
    .family<DiscoveryResults, int>((ref, journeyId) async {
      final repo = ref.watch(matchingRepositoryProvider);
      return repo.compatibleRequests(journeyId: journeyId);
    });

class JourneyDetailScreen extends ConsumerStatefulWidget {
  const JourneyDetailScreen({required this.journeyId, super.key});

  final int journeyId;

  @override
  ConsumerState<JourneyDetailScreen> createState() =>
      _JourneyDetailScreenState();
}

class _JourneyDetailScreenState extends ConsumerState<JourneyDetailScreen> {
  bool _busy = false;

  Future<void> _publish() async {
    setState(() => _busy = true);
    final l = L.of(context);
    try {
      await ref.read(journeyRepositoryProvider).publish(widget.journeyId);
      if (!mounted) return;
      ref.invalidate(journeyDetailProvider(widget.journeyId));
      refreshVolatileState(ref);
      AppSnack.success(context, l.journeyPublished);
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(context, error, fallback: _publishFailure(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Every publish refusal is a specific, fixable thing. Mapping them one by
  /// one is what turns a 409 into an instruction.
  String? _publishFailure(ApiException error) {
    final l = L.of(context);
    return switch (error.code.raw) {
      'journey_status_not_publishable' => l.journeyErrorNotPublishable,
      'journey_has_no_legs' => l.journeyErrorNoLegs,
      'journey_leg_positions_invalid' => l.journeyErrorLegPositions,
      'journey_endpoints_mismatch' => l.journeyErrorEndpointsMismatch,
      'journey_leg_endpoints_invalid' => l.journeyErrorLegEndpoints,
      'journey_leg_time_invalid' => l.journeyErrorLegTime,
      'journey_legs_disconnected' => l.journeyErrorLegsDisconnected,
      'journey_leg_time_order_invalid' => l.journeyErrorLegTimeOrder,
      'journey_leg_mode_unavailable' => l.routeErrorModeUnavailable,
      'traveler_kyc_not_approved' => l.kycRequiredForJourney,
      'flight_proof_not_approved' => l.journeyPublishBlockedProof,
      'journey_not_owned' => l.journeyErrorNotOwned,
      _ => null,
    };
  }

  Future<void> _cancel() async {
    final l = L.of(context);
    final confirmed = await confirmAction(
      context,
      title: l.journeyCancelConfirmTitle,
      body: l.journeyCancelConfirmBody,
      confirmLabel: l.journeyCancel,
      isDestructive: true,
    );
    if (!confirmed || !mounted) return;

    setState(() => _busy = true);
    try {
      final result = await ref
          .read(journeyRepositoryProvider)
          .cancel(widget.journeyId);
      if (!mounted) return;
      ref.invalidate(journeyDetailProvider(widget.journeyId));
      refreshVolatileState(ref);
      // The released reservations are a real consequence for other people's
      // deliveries, so they are reported rather than swallowed.
      AppSnack.success(
        context,
        result.releasedAllocations > 0
            ? l.journeyReleasedAllocations(result.releasedAllocations)
            : l.journeyCancelled,
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      AppSnack.failure(
        context,
        error,
        fallback: switch (error.code.raw) {
          'journey_not_cancellable' => l.journeyErrorNotCancellable,
          'journey_has_funded_deal' => l.journeyErrorHasFundedDeal,
          'journey_not_owned' => l.journeyErrorNotOwned,
          _ => null,
        },
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// Why the edit button is inert, in the traveller's terms.
  String _editBlockedReason(Journey journey) {
    final l = L.of(context);
    return switch (journey.editBlockedCode) {
      'journey_has_dependent_state' => l.journeyEditBlockedDependent,
      'journey_not_owned' => l.journeyErrorNotOwned,
      _ => l.journeyEditBlockedStatus,
    };
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final journey = ref.watch(journeyDetailProvider(widget.journeyId));

    return AppScaffold(
      topBar: AppTopBar(title: l.journeyTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async =>
            ref.invalidate(journeyDetailProvider(widget.journeyId)),
        child: AsyncView<Journey>(
          value: journey,
          onRetry: () =>
              ref.invalidate(journeyDetailProvider(widget.journeyId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (data) {
            final isOwner = account != null && data.travelerId == account.id;
            final needProof = data.legsNeedingProof;
            final kycOk = account?.isKycVerified ?? false;

            return ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                _Header(journey: data),
                const SizedBox(height: AppSpace.xl),

                if (isOwner && data.status.isEditable) ...[
                  _Blockers(
                    legsNeedingProof: needProof,
                    kycVerified: kycOk,
                    journeyId: data.id,
                  ),
                  const SizedBox(height: AppSpace.xl),
                ],

                Row(
                  children: [
                    Expanded(child: SectionHeader(title: l.journeyRouteShape)),
                    if (isOwner && data.editable != null)
                      AppButton(
                        label: l.journeyEditAction,
                        icon: Icons.edit_outlined,
                        variant: AppButtonVariant.tertiary,
                        expand: false,
                        // Present but inert when the server says no, with the
                        // reason underneath. A button that vanishes explains
                        // nothing to the traveller looking for it.
                        onPressed: data.canEdit && !_busy
                            ? () => context.openJourneyEdit(data.id)
                            : null,
                      ),
                  ],
                ),
                if (isOwner && data.editable == false) ...[
                  InfoNotice(
                    message: _editBlockedReason(data),
                    tone: StatusTone.neutral,
                    icon: Icons.lock_outline_rounded,
                  ),
                  const SizedBox(height: AppSpace.md),
                ],
                _Route(journey: data),

                if (data.notes.isNotEmpty) ...[
                  const SizedBox(height: AppSpace.xl),
                  SectionHeader(title: l.journeyNotesLabel),
                  AppInsetGroup(
                    child: Text(
                      data.notes,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                ],

                if (isOwner && data.status.isLive) ...[
                  const SizedBox(height: AppSpace.xl),
                  _CompatibleRequests(journeyId: data.id),
                ],

                if (isOwner && !data.status.isFinished) ...[
                  const SizedBox(height: AppSpace.xxl),
                  AppButton(
                    label: l.journeyCancel,
                    variant: AppButtonVariant.destructive,
                    onPressed: _busy ? null : _cancel,
                  ),
                ],
              ],
            );
          },
        ),
      ),
      footer: _publishFooter(journey.value, account?.isKycVerified ?? false),
    );
  }

  Widget? _publishFooter(Journey? journey, bool kycVerified) {
    if (journey == null || !journey.status.isEditable) return null;
    final l = L.of(context);
    final blocked = journey.legsNeedingProof.isNotEmpty || !kycVerified;

    return AppButton(
      label: l.journeyPublish,
      isLoading: _busy,
      // Disabled rather than hidden: the traveller should see that publishing
      // is the goal, and the blockers above say what stands in the way.
      onPressed: blocked ? null : _publish,
    );
  }
}

class _Header extends StatelessWidget {
  const _Header({required this.journey});

  final Journey journey;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final copy = journeyStatusCopy(context, journey.status);
    final locale = Localizations.localeOf(context);
    final departure = journey.firstDeparture;

    return AppCard(
      accent: copy.tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  l.journeyLegCount(journey.legs.length),
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: context.colors.textTertiary,
                  ),
                ),
              ),
              StatusPill(
                label: copy.label,
                tone: copy.tone,
                icon: copy.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.md),
          RouteSummary(
            from: journeyStartLabel(journey),
            to: journeyDestinationLabel(journey),
          ),
          if (departure != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              LocaleFormats.dateTime(locale, departure),
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ],
          if (journey.status.isEditable) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              l.journeyDraftNextSteps,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textTertiary,
              ),
            ),
          ],
        ],
      ),
    );
  }
}

/// Everything standing between this journey and being live.
class _Blockers extends StatelessWidget {
  const _Blockers({
    required this.legsNeedingProof,
    required this.kycVerified,
    required this.journeyId,
  });

  final List<JourneyLeg> legsNeedingProof;
  final bool kycVerified;
  final int journeyId;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    if (legsNeedingProof.isEmpty && kycVerified) {
      return const SizedBox.shrink();
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (!kycVerified) ...[
          InfoNotice(
            message: l.kycRequiredForJourney,
            tone: StatusTone.action,
            icon: Icons.verified_user_outlined,
            actionLabel: l.kycStartAction,
            onAction: () => context.openKyc(),
          ),
          const SizedBox(height: AppSpace.md),
        ],
        if (legsNeedingProof.isNotEmpty) ...[
          SectionHeader(
            title: l.journeyLegsNeedProofTitle,
            subtitle: l.journeyPublishBlockedProof,
          ),
          for (final leg in legsNeedingProof) ...[
            AppCard(
              accent: StatusTone.action,
              onTap: () => context.openLegProof(journeyId, leg.id),
              child: Row(
                children: [
                  Icon(
                    Icons.flight_takeoff_rounded,
                    size: 20,
                    color: context.colors.modeFlight,
                  ),
                  const SizedBox(width: AppSpace.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          l.proofLegLabel(
                            leg.position + 1,
                            legOriginLabel(leg),
                            legDestinationLabel(leg),
                          ),
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        const SizedBox(height: AppSpace.xxs),
                        Text(
                          _proofLabel(context, leg.proofStatus),
                          style: Theme.of(context).textTheme.bodySmall
                              ?.copyWith(color: context.colors.textSecondary),
                        ),
                      ],
                    ),
                  ),
                  Icon(
                    Icons.chevron_right_rounded,
                    size: 20,
                    color: context.colors.textTertiary,
                  ),
                ],
              ),
            ),
            const SizedBox(height: AppSpace.md),
          ],
        ],
      ],
    );
  }

  String _proofLabel(BuildContext context, ProofStatus status) {
    final l = L.of(context);
    return switch (status) {
      ProofStatus.approved => l.proofStatusApproved,
      ProofStatus.pending => l.proofStatusPending,
      ProofStatus.rejected => l.proofStatusRejected,
      ProofStatus.unknown => l.proofStatusMissing,
    };
  }
}

class _Route extends StatelessWidget {
  const _Route({required this.journey});

  final Journey journey;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final legs = journey.legs;
    if (legs.isEmpty) {
      return AppEmptyState(
        title: l.journeyEmptyLegsTitle,
        body: l.journeyEmptyLegsBody,
        icon: Icons.route_rounded,
        compact: true,
      );
    }

    // N legs join N+1 stops: every leg's origin, plus the final destination.
    // Each stop carries its own context line — "Jijel Wilaya", "Paris
    // department" — so a route of four unfamiliar names is readable without
    // decoding the cards underneath it.
    final stops = <RouteStop>[
      for (final leg in legs)
        RouteStop(
          label: legOriginLabel(leg),
          detail: endpointContext(context, leg.originPlace, leg.origin),
          timeLabel: leg.departAt == null
              ? null
              : '${l.journeyDeparts} '
                    '${LocaleFormats.dateTime(locale, leg.departAt!)}',
        ),
      RouteStop(
        label: legDestinationLabel(legs.last),
        detail: endpointContext(
          context,
          legs.last.destinationPlace,
          legs.last.destination,
        ),
        timeLabel: legs.last.arriveAt == null
            ? null
            : '${l.journeyArrives} '
                  '${LocaleFormats.dateTime(locale, legs.last.arriveAt!)}',
      ),
    ];

    final segments = [
      for (final leg in legs)
        RouteSegment(
          mode: leg.mode,
          modeLabel: transportModeLabel(context, leg.mode),
          detail: _legDetail(context, leg),
          capacityLabel: formatCapacity(context, leg.capacityKg),
          // A flight whose proof was refused carries a state of its own, and
          // the connector is where that belongs.
          tone: leg.proofStatus == ProofStatus.rejected
              ? StatusTone.bad
              : (leg.needsProof ? StatusTone.action : null),
        ),
    ];

    return RouteLine(stops: stops, segments: segments);
  }

  /// Flight number for a flight; the distance the viewer is entitled to for a
  /// drive — exact metres for the owner, a band for anyone else.
  String? _legDetail(BuildContext context, JourneyLeg leg) {
    if (leg.flightNumber.isNotEmpty) return leg.flightNumber;
    if (leg.isOwnerView && leg.distanceMeters != null) {
      return '${(leg.distanceMeters! / 1000).round()} km';
    }
    if (leg.distanceBand != null) {
      return formatDistanceBand(context, leg.distanceBand);
    }
    return null;
  }
}

/// Parcels this journey could carry.
///
/// Read-only by design: in V1 the sender proposes first, so there is nothing
/// for the traveller to press here. Saying that plainly is better than an
/// affordance that does not exist.
class _CompatibleRequests extends ConsumerWidget {
  const _CompatibleRequests({required this.journeyId});

  final int journeyId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final results = ref.watch(_compatibleRequestsProvider(journeyId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.discoveryRequestsTitle),
        InfoNotice(
          title: l.journeyMatchesInfoTitle,
          message: l.journeyMatchesInfoBody,
          icon: Icons.info_outline_rounded,
        ),
        const SizedBox(height: AppSpace.md),
        AsyncView<DiscoveryResults>(
          value: results,
          onRetry: () => ref.invalidate(_compatibleRequestsProvider(journeyId)),
          loading: () => const SkeletonCardList(count: 2),
          error: (error) => InlineFailure(
            error: error,
            onRetry: () =>
                ref.invalidate(_compatibleRequestsProvider(journeyId)),
          ),
          data: (data) {
            if (data.candidates.isEmpty) {
              return AppEmptyState(
                title: l.discoveryEmptyRequestsTitle,
                body: l.discoveryEmptyRequestsBody,
                icon: Icons.inventory_2_outlined,
                compact: true,
              );
            }
            return Column(
              children: [
                for (final candidate in data.candidates) ...[
                  _CandidateCard(candidate: candidate),
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

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({required this.candidate});

  final DiscoveryCandidate candidate;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final request = candidate.request;
    final pricing = candidate.pricing;
    if (request == null) return const SizedBox.shrink();

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RouteSummary(
            from: request.pickup?.coarseLabel ?? '',
            to: request.delivery?.coarseLabel ?? '',
          ),
          const SizedBox(height: AppSpace.md),
          Wrap(
            spacing: AppSpace.md,
            runSpacing: AppSpace.xs,
            children: [
              if (request.actualWeightKg != null)
                Text(
                  formatWeight(context, request.actualWeightKg),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
              if (candidate.compatibility != null)
                Text(
                  formatDetour(
                    context,
                    candidate.compatibility!.totalAddedDistance,
                  ),
                  style: text.bodySmall?.copyWith(color: c.textSecondary),
                ),
              if (request.deadlineAt != null)
                Text(
                  LocaleFormats.dayMonth(locale, request.deadlineAt!),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
            ],
          ),
          // The traveller sees the enforced floor. The server deliberately
          // withholds the recommendation from this endpoint, so nothing here
          // shows or implies one.
          if (pricing?.minimumReward != null) ...[
            const SizedBox(height: AppSpace.md),
            Text(
              '${l.moneyMinimumReward}: '
              '${pricing!.minimumReward!.format(locale)}',
              style: text.labelMedium?.copyWith(color: c.textSecondary),
            ),
          ],
        ],
      ),
    );
  }
}
