/// Shared pieces for route changes: the before/after times, the reasons, and
/// the traveler's section on a journey.
///
/// Nothing here measures a threshold or decides who must agree. The server's
/// `material`, `informed` and `reasons` are drawn as given.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/schedule_change.dart';
import '../../l10n/app_localizations.dart';

String changeReasonText(L l, ChangeReason reason) => switch (reason) {
  ChangeReason.deadline => l.scheduleReasonDeadline,
  ChangeReason.shift => l.scheduleReasonShift,
  ChangeReason.pickup => l.scheduleReasonPickup,
};

/// One line, "Arrival", the old time struck through and the new one in bold.
/// A time that did not move shows once.
class TimeDiffRow extends StatelessWidget {
  const TimeDiffRow({
    required this.label,
    required this.before,
    required this.after,
    super.key,
  });

  final String label;
  final DateTime? before;
  final DateTime? after;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    String fmt(DateTime when) => LocaleFormats.dateTime(locale, when);

    final moved = before != null && after != null && before != after;
    final shown = after ?? before;

    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpace.xs),
      child: Semantics(
        container: true,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: text.labelMedium?.copyWith(color: c.textTertiary),
            ),
            const SizedBox(height: 2),
            if (shown == null)
              Text('—', style: text.bodyMedium)
            else if (!moved)
              Text(fmt(shown), style: text.bodyMedium)
            else ...[
              Text(
                fmt(before!),
                style: text.bodyMedium?.copyWith(
                  color: c.textTertiary,
                  decoration: TextDecoration.lineThrough,
                ),
              ),
              Text(
                fmt(after!),
                style: text.bodyLarge?.copyWith(fontWeight: FontWeight.w600),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// The legs whose times changed, each as "Marseille → Algiers" with its
/// departure and arrival before and after. Legs that did not change are left
/// out: the traveler knows their own trip.
class LegChangeList extends StatelessWidget {
  const LegChangeList({required this.legs, super.key});

  final List<LegTimeChange> legs;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final changed = legs.where((leg) => leg.changed).toList(growable: false);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var i = 0; i < changed.length; i++) ...[
          if (i > 0) const Divider(height: AppSpace.xl),
          if (changed[i].originName.isNotEmpty ||
              changed[i].destinationName.isNotEmpty)
            Text(
              '${changed[i].originName} → ${changed[i].destinationName}',
              style: text.titleSmall,
            ),
          TimeDiffRow(
            label: l.scheduleDeparture,
            before: changed[i].departBefore,
            after: changed[i].departAfter,
          ),
          TimeDiffRow(
            label: l.scheduleArrival,
            before: changed[i].arriveBefore,
            after: changed[i].arriveAfter,
          ),
        ],
      ],
    );
  }
}

// ---------------------------------------------------------------------------
// The traveler's section on the journey
// ---------------------------------------------------------------------------

String? scheduleFailureMessage(L l, ApiException error) {
  if (error.kind == ApiFailureKind.offline ||
      error.kind == ApiFailureKind.timeout) {
    return l.scheduleErrorOffline;
  }
  return switch (error.code.raw) {
    'journey_not_owned' => l.journeyErrorNotOwned,
    'journey_not_reschedulable' => l.scheduleErrorNotReschedulable,
    'schedule_change_empty' => l.scheduleErrorEmpty,
    'schedule_change_pending' => l.scheduleErrorPending,
    'leg_already_arrived' => l.scheduleErrorLegArrived,
    'leg_already_departed' => l.scheduleErrorLegDeparted,
    'leg_departure_in_past' => l.scheduleErrorDepartureInPast,
    'schedule_change_invalid' ||
    'journey_leg_time_invalid' => l.journeyErrorLegTime,
    'journey_leg_arrival_required' => l.journeyErrorLegArrivalRequired,
    'journey_leg_time_order_invalid' => l.journeyErrorLegTimeOrder,
    'schedule_change_not_found' ||
    'schedule_change_not_pending' => l.scheduleErrorNotWaiting,
    _ => null,
  };
}

/// "Change times", and the state of the change that is waiting.
class ScheduleChangeSection extends ConsumerStatefulWidget {
  const ScheduleChangeSection({required this.journeyId, super.key});

  final int journeyId;

  @override
  ConsumerState<ScheduleChangeSection> createState() =>
      _ScheduleChangeSectionState();
}

