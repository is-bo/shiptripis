/// The delivery.
///
/// This is the hub: one screen that answers "where is my parcel, what happens
/// next, and is it me who has to do something". Every other deal screen —
/// payment, recipient, pickup, delivery, dispute, cancel, rate — is reached
/// from here and returns to here.
///
/// ## One call
///
/// `GET /api/deals/<id>` returns the whole aggregate: terms, allocations,
/// recipient, handover, protection, dispute, cancellation availability and
/// ratings. This screen makes that one call and nothing else. Fanning out into
/// eight requests for a screen the user opens on a train would be a worse
/// product for no gain.
///
/// ## The timeline is built from timestamps, not from a status
///
/// Each step is `done` because the server returned an instant for it, and
/// `waitingOnYou` because the server returned a permission for it
/// (`can_submit_*`, `can_reveal_*`, `can_rate`, a status that needs funding).
/// Nothing here infers a stage from a status string, which is what keeps the
/// screen honest when a deal is in a state this build has never seen.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/format/locale_formats.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../design/components/codes.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/route.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/components/timeline.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/money_perspective.dart';
import '../../domain/rating.dart';
import '../../l10n/app_localizations.dart';
import '../common/status_copy.dart';

class DealScreen extends ConsumerWidget {
  const DealScreen({required this.dealId, super.key});

  final int dealId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final account = ref.watch(accountProvider);
    final deal = ref.watch(dealDetailProvider(dealId));

