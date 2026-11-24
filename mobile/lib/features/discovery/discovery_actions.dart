/// What a person can do from a discovery card (spec 4.4).
///
/// * From a **trip**, a sender picks one of their open requests and lands on
///   Find Travelers with that trip in focus, or posts a new request for the
///   route. The sender still proposes first; nothing here makes an offer.
/// * From a **request**, a traveler may say **"I can carry this"**. That sends
///   the sender one notification. It is not an offer, carries no price and
///   reserves nothing, and the server decides whether the pair is compatible.
/// * From a **person**, a viewer may turn on a route alert.
///
/// The server owns every verdict. A refusal is shown with the server's own
/// reason codes mapped to copy, never with a reason the client made up.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/discovery_repository.dart';
import '../../design/components/feedback.dart';
import '../../core/money/money.dart';
import '../../design/components/money.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/delivery_request.dart';
import '../../domain/journey.dart';
import '../../domain/public_discovery.dart';
import '../../l10n/app_localizations.dart';
import '../auth/account_gate.dart';
import '../common/formatters.dart';
import '../common/status_copy.dart';
import '../common/traveler_candidate_card.dart';
import '../reviews/review_widgets.dart';
import '../journeys/journey_labels.dart';
import '../requests/request_labels.dart';
import 'discovery_widgets.dart';

// ---------------------------------------------------------------------------
// Reasons
// ---------------------------------------------------------------------------

/// The server's machine rejection codes, as sentences a person can act on.
///
/// Several codes can arrive at once and several map to one sentence, so the
/// result is de-duplicated. A code this app has never heard of becomes the
/// generic line rather than being printed raw.
List<String> rejectionReasons(L l, Iterable<String> codes) {
  final reasons = <String>{};
  for (final code in codes) {
    reasons.add(switch (code) {
      'capacity_available_on_every_leg' => l.rejectCapacity,
      'delivery_before_deadline' => l.rejectDeadline,
      'pickup_within_ready_window' ||
      'pickup_before_delivery' ||
      'route_time_order_feasible' => l.rejectTiming,
      'pickup_detour_within_limit' ||
      'delivery_detour_within_limit' ||
      'total_added_distance_within_limit' ||
      'total_added_duration_within_limit' ||
      'canonical_geography_complete' => l.rejectRoute,
      'request_active' ||
      'request_has_no_active_deal' ||
      'journey_active' ||
      'journey_leg_sequence' => l.rejectClosed,
      'accounts_eligible' ||
      'traveler_kyc_current' ||
      'target_traveler_eligible' ||
      'flight_proofs_approved' ||
      'sea_proofs_approved' => l.rejectVerification,
      'item_safety_eligible' => l.rejectItem,
      'item_accepted_by_traveler' => l.rejectNotAccepted,
      'sea_legs_available' => l.rejectSea,
      'journey_not_paused' => l.rejectPaused,
      'stop_services_allow_handover' => l.rejectHandover,
      'volume_available_on_every_leg' => l.rejectVolume,
      'parcel_slots_available_on_every_leg' => l.rejectParcelSlots,
      _ => l.rejectGeneric,
    });
  }
  return reasons.toList(growable: false);
}

/// Copy for the discovery refusals that have a clearer sentence than the
/// generic failure strip, or null to fall through to [describeFailure].
String? discoveryRefusal(L l, ApiException error) => switch (error.code) {
  ApiErrorCode.interestDailyCapReached => l.carryDailyCap,
  ApiErrorCode.discoveryListingsDisabled => l.discoveryListingsOff,
  ApiErrorCode.discoveryProfilesDisabled => l.discoveryProfilesOff,
  ApiErrorCode.requestNotFound => l.carryRequestGone,
  ApiErrorCode.journeyNotFound => l.carryJourneyGone,
  ApiErrorCode.profileNotFound => l.discoveryProfileGone,
  ApiErrorCode.routeAlertLimitReached => l.alertLimitReached,
  ApiErrorCode.routeAlertSameCity => l.alertSameCity,
  ApiErrorCode.routeAlertSelf => l.alertSelf,
  ApiErrorCode.usualRouteSameCity => l.alertSameCity,
  ApiErrorCode.usualRouteDuplicate => l.publicRouteDuplicate,
  _ => null,
};

