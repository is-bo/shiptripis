/// Travellers who can carry this parcel.
///
/// Every candidate on this screen is a **server verdict**. The client does not
/// rank, does not filter, does not score and does not price; it renders what
/// `compatible-journeys` returned and, where the server refused a candidate,
/// says how many reasons there were rather than reciting machine codes at a
/// human.
///
/// This is the one discovery endpoint that carries a recommendation, because
/// the sender is the party who proposes. So the floor (`minimum_reward`) and
/// the suggestion (`recommended_reward`) both appear, and the amount field is
/// pre-filled with the suggestion — a sender staring at an empty box will
/// under-offer and wonder why nobody answers.
///
/// The proposal echoes `start_leg_id`/`end_leg_id` back exactly as they
/// arrived. The server recomputes the sub-route and refuses a mismatch with
/// `invalid_leg_range`, which is not an error to apologise for but a signal
/// that the list is stale — so it refreshes.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

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
import '../../domain/discovery.dart';
import '../../domain/location.dart';
import '../../l10n/app_localizations.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';
import 'checkout_section.dart';

/// Local to this screen on purpose: a compatibility list is only meaningful
/// while the sender is looking at it, and caching it in the shared read model
/// would let a sender propose against capacity that has since gone.
final _compatibleJourneysProvider = FutureProvider.autoDispose
    .family<DiscoveryResults, int>((ref, parcelId) async {
      final repo = ref.watch(matchingRepositoryProvider);
      return repo.compatibleJourneys(parcelId: parcelId);
    });

class DiscoveryScreen extends ConsumerWidget {
  const DiscoveryScreen({required this.requestId, super.key});

  final int requestId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final results = ref.watch(_compatibleJourneysProvider(requestId));

    void refresh() => ref.invalidate(_compatibleJourneysProvider(requestId));

    return AppScaffold(
      topBar: AppTopBar(title: l.discoveryTravelersTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async => refresh(),
        child: AsyncView<DiscoveryResults>(
          value: results,
          onRetry: refresh,
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonCardList()],
          ),
          data: (data) {
            if (data.candidates.isEmpty) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.discoveryEmptyTravelersTitle,
                    body: l.discoveryEmptyTravelersBody,
                    icon: Icons.travel_explore_rounded,
                    actionLabel: l.boostTitle,
                    onAction: () => context.openBoost(requestId),
                    secondaryLabel: l.actionRefresh,
                    onSecondary: refresh,
                  ),
                ],
              );
            }

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                for (final candidate in data.candidates) ...[
                  _CandidateCard(
                    candidate: candidate,
                    onPropose: () => _propose(context, ref, candidate),
                  ),
                  const SizedBox(height: AppSpace.md),
                ],
                const SizedBox(height: AppSpace.lg),
                AppButton(
                  label: l.boostTitle,
                  variant: AppButtonVariant.tertiary,
                  icon: Icons.trending_up_rounded,
                  onPressed: () => context.openBoost(requestId),
                ),
              ],
            );
          },
        ),
      ),
    );
  }

  Future<void> _propose(
    BuildContext context,
    WidgetRef ref,
    DiscoveryCandidate candidate,
  ) async {
    final outcome = await showAppSheet<_ProposeOutcome>(
      context,
      builder: (sheetContext) => _ProposeSheet(candidate: candidate),
    );
    if (outcome == null || !context.mounted) return;

    if (outcome.staleCode != null) {
      ref.invalidate(_compatibleJourneysProvider(requestId));
      return;
    }

    final matchId = outcome.matchId;
    if (matchId != null) {
      ref.invalidate(_compatibleJourneysProvider(requestId));
      AppSnack.success(context, L.of(context).discoveryProposalSent);
      context.openNegotiation(matchId);
    }
  }
}