    return AppScaffold(
      topBar: AppTopBar(
        title: l.deliveriesTitle,
        showBack: true,
        actions: [
          if (deal.value?.matchId != null)
            AppIconButton(
              icon: Icons.forum_outlined,
              label: l.dealOpenChat,
              onPressed: () => context.openChatThread(
                deal.value!.matchId!,
                dealId: deal.value!.id,
              ),
            ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: () async => ref.invalidate(dealDetailProvider(dealId)),
        child: AsyncView<Deal>(
          value: deal,
          onRetry: () => ref.invalidate(dealDetailProvider(dealId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (data) {
            if (account == null) return const SkeletonDetail();
            final perspective = data.moneyPerspectiveFor(account.id);
            if (perspective == null) return const SizedBox.shrink();
            final isSender = perspective.isSender;

            return ListView(
              padding: AppScrollPadding.page(context),
              children: [
                _StatusHeader(deal: data, perspective: perspective),
                const SizedBox(height: AppSpace.xl),

                _Urgent(deal: data, isSender: isSender),

                if (isSender) _SenderEarlyArrivalNotice(deal: data),

                _ArrivalSection(deal: data, isSender: isSender),

                _PostPickupWaiting(deal: data, isSender: isSender),

                _RouteSection(
                  route: data.route,
                  isFunded: data.fundedAt != null,
                ),

                SectionHeader(title: l.timelineTitle),
                LifecycleTimeline(
                  steps: _buildSteps(context, data, isSender: isSender),
                ),
                const SizedBox(height: AppSpace.xl),

                _MoneySection(deal: data, perspective: perspective),
                const SizedBox(height: AppSpace.xl),

                _RecipientSection(deal: data, isSender: isSender),

                _ProtectionSection(deal: data, isSender: isSender),

                _DisputeSection(deal: data),

                _RatingSection(deal: data, isSender: isSender),

                const SizedBox(height: AppSpace.xl),
                _SecondaryActions(deal: data, isSender: isSender),
              ],
            );
          },
        ),
      ),
    );
  }

  /// The lifecycle, assembled from server instants and server permissions.
  List<LifecycleStep> _buildSteps(
    BuildContext context,
    Deal deal, {
    required bool isSender,
  }) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final handover = deal.handover;

    String? at(DateTime? when) =>
        when == null ? null : LocaleFormats.dayMonth(locale, when);

    LifecycleState stateFor({
      required bool done,
      required bool mine,
      required bool reached,
    }) {
      if (done) return LifecycleState.done;
      if (!reached) return LifecycleState.upcoming;
      return mine ? LifecycleState.waitingOnYou : LifecycleState.waitingOnThem;
    }

    final isFunded = deal.isFunded;
    final recipientRecorded = deal.recipient?.recorded ?? false;
    final pickedUp = deal.pickupConfirmedAt != null;
    final delivered = deal.deliveryConfirmedAt != null;
    final completed = deal.status == DealStatus.completed;
    final deliveryActionAvailable =
        (handover?.canSubmitDeliveryCode ?? false) ||
        (handover?.canRevealDeliveryCode ?? false);

    return [
      LifecycleStep(
        label: l.dealStepAgreed,
        state: LifecycleState.done,
        timeLabel: at(deal.createdAt),
      ),

      LifecycleStep(
        label: l.dealStepPaid,
        state: deal.status == DealStatus.paymentFailed
            ? LifecycleState.failed
            : stateFor(done: isFunded, mine: isSender, reached: true),
        timeLabel: at(deal.fundedAt),
        detail: isFunded ? null : (isSender ? l.dealActionPay : null),
        actionLabel: !isFunded && isSender ? l.dealActionPay : null,
        onAction: !isFunded && isSender
            ? () => context.openDealPayment(deal.id)
            : null,
      ),

      LifecycleStep(
        label: l.dealStepRecipient,
        state: stateFor(
          done: recipientRecorded,
          mine: isSender,
          reached: isFunded,
        ),
        timeLabel: at(deal.recipient?.updatedAt),
        actionLabel: isFunded && !recipientRecorded && isSender
            ? l.dealActionRecipient
            : null,
        onAction: isFunded && !recipientRecorded && isSender
            ? () => context.openRecipient(deal.id)
            : null,
      ),

      LifecycleStep(
        label: l.dealStepPickedUp,
        state: stateFor(
          done: pickedUp,
          // Whoever the server says can act on the code right now.
          mine:
              (handover?.canSubmitPickupCode ?? false) ||
              (handover?.canRevealPickupCode ?? false),
          reached: isFunded,
        ),
        timeLabel: at(deal.pickupConfirmedAt),
        actionLabel:
            !pickedUp &&
                ((handover?.canSubmitPickupCode ?? false) ||
                    (handover?.canRevealPickupCode ?? false))
            ? l.dealActionPickup
            : null,
        onAction:
            !pickedUp &&
                ((handover?.canSubmitPickupCode ?? false) ||
                    (handover?.canRevealPickupCode ?? false))
            ? () => context.openPickup(deal.id)
            : null,
      ),

      LifecycleStep(
        label: l.dealStepDelivered,
        state: stateFor(
          done: delivered,
          mine: deliveryActionAvailable,
          reached: pickedUp && !(handover?.inDeliveryCodeBuffer ?? false),
        ),
        timeLabel: at(deal.deliveryConfirmedAt),
        // The buffer is a real, explainable wait rather than a silence.
        detail: !delivered && (handover?.inDeliveryCodeBuffer ?? false)
            ? l.deliveryCodeLockedBody
            : null,
        actionLabel: !delivered && deliveryActionAvailable
            ? l.dealActionDelivery
            : null,
        onAction: !delivered && deliveryActionAvailable
            ? () => context.openDelivery(deal.id)
            : null,
      ),

      LifecycleStep(
        label: l.dealStepProtection,
        state: completed
            ? LifecycleState.done
            : stateFor(done: false, mine: false, reached: delivered),
        timeLabel: at(deal.protectionEndsAt),
      ),

      LifecycleStep(
        label: l.dealStepCompleted,
        state: completed ? LifecycleState.done : LifecycleState.upcoming,
        timeLabel: at(deal.completedAt),
      ),
    ];
  }
}

class _PostPickupWaiting extends ConsumerWidget {
  const _PostPickupWaiting({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handover = deal.handover;
    if (deal.pickupConfirmedAt == null ||
        deal.deliveryConfirmedAt != null ||
        !(handover?.inDeliveryCodeBuffer ?? false)) {
      return const SizedBox.shrink();
    }

    final l = L.of(context);
    final availableAt =
        handover?.deliveryCodeAvailableAt ?? deal.deliveryCodeAvailableAt;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: LockedCodePanel(
        title: l.pickupConfirmedTitle,
        body: isSender
            ? l.deliverySafetyWaitingSenderBody
            : l.deliverySafetyWaitingTravelerBody,
        availableAt: availableAt,
        onAvailable: availableAt == null
            ? null
            : () => ref.invalidate(dealDetailProvider(deal.id)),
      ),
    );
  }
}

class _SenderEarlyArrivalNotice extends ConsumerStatefulWidget {
  const _SenderEarlyArrivalNotice({required this.deal});

  final Deal deal;

  @override
  ConsumerState<_SenderEarlyArrivalNotice> createState() =>
      _SenderEarlyArrivalNoticeState();
}

class _SenderEarlyArrivalNoticeState
    extends ConsumerState<_SenderEarlyArrivalNotice> {
  bool _submitting = false;

  Future<void> _confirm() async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      final repo = ref.read(dealRepositoryProvider);
      await repo.confirmEarlyArrival(widget.deal.id);
      if (mounted) {
        AppSnack.success(context, L.of(context).earlyArrivalConfirmedTitle);
      }
      ref.invalidate(dealDetailProvider(widget.deal.id));
      ref.invalidate(activeDealsProvider);
    } catch (err) {
      if (mounted) {
        AppSnack.failure(context, err);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  Future<void> _decline() async {
    if (_submitting) return;
    setState(() => _submitting = true);
    try {
      final repo = ref.read(dealRepositoryProvider);
      await repo.declineEarlyArrival(widget.deal.id);
      if (mounted) {
        AppSnack.success(context, L.of(context).earlyArrivalDeclinedTitle);
      }
      ref.invalidate(dealDetailProvider(widget.deal.id));
      ref.invalidate(activeDealsProvider);
    } catch (err) {
      if (mounted) {
        AppSnack.failure(context, err);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final arrival = widget.deal.arrival;
    if (arrival == null || !arrival.isPendingConfirmation) {
      return const SizedBox.shrink();
    }

    final l = L.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: AppCard(
        accent: StatusTone.action,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  Icons.flight_land_rounded,
                  color: context.colors.attention,
                ),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: Text(
                    l.earlyArrivalSenderNoticeTitle,
                    style: Theme.of(context).textTheme.titleSmall,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpace.sm),
            Text(
              l.earlyArrivalSenderNoticeBody,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
            const SizedBox(height: AppSpace.lg),
            Row(
              children: [
                Expanded(
                  child: AppButton(
                    label: l.earlyArrivalConfirmAction,
                    variant: AppButtonVariant.primary,
                    isLoading: _submitting,
                    onPressed: _submitting ? null : _confirm,
                  ),
                ),
                const SizedBox(width: AppSpace.sm),
                Expanded(
                  child: AppButton(
                    label: l.earlyArrivalDeclineAction,
                    variant: AppButtonVariant.secondary,
                    onPressed: _submitting ? null : _decline,
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _ArrivalSection extends ConsumerStatefulWidget {
  const _ArrivalSection({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  ConsumerState<_ArrivalSection> createState() => _ArrivalSectionState();
}

class _ArrivalSectionState extends ConsumerState<_ArrivalSection> {
  bool _submitting = false;

  Future<void> _reportEarlyArrival() async {
    if (_submitting) return;
    final l = L.of(context);

    final confirmed = await confirmAction(
      context,
      title: l.earlyArrivalConfirmSheetTitle,
      body: l.earlyArrivalConfirmSheetBody,
      confirmLabel: l.earlyArrivalAction,
      cancelLabel: l.actionCancel,
      consequence: InfoNotice(
        message: l.earlyArrivalPayoutFloorExplanation,
        tone: StatusTone.neutral,
        icon: Icons.shield_outlined,
      ),
    );

    if (!confirmed || !mounted) return;

    setState(() => _submitting = true);
    try {
      final repo = ref.read(dealRepositoryProvider);
      await repo.reportEarlyArrival(widget.deal.id);
      if (mounted) {
        AppSnack.success(context, l.earlyArrivalWaitingSenderTitle);
      }
      ref.invalidate(dealDetailProvider(widget.deal.id));
      ref.invalidate(activeDealsProvider);
    } catch (err) {
      if (mounted) {
        AppSnack.failure(context, err);
      }
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final arrival = widget.deal.arrival;
    final isSender = widget.isSender;

    // 1. Traveler can report early arrival
    if (!isSender && (arrival?.canReportEarlyArrival ?? false)) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.flight_land_rounded, color: context.colors.brand),
                  const SizedBox(width: AppSpace.sm),
                  Expanded(
                    child: Text(
                      l.earlyArrivalAction,
                      style: Theme.of(context).textTheme.titleSmall,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpace.sm),
              Text(
                l.earlyArrivalConfirmSheetBody,
                style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: context.colors.textSecondary,
                ),
              ),
              const SizedBox(height: AppSpace.md),
              AppButton(
                label: l.earlyArrivalAction,
                variant: AppButtonVariant.secondary,
                isLoading: _submitting,
                onPressed: _submitting ? null : _reportEarlyArrival,
              ),
            ],
          ),
        ),
      );
    }

    // 2. Traveler waiting for sender confirmation
    if (!isSender && (arrival?.isPendingConfirmation ?? false)) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: InfoNotice(
          title: l.earlyArrivalWaitingSenderTitle,
          message: l.earlyArrivalWaitingSenderBody,
          tone: StatusTone.waiting,
          icon: Icons.hourglass_top_rounded,
        ),
      );
    }

    // 3. Arrival confirmed (if parcel handover not yet confirmed)
    if ((arrival?.isConfirmed ?? false) &&
        widget.deal.deliveryConfirmedAt == null) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: InfoNotice(
          title: l.earlyArrivalConfirmedTitle,
          message: l.earlyArrivalConfirmedBody,
          tone: StatusTone.good,
          icon: Icons.check_circle_outline_rounded,
        ),
      );
    }

    // 4. Arrival declined (if parcel handover not yet confirmed)
    if ((arrival?.isDeclined ?? false) &&
        widget.deal.deliveryConfirmedAt == null) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: InfoNotice(
          title: l.earlyArrivalDeclinedTitle,
          message: l.earlyArrivalDeclinedBody,
          tone: StatusTone.neutral,
          icon: Icons.info_outline_rounded,
        ),
      );
    }

    return const SizedBox.shrink();
  }
}

class _RouteSection extends StatelessWidget {
  const _RouteSection({required this.route, required this.isFunded});

  final DealRoute? route;

  /// Whether the delivery is funded. A route is frozen at funding, so before
  /// that there is nothing to show yet — which is a different fact from a
  /// funded delivery that has no recorded route.
  final bool isFunded;

  @override
  Widget build(BuildContext context) {
    final r = route;
    final l = L.of(context);

    // An absent route used to render nothing at all, which is indistinguishable
    // from the app failing to draw a route the server did send. Deliveries
    // funded before route snapshots existed legitimately have none, and they
    // now say so rather than leaving a silent gap in the screen.
    if (r == null || r.legs.isEmpty) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SectionHeader(title: l.routeTitle),
            InfoNotice(
              message: isFunded
                  ? l.routeUnavailableFunded
                  : l.routeUnavailableBeforeFunding,
              icon: Icons.alt_route_rounded,
            ),
          ],
        ),
      );
    }