/// The sentence for any failure from a discovery write: the clearer refusal
/// when there is one, the shared failure copy otherwise.
String discoveryFailureMessage(BuildContext context, Object error) {
  final l = L.of(context);
  if (error is ApiException) {
    final refusal = discoveryRefusal(l, error);
    if (refusal != null) return refusal;
  }
  return describeFailure(context, error).body;
}

// ---------------------------------------------------------------------------
// "I can carry this"
// ---------------------------------------------------------------------------

/// What came of an "I can carry this" attempt, ready to show.
sealed class CarryOutcome {
  const CarryOutcome();
}

class CarrySent extends CarryOutcome {
  const CarrySent({required this.created});

  /// False when the same signal had already been sent: nothing was sent again.
  final bool created;
}

class CarryRefused extends CarryOutcome {
  const CarryRefused(this.message);
  final String message;
}

/// Sends the signal and turns every refusal into a sentence.
///
/// An incompatible pair lists the server's reasons. The cap, a switched-off
/// listing tier and a request that has since gone each have their own line.
Future<CarryOutcome> sendCarrySignal(
  BuildContext context,
  WidgetRef ref, {
  required int requestId,
  required int journeyId,
}) async {
  final l = L.of(context);
  try {
    final result = await ref
        .read(discoveryRepositoryProvider)
        .sendInterest(requestId: requestId, journeyId: journeyId);
    return CarrySent(created: result.created);
  } on ApiException catch (error) {
    if (!context.mounted) return CarryRefused(l.stateUnexpectedBody);
    if (error.code == ApiErrorCode.incompatibleCandidate) {
      final reasons = rejectionReasons(
        l,
        error.stringListExtra('rejection_codes'),
      );
      return CarryRefused(
        reasons.isEmpty
            ? l.carryIncompatible
            : '${l.carryIncompatible}\n${reasons.map((r) => '• $r').join('\n')}',
      );
    }
    return CarryRefused(discoveryFailureMessage(context, error));
  }
}

/// A traveler's journeys that can carry something, newest route first as the
/// server lists them. Only live journeys: the server refuses the rest anyway.
String journeyOptionLabel(Journey journey) => [
  endpointLabel(journey.startPlace, journey.startLocation),
  endpointLabel(journey.destinationPlace, journey.destinationLocation),
].join(' → ');

// ---------------------------------------------------------------------------
// Trip preview
// ---------------------------------------------------------------------------

/// What a sender chose to do with a trip.
sealed class TripChoice {
  const TripChoice();
}

class ChooseRequest extends TripChoice {
  const ChooseRequest(this.requestId);
  final int requestId;
}

class PostForRoute extends TripChoice {
  const PostForRoute();
}

/// Opens the full trip card and, if the sender acts on it, carries on to Find
/// Travelers or the request form.
Future<void> showTripPreview(
  BuildContext context,
  TripCard card, {
  bool canAct = true,
}) async {
  final choice = await showAppSheet<TripChoice>(
    context,
    builder: (_) => _TripPreviewSheet(card: card, canAct: canAct),
  );
  if (choice == null || !context.mounted) return;
  switch (choice) {
    case ChooseRequest(:final requestId):
      context.openDiscovery(requestId, focusJourneyId: card.journeyId);
    case PostForRoute():
      final first = card.stops.isEmpty ? null : card.stops.first;
      final last = card.stops.length < 2 ? null : card.stops.last;
      await context.openRequestCreate(
        pickup: first?.toLocality(),
        delivery: last?.toLocality(),
      );
  }
}

class _TripPreviewSheet extends ConsumerWidget {
  const _TripPreviewSheet({required this.card, required this.canAct});