// ---------------------------------------------------------------------------
// Candidate
// ---------------------------------------------------------------------------

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({required this.candidate, required this.onPropose});

  final DiscoveryCandidate candidate;
  final VoidCallback onPropose;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final journey = candidate.journey;
    final compatibility = candidate.compatibility;
    final pricing = candidate.pricing;
    final canPropose = candidate.proposalTarget != null;

    final legs = compatibility?.coveredLegs ?? const <CoveredLeg>[];
    final departure = journey?.firstDeparture;
    final band =
        compatibility?.matchedDistanceBand ?? pricing?.matchedDistanceBand;
    final detour = formatDetour(
      context,
      compatibility?.totalAddedDistance ?? DetourBand.unknown,
    );

    return AppCard(
      onTap: canPropose ? onPropose : null,
      semanticLabel: l.discoveryTravelersTitle,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (legs.isNotEmpty)
            RouteLine(
              compactSegments: true,
              stops: _stopsFor(context, legs),
              segments: [
                for (final leg in legs)
                  RouteSegment(
                    mode: leg.mode,
                    modeLabel: transportModeLabel(context, leg.mode),
                  ),
              ],
            )
          else if (journey?.startLocation != null &&
              journey?.destinationLocation != null)
            RouteSummary(
              from: _placeLabel(journey!.startLocation!),
              to: _placeLabel(journey.destinationLocation!),
            ),

          const SizedBox(height: AppSpace.md),

          if (legs.isNotEmpty)
            DetailRow(
              label: l.journeyLegs,
              value: Text(l.discoveryCoveredLegs(legs.length)),
            ),
          if (departure != null)
            DetailRow(
              label: l.discoveryFirstDeparture,
              value: Text(LocaleFormats.dateTime(locale, departure)),
              icon: Icons.schedule_rounded,
            ),
          if (detour.isNotEmpty)
            DetailRow(
              label: l.discoveryDetourLabel,
              value: Text(detour),
              icon: Icons.alt_route_rounded,
            ),
          if (band != null)
            DetailRow(
              label: l.discoveryMatchedDistance,
              value: Text(formatDistanceBand(context, band)),
              icon: Icons.straighten_rounded,
            ),

          if (pricing?.minimumReward != null)
            DetailRow(
              label: l.moneyMinimumReward,
              value: MoneyText(
                pricing!.minimumReward!,
                semanticPrefix: l.moneyMinimumReward,
                size: 14,
                color: c.textSecondary,
              ),
            ),
          if (pricing?.recommendedReward != null)
            DetailRow(
              label: l.moneyRecommendedReward,
              value: MoneyText(
                pricing!.recommendedReward!,
                semanticPrefix: l.moneyRecommendedReward,
              ),
              emphasise: true,
            ),

          if (pricing?.isVolumetric ?? false) ...[
            const SizedBox(height: AppSpace.sm),
            Text(
              l.discoveryVolumetricExplainer,
              style: text.bodySmall?.copyWith(color: c.textTertiary),
            ),
          ],

          if (!canPropose) ...[
            const SizedBox(height: AppSpace.md),
            InfoNotice(
              message: l.discoveryProposeBlocked,
              tone: StatusTone.waiting,
              icon: Icons.help_outline_rounded,
            ),
          ],
        ],
      ),
    );
  }

  /// N legs make N+1 stops: every leg's origin, then the last destination.
  /// [RouteLine] needs exactly that shape.
  static List<RouteStop> _stopsFor(
    BuildContext context,
    List<CoveredLeg> legs,
  ) {
    final locale = Localizations.localeOf(context);
    final stops = <RouteStop>[
      for (final leg in legs)
        RouteStop(
          label: leg.origin == null ? '' : _placeLabel(leg.origin!),
          timeLabel: leg.departAt == null
              ? null
              : LocaleFormats.dateTime(locale, leg.departAt!),
        ),
    ];

    final last = legs.last;
    stops.add(
      RouteStop(
        label: last.destination == null ? '' : _placeLabel(last.destination!),
        timeLabel: last.arriveAt == null
            ? null
            : LocaleFormats.dateTime(locale, last.arriveAt!),
      ),
    );
    return stops;
  }

  static String _placeLabel(AppLocation place) =>
      place.isExact ? place.displayLabel : place.coarseLabel;
}

// ---------------------------------------------------------------------------
// Proposing
// ---------------------------------------------------------------------------

/// What the sheet hands back: the match to open, or the code that made it
/// close itself.
@immutable
class _ProposeOutcome {
  const _ProposeOutcome.sent(this.matchId) : staleCode = null;
  const _ProposeOutcome.stale(this.staleCode) : matchId = null;

  final int? matchId;
  final ApiErrorCode? staleCode;
}

class _ProposeSheet extends ConsumerStatefulWidget {
  const _ProposeSheet({required this.candidate});