    final locale = Localizations.localeOf(context);
    final legs = r.legs;

    final stops = <RouteStop>[];
    final segments = <RouteSegment>[];

    final firstOrigin = legs.first.origin;
    stops.add(
      RouteStop(
        label: (firstOrigin?.displayLabel.isNotEmpty ?? false)
            ? firstOrigin!.displayLabel
            : (firstOrigin?.name ?? '—'),
        detail:
            (firstOrigin?.isAirport ?? false) && firstOrigin?.iataCode != null
            ? firstOrigin!.iataCode
            : firstOrigin?.parentName,
        timeLabel: legs.first.departAt != null
            ? LocaleFormats.dateTime(locale, legs.first.departAt!)
            : null,
      ),
    );

    for (var i = 0; i < legs.length; i++) {
      final leg = legs[i];
      final modeLabel = switch (leg.mode) {
        TransportMode.flight => l.routeFlightMode,
        TransportMode.drive => l.routeDriveMode,
        TransportMode.unknown => l.routeTitle,
      };

      segments.add(RouteSegment(mode: leg.mode, modeLabel: modeLabel));

      final dest = leg.destination;
      stops.add(
        RouteStop(
          label: (dest?.displayLabel.isNotEmpty ?? false)
              ? dest!.displayLabel
              : (dest?.name ?? '—'),
          detail: (dest?.isAirport ?? false) && dest?.iataCode != null
              ? dest!.iataCode
              : dest?.parentName,
          timeLabel: leg.arriveAt != null
              ? LocaleFormats.dateTime(locale, leg.arriveAt!)
              : null,
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: l.routeTitle),
          AppCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (r.basis == DealRouteBasis.fundedSnapshot) ...[
                  StatusPill(
                    label: l.routeBasisSnapshot,
                    tone: StatusTone.neutral,
                    icon: Icons.lock_outline_rounded,
                    compact: true,
                  ),
                  const SizedBox(height: AppSpace.md),
                ] else if (r.basis == DealRouteBasis.liveJourney) ...[
                  StatusPill(
                    label: l.routeBasisLive,
                    tone: StatusTone.neutral,
                    icon: Icons.alt_route_rounded,
                    compact: true,
                  ),
                  const SizedBox(height: AppSpace.md),
                ],
                RouteLine(stops: stops, segments: segments),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _StatusHeader extends StatelessWidget {
  const _StatusHeader({required this.deal, required this.perspective});

  final Deal deal;
  final MoneyPerspective perspective;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final isSender = perspective.isSender;
    final copy = dealStatusCopy(context, deal.status, viewerIsSender: isSender);
    final amount = deal.terms?.totalFor(perspective);

    return AppCard(
      accent: copy.tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusPill(label: copy.label, tone: copy.tone, icon: copy.icon),
          if (amount != null) ...[
            const SizedBox(height: AppSpace.lg),
            MoneyHero(
              amount: amount,
              label: isSender ? l.moneyYouPay : l.moneyYouReceive,
            ),
          ],
        ],
      ),
    );
  }
}