class _ScheduleChangeSectionState extends ConsumerState<ScheduleChangeSection> {
  bool _busy = false;

  Future<void> _withdraw(ScheduleChange change) async {
    final l = L.of(context);
    setState(() => _busy = true);
    try {
      await ref
          .read(journeyRepositoryProvider)
          .withdrawScheduleChange(widget.journeyId, change.id);
      if (!mounted) return;
      ref.invalidate(journeyScheduleChangesProvider(widget.journeyId));
      AppSnack.success(context, l.scheduleWithdrawn);
    } on ApiException catch (error) {
      if (!mounted) return;
      ref.invalidate(journeyScheduleChangesProvider(widget.journeyId));
      AppSnack.failure(
        context,
        error,
        fallback: scheduleFailureMessage(l, error),
      );
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final changes = ref.watch(journeyScheduleChangesProvider(widget.journeyId));
    // Optional: a failure here must not take the journey page with it.
    final list = changes.value;
    if (list == null) return const SizedBox.shrink();

    final waiting = list.where((c) => c.isWaiting).firstOrNull;
    final latest = list.firstOrNull;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.scheduleSectionTitle),
        if (waiting != null)
          _WaitingCard(
            change: waiting,
            busy: _busy,
            onWithdraw: () => _withdraw(waiting),
          )
        else ...[
          if (latest != null && latest.status == ScheduleChangeStatus.withdrawn)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.md),
              child: InfoNotice(
                message: latest.withdrawnBy == 'no_longer_valid'
                    ? l.scheduleWithdrawnNoLongerValid
                    : l.scheduleWithdrawnByYou,
                tone: StatusTone.neutral,
                icon: Icons.event_busy_outlined,
              ),
            ),
          Text(
            l.scheduleSectionIntro,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
              color: context.colors.textSecondary,
            ),
          ),
          const SizedBox(height: AppSpace.md),
          AppButton(
            label: l.scheduleChangeAction,
            icon: Icons.edit_calendar_outlined,
            variant: AppButtonVariant.secondary,
            onPressed: () => context.openChangeTimes(widget.journeyId),
          ),
        ],
        const SizedBox(height: AppSpace.xl),
      ],
    );
  }
}

class _WaitingCard extends StatelessWidget {
  const _WaitingCard({
    required this.change,
    required this.busy,
    required this.onWithdraw,
  });

  final ScheduleChange change;
  final bool busy;
  final VoidCallback onWithdraw;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final asked = change.parcels.where((p) => p.material).toList();

    return AppCard(
      accent: StatusTone.waiting,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StatusPill(
            label: l.scheduleWaitingPill(change.waitingFor),
            tone: StatusTone.waiting,
            icon: Icons.hourglass_top_rounded,
            compact: true,
          ),
          const SizedBox(height: AppSpace.md),
          Text(l.scheduleWaitingBody, style: text.bodyMedium),
          const SizedBox(height: AppSpace.lg),
          LegChangeList(legs: change.legs),
          if (asked.isNotEmpty) ...[
            const Divider(height: AppSpace.xl),
            Text(l.scheduleSendersTitle, style: text.titleSmall),
            const SizedBox(height: AppSpace.sm),
            for (final parcel in asked)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: AppSpace.xs),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        parcel.trackingNumber ?? l.scheduleParcelFallback,
                        style: text.bodyMedium,
                      ),
                    ),
                    Text(
                      switch (parcel.consent) {
                        ConsentState.accepted => l.scheduleConsentAccepted,
                        ConsentState.declined => l.scheduleConsentDeclined,
                        _ => l.scheduleConsentPending,
                      },
                      style: text.bodySmall?.copyWith(
                        color: parcel.consent == ConsentState.declined
                            ? c.danger
                            : c.textSecondary,
                      ),
                    ),
                  ],
                ),
              ),
          ],
          const SizedBox(height: AppSpace.lg),
          AppButton(
            label: l.scheduleWithdrawAction,
            variant: AppButtonVariant.tertiary,
            isLoading: busy,
            onPressed: onWithdraw,
          ),
        ],
      ),
    );
  }
}

/// An inset group that spans the page: [AppInsetGroup] shrinks to its content.
class FullWidthGroup extends StatelessWidget {
  const FullWidthGroup({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) => SizedBox(
    width: double.infinity,
    child: AppInsetGroup(child: child),
  );
}