  final TripCard card;
  final bool canAct;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);

    final stops = placeStops(card.stops);
    final capacity = spaceLeftValue(l, card.freeWeightKg);
    final requests = ref.watch(myRequestsProvider);
    final open = (requests.value ?? const <DeliveryRequest>[])
        .where((r) => r.status == RequestStatus.open)
        .toList(growable: false);

    return AppSheet(
      title: card.traveler.displayName,
      subtitle: l.tripPreviewSubtitle,
      footer: !canAct
          ? null
          : open.isEmpty
          ? AppButton(
              label: l.tripPostForRoute,
              icon: Icons.add_rounded,
              onPressed: () => Navigator.of(context).pop(const PostForRoute()),
            )
          : null,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          PublicPersonRow(person: card.traveler, avatarSize: 40),
          const SizedBox(height: AppSpace.md),
          if (card.traveler.identityVerified)
            Row(
              children: [
                Icon(Icons.verified_rounded, size: 16, color: c.success),
                const SizedBox(width: AppSpace.sm),
                Text(l.findTravelersIdentityVerified, style: text.labelMedium),
              ],
            ),
          if (card.traveler.completedDeliveries > 0) ...[
            const SizedBox(height: AppSpace.xs),
            Text(
              l.findTravelersDeliveries(card.traveler.completedDeliveries),
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ],
          if (card.traveler.hasRating)
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: ReviewsLink(
                rating: card.traveler.rating,
                onTap: () => context.openTripReviews(card.journeyId),
              ),
            ),
          const SizedBox(height: AppSpace.lg),
          InlineRoute(stops: stops),
          const SizedBox(height: AppSpace.md),
          for (final (index, leg) in card.legs.indexed)
            _LegRow(
              leg: leg,
              from: index < card.stops.length ? card.stops[index].label : '',
              to: index + 1 < card.stops.length
                  ? card.stops[index + 1].label
                  : '',
            ),
          const SizedBox(height: AppSpace.sm),
          if (card.arrivesAt != null)
            DetailRow(
              label: l.tripArrives,
              icon: Icons.flag_outlined,
              value: Text(LocaleFormats.dateTime(locale, card.arrivesAt!)),
            ),
          if (capacity.isNotEmpty)
            DetailRow(
              label: l.tripSpace,
              icon: Icons.luggage_outlined,
              value: Text(capacity),
            ),
          if (card.price case final price?)
            DetailRow(
              label: l.tripPrice,
              icon: Icons.sell_outlined,
              value: Text(
                l.tripPriceFrom(
                  Money.eurCents(price.perKgEurCents).format(locale),
                  Money.eurCents(price.minimumEurCents).format(locale),
                ),
              ),
            ),
          if (canAct && open.isNotEmpty) ...[
            SectionHeader(title: l.tripChooseParcel),
            for (final request in open) ...[
              AppCard(
                onTap: () =>
                    Navigator.of(context).pop(ChooseRequest(request.id)),
                padding: const EdgeInsets.all(AppSpace.md),
                semanticLabel: request.title,
                child: Row(
                  children: [
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            request.title,
                            style: text.titleSmall,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                          ),
                          const SizedBox(height: AppSpace.xs),
                          RouteSummary(
                            from: requestPickupLabel(l, request),
                            to: requestDeliveryLabel(l, request),
                            style: text.bodySmall?.copyWith(
                              color: c.textSecondary,
                            ),
                          ),
                        ],
                      ),
                    ),
                    Icon(
                      Icons.chevron_right_rounded,
                      size: 20,
                      color: c.textTertiary,
                    ),
                  ],
                ),
              ),
              const SizedBox(height: AppSpace.sm),
            ],
            AppButton(
              label: l.tripPostForRoute,
              variant: AppButtonVariant.tertiary,
              icon: Icons.add_rounded,
              onPressed: () => Navigator.of(context).pop(const PostForRoute()),
            ),
          ],
          if (canAct && requests.isLoading && !requests.hasValue)
            const Padding(
              padding: EdgeInsets.only(top: AppSpace.lg),
              child: SkeletonCardList(count: 1),
            ),
          if (canAct && requests.hasError && !requests.hasValue)
            Padding(
              padding: const EdgeInsets.only(top: AppSpace.lg),
              child: InlineFailure(
                error: requests.error,
                onRetry: () => ref.invalidate(myRequestsProvider),
              ),
            ),
        ],
      ),
    );
  }
}

class _LegRow extends StatelessWidget {
  const _LegRow({required this.leg, required this.from, required this.to});