/// The one thing that is time-critical right now, if there is one.
class _Urgent extends StatelessWidget {
  const _Urgent({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);

    // An unfunded deal holds space on somebody's journey, and that hold
    // expires. Saying so is the difference between a lapsed reservation and a
    // user who thought they had time.
    final deadline = deal.fundingDeadline;
    if (deadline != null && isSender) {
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: InfoNotice(
          message: l.dealFundingDeadline(
            LocaleFormats.dateTime(locale, deadline),
          ),
          tone: StatusTone.action,
          icon: Icons.timer_outlined,
          actionLabel: l.dealActionPay,
          onAction: () => context.openDealPayment(deal.id),
        ),
      );
    }

    if (deal.hasActiveDispute) {
      final dispute = deal.dispute!;
      return Padding(
        padding: const EdgeInsets.only(bottom: AppSpace.xl),
        child: InfoNotice(
          title: disputeStatusCopy(context, dispute.status).label,
          message: l.payoutFrozenBody,
          tone: StatusTone.bad,
          icon: Icons.gavel_rounded,
          actionLabel: l.actionOpen,
          onAction: () => context.openDispute(dispute.id),
        ),
      );
    }

    return const SizedBox.shrink();
  }
}

class _MoneySection extends StatelessWidget {
  const _MoneySection({required this.deal, required this.perspective});