  final DiscoveryCandidate candidate;

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
        widget.candidate.pricing?.recommendedReward ??
        widget.candidate.pricing?.minimumReward;
    if (suggested != null) _reward.text = amountFieldText(suggested);
  }

  @override
  void dispose() {
    _reward.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final l = L.of(context);
    final target = widget.candidate.proposalTarget;
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
            parcelId: target.parcelId,
            journeyId: target.journeyId,
            // Echoed back unchanged. A recalculated range is refused.
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

    // The floor moved. Put the real number on the field rather than in a
    // toast — this is a correction to what they typed.
    if (error.code == ApiErrorCode.rewardBelowMinimum) {
      final minimum = error.intExtra('minimum_reward_eur_cents');
      setState(
        () => _rewardError = minimum == null
            ? l.staleRewardBelowMinimum
            : l.offerBelowMinimum(Money.eurCents(minimum).format(locale)),
      );
      return;
    }

    // Everything below is the world having moved. The list behind this sheet
    // is wrong, so the sheet closes and the caller refreshes it.
    final closing = switch (error.code) {
      ApiErrorCode.capacityExceeded => l.staleCapacityExceeded,
      ApiErrorCode.requestNotOpen => l.staleRequestNotOpen,
      ApiErrorCode.requestAlreadyMatched => l.staleRequestAlreadyMatched,
      ApiErrorCode.journeyNotActive => l.staleJourneyNotActive,
      ApiErrorCode.invalidLegRange => l.discoveryLegRangeMoved,
      // The codes themselves are internal vocabulary. The count is the honest
      // part a sender can act on.
      ApiErrorCode.incompatibleCandidate => l.discoveryIncompatibleCount(
        error.stringListExtra('rejection_codes').length,
      ),
      _ => null,
    };

    if (closing == null) {
      if (error.code.impliesStaleClientState) {
        setState(() => _notice = staleMessage(context, error.code));
        return;
      }
      AppSnack.failure(context, error);
      return;
    }

    AppSnack.info(context, closing);
    Navigator.of(context).pop(_ProposeOutcome.stale(error.code));
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final pricing = widget.candidate.pricing;
    final canPropose = widget.candidate.proposalTarget != null;

    return AppSheet(
      title: l.offerProposeTitle,
      subtitle: l.offerProposeExplainer,
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
            const SizedBox(height: AppSpace.lg),
          ],

          AppAmountField(
            label: l.offerRewardLabel,
            controller: _reward,
            helper: pricing?.minimumReward == null
                ? null
                : l.offerBelowMinimum(
                    pricing!.minimumReward!.format(
                      Localizations.localeOf(context),
                    ),
                  ),
            errorText: _rewardError,
            enabled: !_busy,
            onChanged: (_) => setState(() {}),
          ),

          if (pricing?.recommendedReward != null) ...[
            AppButton(
              label: l.offerUseRecommended,
              variant: AppButtonVariant.tertiary,
              expand: false,
              onPressed: () => setState(
                () =>
                    _reward.text = amountFieldText(pricing!.recommendedReward!),
              ),
            ),
            const SizedBox(height: AppSpace.lg),
          ],

          _Breakdown(
            pricing: pricing,
            entered: AppAmountField.centsOf(_reward),
          ),
        ],
      ),
    );
  }
}

/// The server's own arithmetic, rendered.
///
/// Only ever shows a set of figures the API published together: it never adds
/// a reward to a fee, because [Money] has no `+` and a total the server did
/// not send is a total we do not know.
class _Breakdown extends StatelessWidget {
  const _Breakdown({required this.pricing, required this.entered});

  final PricingQuote? pricing;
  final int? entered;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final quote = pricing;
    if (quote == null) return const SizedBox.shrink();

    // Pick the economics block that actually matches what is in the field.
    // Anything else would be a total attached to a different number.
    final matchesMinimum =
        entered != null && entered == quote.minimumReward?.minorUnits;
    final economics = matchesMinimum
        ? quote.minimumEconomics
        : quote.recommendedEconomics ?? quote.minimumEconomics;
    if (economics == null) return const SizedBox.shrink();

    final matchesShown =
        entered != null && entered == economics.travelerReward?.minorUnits;

    return MoneyBreakdown(
      title: l.moneyBreakdownTitle,
      explainer: matchesShown
          ? l.moneyRewardNotReduced
          : l.discoveryBreakdownNote,
      lines: [
        if (economics.travelerReward != null)
          MoneyLine(
            label: l.moneyTravelerReceives,
            amount: economics.travelerReward!,
          ),
        if (economics.platformFee != null)
          MoneyLine(label: l.moneyPlatformFee, amount: economics.platformFee!),
        if (economics.senderTotal != null)
          MoneyLine.total(label: l.moneyYouPay, amount: economics.senderTotal!),
      ],
    );
  }
}