  final TripLeg leg;
  final String from;
  final String to;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final depart = leg.departAt;
    final arrive = leg.arriveAt;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpace.xs),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            leg.mode.icon,
            size: 16,
            color: modeAccentColor(context, leg.mode),
          ),
          const SizedBox(width: AppSpace.sm),
          Expanded(
            child: Text(
              [
                transportModeLabel(context, leg.mode),
                if (from.isNotEmpty && to.isNotEmpty) '$from → $to',
                if (depart != null) LocaleFormats.dateTime(locale, depart),
                if (arrive != null && depart != null)
                  '→ ${LocaleFormats.dateTime(locale, arrive)}',
              ].join(' · '),
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// Request preview
// ---------------------------------------------------------------------------

/// Opens the full request card with the "I can carry this" action. A traveler
/// with no live trip is offered the publish screen instead.
///
/// [carryJourneyId] is the trip a "a parcel fits your trip" alert named. It is
/// the one "I can carry this" speaks for, and the server still decides whether
/// the pair works: a refusal is shown with its reasons, as for any other trip.
Future<void> showRequestPreview(
  BuildContext context,
  RequestCard card, {
  int? carryJourneyId,
}) async {
  // A guest may sign in from the sheet, and the tab under it is then built
  // again for the member: the trip form opens from the app's own navigator,
  // which outlives that.
  final root = Navigator.of(context, rootNavigator: true).context;
  final publish = await showAppSheet<bool>(
    context,
    builder: (_) =>
        _RequestPreviewSheet(card: card, carryJourneyId: carryJourneyId),
  );
  if (publish == true && root.mounted) await root.openJourneyCreate();
}

class _RequestPreviewSheet extends ConsumerStatefulWidget {
  const _RequestPreviewSheet({required this.card, this.carryJourneyId});

  final RequestCard card;
  final int? carryJourneyId;

  @override
  ConsumerState<_RequestPreviewSheet> createState() =>
      _RequestPreviewSheetState();
}

class _RequestPreviewSheetState extends ConsumerState<_RequestPreviewSheet> {
  bool _busy = false;
  CarryOutcome? _outcome;

  /// A guest asked to carry this and has just made an account: the signal
  /// goes as soon as their trips are known.
  bool _carryOnceSignedIn = false;

  Future<void> _carryAsGuest() async {
    if (!await ensureAccount(context, AccountReason.carry) || !mounted) return;
    setState(() => _carryOnceSignedIn = true);
  }

  /// Carries on with the guest's "I can carry this" once their trips are
  /// read: the signal for a live trip, or the sheet's own "Add a journey"
  /// when they have none.
  void _continueCarry(
    AsyncValue<List<Journey>> myJourneys,
    List<Journey> live,
  ) {
    if (!_carryOnceSignedIn) return;
    if (!myJourneys.hasValue && !myJourneys.hasError) return;
    _carryOnceSignedIn = false;
    if (!myJourneys.hasValue || live.isEmpty) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) _carry(live);
    });
  }

  Future<void> _carry(List<Journey> journeys) async {
    final l = L.of(context);
    final named = journeys
        .where((j) => j.id == widget.carryJourneyId)
        .firstOrNull;
    final Journey journey;
    if (named != null) {
      journey = named;
    } else if (journeys.length == 1) {
      journey = journeys.single;
    } else {
      final picked = await showAppSheet<Journey>(
        context,
        builder: (_) => AppChoiceSheet<Journey>(
          title: l.carryChooseTrip,
          subtitle: l.carryChooseTripHint,
          selected: null,
          options: [
            for (final j in journeys)
              AppSheetOption(
                value: j,
                label: journeyOptionLabel(j),
                detail: j.firstDeparture == null
                    ? null
                    : LocaleFormats.dateTime(
                        Localizations.localeOf(context),
                        j.firstDeparture!,
                      ),
                icon: Icons.luggage_outlined,
              ),
          ],
        ),
      );
      if (picked == null || !mounted) return;
      journey = picked;
    }

    setState(() => _busy = true);
    final outcome = await sendCarrySignal(
      context,
      ref,
      requestId: widget.card.requestId,
      journeyId: journey.id,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _outcome = outcome;
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;
    final locale = Localizations.localeOf(context);
    final card = widget.card;

    final guest = ref.watch(isGuestProvider);
    final myJourneys = ref.watch(myJourneysProvider);
    final journeys = ref.watch(activeJourneysProvider);
    _continueCarry(myJourneys, journeys);
    final sent = _outcome is CarrySent;
    final stops = placeStops([card.pickup, card.delivery]);
    final suggested = journeys
        .where((j) => j.id == widget.carryJourneyId)
        .firstOrNull;

    Widget? footer;
    if (sent) {
      footer = AppButton(
        label: l.actionDone,
        onPressed: () => Navigator.of(context).pop(),
      );
    } else if (guest) {
      footer = AppButton(
        label: l.requestCarryAction,
        icon: Icons.back_hand_outlined,
        onPressed: _carryAsGuest,
      );
    } else if (journeys.isEmpty && myJourneys.hasValue) {
      footer = AppButton(
        label: l.carryPublishTrip,
        icon: Icons.flight_takeoff_rounded,
        onPressed: () => Navigator.of(context).pop(true),
      );
    } else {
      footer = AppButton(
        label: l.requestCarryAction,
        icon: Icons.back_hand_outlined,
        isLoading: _busy || (myJourneys.isLoading && !myJourneys.hasValue),
        onPressed: journeys.isEmpty ? null : () => _carry(journeys),
      );
    }

    return AppSheet(
      title: card.title,
      subtitle: card.sender.isEmpty ? null : l.requestCardFrom(card.sender),
      footer: footer,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (suggested != null) ...[
            InfoNotice(
              message: l.requestFitsTripHint(journeyOptionLabel(suggested)),
              tone: StatusTone.progress,
              icon: Icons.luggage_outlined,
            ),
            const SizedBox(height: AppSpace.md),
          ],
          InlineRoute(stops: stops),
          const SizedBox(height: AppSpace.md),
          if (card.fragile)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.sm),
              child: Align(
                alignment: AlignmentDirectional.centerStart,
                child: StatusPill(
                  label: l.requestFragile,
                  tone: StatusTone.waiting,
                  icon: Icons.warning_amber_rounded,
                ),
              ),
            ),
          DetailRow(
            label: l.requestCategory,
            icon: Icons.category_outlined,
            value: Text(itemCategoryLabel(l, card.category)),
          ),
          if (card.weightKg != null)
            DetailRow(
              label: l.requestWeight,
              icon: Icons.scale_outlined,
              value: Text(formatWeight(context, card.weightKg)),
            ),
          if (card.readyWindowStart != null && card.readyWindowEnd != null)
            DetailRow(
              label: l.requestReadyWindow,
              icon: Icons.schedule_rounded,
              value: Text(
                LocaleFormats.range(
                  locale,
                  card.readyWindowStart!,
                  card.readyWindowEnd!,
                ),
              ),
            ),
          if (card.deadlineAt != null)
            DetailRow(
              label: l.requestDeadline,
              icon: Icons.flag_outlined,
              value: Text(LocaleFormats.dateTime(locale, card.deadlineAt!)),
            ),
          if (card.totalOfferedReward != null)
            DetailRow(
              label: l.requestOfferedReward,
              icon: Icons.payments_outlined,
              emphasise: true,
              value: MoneyText(
                card.totalOfferedReward!,
                size: 16,
                color: c.textPrimary,
              ),
            ),
          const SizedBox(height: AppSpace.md),
          if (_outcome case CarrySent(:final created))
            InfoNotice(
              title: created ? l.carrySentTitle : l.carryAlreadySentTitle,
              message: l.carrySentBody,
              tone: StatusTone.good,
              icon: Icons.check_circle_outline_rounded,
            )
          else if (_outcome case CarryRefused(:final message))
            InfoNotice(
              message: message,
              tone: StatusTone.waiting,
              icon: Icons.info_outline_rounded,
            )
          else
            Text(
              l.carryExplain,
              style: text.bodySmall?.copyWith(color: c.textSecondary),
            ),
          if (myJourneys.hasError && !myJourneys.hasValue)
            Padding(
              padding: const EdgeInsets.only(top: AppSpace.md),
              child: InlineFailure(
                error: myJourneys.error,
                onRetry: () => ref.invalidate(myJourneysProvider),
              ),
            ),
        ],
      ),
    );
  }
}