  final Deal deal;
  final MoneyPerspective perspective;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final isSender = perspective.isSender;
    final terms = deal.terms;
    if (terms == null) return const SizedBox.shrink();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.dealMoneySection),
        MoneyBreakdown(
          // The traveller is shown what they receive and nothing about the
          // sender's fee; the sender is shown the full build-up.
          explainer: isSender ? l.moneyRewardNotReduced : null,
          lines: [
            if (terms.travelerReward != null)
              MoneyLine(
                label: l.moneyBaseReward,
                amount: terms.travelerReward!,
              ),
            if (terms.boostTravelerBonus?.isPositive ?? false)
              MoneyLine(
                label: l.moneyBoostBonus,
                amount: terms.boostTravelerBonus!,
              ),
            if (terms.travelerTotal != null)
              MoneyLine.total(
                label: isSender
                    ? l.moneyTravelerReceives
                    : l.moneyTotalYouReceive,
                amount: terms.travelerTotal!,
              ),
            if (isSender && terms.platformFee != null)
              MoneyLine(label: l.moneyPlatformFee, amount: terms.platformFee!),
            if (isSender && (terms.boostPlatformFee?.isPositive ?? false))
              MoneyLine(
                label: l.moneyPlatformBoostRevenue,
                amount: terms.boostPlatformFee!,
              ),
            if (isSender && terms.senderTotalWithBoost != null)
              MoneyLine.total(
                label: l.moneyYouPay,
                amount: terms.senderTotalWithBoost!,
              ),
          ],
        ),
      ],
    );
  }
}

class _RecipientSection extends StatelessWidget {
  const _RecipientSection({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final recipient = deal.recipient;
    if (!deal.isFunded) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(
            title: l.recipientTitle,
            actionLabel: isSender && deal.pickupConfirmedAt == null
                ? l.actionEdit
                : null,
            onAction: isSender && deal.pickupConfirmedAt == null
                ? () => context.openRecipient(deal.id)
                : null,
          ),
          if (recipient == null || !recipient.recorded)
            InfoNotice(
              message: isSender
                  ? l.recipientRequiredBody
                  : l.pickupAwaitingSenderBody,
              tone: isSender ? StatusTone.action : StatusTone.waiting,
              icon: Icons.person_add_alt_rounded,
              actionLabel: isSender ? l.dealActionRecipient : null,
              onAction: isSender ? () => context.openRecipient(deal.id) : null,
            )
          else if (isSender)
            // The sender's own record, in full. This is the only place the
            // recipient's email is ever rendered, and it is never logged.
            AppInsetGroup(
              child: Column(
                children: [
                  DetailRow(
                    label: l.recipientName,
                    value: Text(recipient.fullName ?? ''),
                  ),
                  if (recipient.email != null)
                    DetailRow(
                      label: l.recipientEmail,
                      value: Text(recipient.email!),
                    ),
                  if (recipient.phone != null && recipient.phone!.isNotEmpty)
                    DetailRow(
                      label: l.recipientPhone,
                      value: Text(recipient.phone!),
                    ),
                ],
              ),
            )
          else
            // The traveller learns that a recipient exists, and after pickup
            // their name — never their email or phone. That asymmetry is the
            // server's, and this branch mirrors it rather than working round it.
            InfoNotice(
              message: recipient.fullName == null
                  ? l.recipientRecordedForTraveler
                  : recipient.fullName!,
              icon: Icons.person_outline_rounded,
            ),
        ],
      ),
    );
  }
}

class _ProtectionSection extends StatelessWidget {
  const _ProtectionSection({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final protection = deal.protection;
    final endsAt = protection?.protectionEndsAt ?? deal.protectionEndsAt;
    if (endsAt == null) return const SizedBox.shrink();

    final payout = protection?.payout;
    final payoutFloor = protection?.payoutFloor;
    final scheduledArrivalFloor =
        payoutFloor?.fundedScheduledArrivalFloorAt ??
        deal.fundedScheduledArrivalFloorAt;
    final payoutEligibleFrom = payoutFloor?.payoutEligibleFrom;

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: l.protectionTitle),
          AppInsetGroup(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  isSender
                      ? l.protectionSenderBody(
                          LocaleFormats.dateTime(locale, endsAt),
                        )
                      : l.protectionTravelerBody(
                          LocaleFormats.dateTime(locale, endsAt),
                        ),
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: context.colors.textSecondary,
                  ),
                ),
                const SizedBox(height: AppSpace.lg),
                if (endsAt.isAfter(DateTime.now()))
                  CodeCountdown(target: endsAt, label: l.protectionEndsInLabel)
                else
                  Text(
                    l.protectionEnded,
                    style: Theme.of(context).textTheme.bodyMedium,
                  ),
                if (scheduledArrivalFloor != null) ...[
                  const SizedBox(height: AppSpace.md),
                  Text(
                    '${l.earlyArrivalScheduledArrivalLabel}: ${LocaleFormats.dateTime(locale, scheduledArrivalFloor)}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: context.colors.textSecondary,
                    ),
                  ),
                ],
                if (payoutEligibleFrom != null) ...[
                  const SizedBox(height: AppSpace.xs),
                  Text(
                    '${l.earlyArrivalPayoutProtectedGateLabel}: ${LocaleFormats.dateTime(locale, payoutEligibleFrom)}',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: context.colors.textSecondary,
                    ),
                  ),
                ],
                if (scheduledArrivalFloor != null ||
                    (deal.arrival?.isConfirmed ?? false) ||
                    (deal.arrival?.isPendingConfirmation ?? false)) ...[
                  const SizedBox(height: AppSpace.md),
                  InfoNotice(
                    message: l.earlyArrivalPayoutFloorExplanation,
                    tone: StatusTone.neutral,
                    icon: Icons.shield_outlined,
                  ),
                ],
                if (payout != null && !isSender) ...[
                  const SizedBox(height: AppSpace.lg),
                  Builder(
                    builder: (context) {
                      final copy = payoutStatusCopy(context, payout.status);
                      return StatusPill(
                        label: copy.label,
                        tone: copy.tone,
                        icon: copy.icon,
                        compact: true,
                      );
                    },
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _DisputeSection extends StatelessWidget {
  const _DisputeSection({required this.deal});

  final Deal deal;

  @override
  Widget build(BuildContext context) {
    final dispute = deal.dispute;
    // An active dispute is already surfaced at the top; this is the closed
    // record, kept visible because a resolution moved money.
    if (dispute == null || dispute.isActive) return const SizedBox.shrink();

    final l = L.of(context);
    final copy = disputeStatusCopy(context, dispute.status);

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: l.disputeResolutionTitle),
          AppCard(
            onTap: () => context.openDispute(dispute.id),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    disputeCategoryLabel(context, dispute.category),
                    style: Theme.of(context).textTheme.titleSmall,
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
          ),
        ],
      ),
    );
  }
}

class _RatingSection extends StatelessWidget {
  const _RatingSection({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final ratings = deal.ratings;
    if (ratings == null || ratings.isUnavailable) {
      return const SizedBox.shrink();
    }

    // Driven by the server's rating state, not by re-deriving one from the
    // booleans. Only `available` may offer the rate action: once the viewer has
    // rated, the section goes passive instead of continuing to ask. The
    // section also outlives `window_open` so a revealed rating stays readable.
    final revealed = ratings.revealedCounterpartRating;
    final body = switch (ratings) {
      _ when ratings.isActionable => InfoNotice(
        message: ratings.counterpartySubmitted
            ? l.ratingHiddenUntilBoth
            : (isSender ? l.ratingSenderPrompt : l.ratingTravelerPrompt),
        tone: StatusTone.action,
        icon: ratings.counterpartySubmitted
            ? Icons.visibility_off_outlined
            : Icons.star_outline_rounded,
        actionLabel: l.dealActionRate,
        onAction: () => context.openRate(deal.id),
      ),
      _ when ratings.isAwaitingCounterparty => InfoNotice(
        message: l.ratingWaitingForOther,
        icon: Icons.hourglass_top_rounded,
      ),
      _ when ratings.isRevealed => _RevealedRating(rating: revealed),
      _ when ratings.isExpired => InfoNotice(
        message: l.ratingWindowClosed,
        icon: Icons.schedule_rounded,
      ),
      _ => null,
    };
    if (body == null) return const SizedBox.shrink();

    final title = switch (ratings) {
      _ when ratings.isActionable => l.ratingTitle,
      _ when ratings.isExpired => l.ratingClosedTitle,
      _ => l.ratingSubmittedTitle,
    };

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SectionHeader(title: title),
          body,
        ],
      ),
    );
  }
}

/// The counterpart's rating, shown only after the server reveals it.
///
/// [rating] is null when the reveal period passed without the counterpart
/// rating at all — there is genuinely nothing to show, and inventing an empty
/// score would read as a bad review.
class _RevealedRating extends StatelessWidget {
  const _RevealedRating({required this.rating});

  final Rating? rating;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final value = rating;

    if (value == null) {
      return InfoNotice(
        message: l.ratingWaitingForOther,
        icon: Icons.hourglass_top_rounded,
      );
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Icon(Icons.star_rounded, size: 20, color: c.brand),
              const SizedBox(width: AppSpace.sm),
              Expanded(
                child: Text(
                  l.ratingTheirsTitle,
                  style: text.titleSmall?.copyWith(fontWeight: FontWeight.w600),
                ),
              ),
              Text(
                l.ratingScoreLabel(value.score),
                style: text.bodyMedium?.copyWith(fontWeight: FontWeight.w600),
              ),
            ],
          ),
          if (value.tags.isNotEmpty) ...[
            const SizedBox(height: AppSpace.sm),
            Wrap(
              spacing: AppSpace.sm,
              runSpacing: AppSpace.sm,
              children: [
                // Server-authored vocabulary, rendered as given — the same
                // treatment the ratings list uses.
                for (final tag in value.tags)
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: AppSpace.md,
                      vertical: AppSpace.xs,
                    ),
                    decoration: BoxDecoration(
                      color: c.neutralSoft,
                      borderRadius: AppRadius.rPill,
                    ),
                    child: Text(
                      tag.replaceAll('_', ' '),
                      style: text.bodySmall,
                    ),
                  ),
              ],
            ),
          ],
          if ((value.comment ?? '').isNotEmpty) ...[
            const SizedBox(height: AppSpace.sm),
            Text(value.comment!, style: text.bodyMedium),
          ],
          const SizedBox(height: AppSpace.sm),
          Text(
            l.ratingRevealedNote,
            style: text.bodySmall?.copyWith(color: c.textSecondary),
          ),
        ],
      ),
    );
  }
}

/// Destructive and rare actions, kept at the bottom where they cannot be hit
/// by accident.
class _SecondaryActions extends StatelessWidget {
  const _SecondaryActions({required this.deal, required this.isSender});

  final Deal deal;
  final bool isSender;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final cancellation = deal.cancellation;

    // Disputes open at pickup and close with the protection window. The server
    // owns that window; this only asks whether we are inside it.
    final canDispute = deal.availableActions.contains('open_dispute');

    return Column(
      children: [
        if (canDispute)
          AppButton(
            label: l.dealActionDispute,
            variant: AppButtonVariant.tertiary,
            icon: Icons.gavel_rounded,
            onPressed: () => context.openDisputeForm(deal.id),
          ),
        if (cancellation?.allowed ?? false) ...[
          const SizedBox(height: AppSpace.sm),
          AppButton(
            label: l.dealActionCancel,
            variant: AppButtonVariant.destructive,
            onPressed: () => context.openCancel(deal.id),
          ),
        ] else if (cancellation?.isAfterPickup ?? false) ...[
          const SizedBox(height: AppSpace.sm),
          InfoNotice(message: l.cancelAfterPickupBody),
        ],
      ],
    );
  }
}
