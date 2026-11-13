/// A sender's view of new times: old against new, and "Accept" or "Decline".
///
/// Whether this person is asked (`can_answer`), whether the parcel is already
/// collected (`informed`) and which actions then exist (`actions`) are the
/// server's. Declining does not cancel anything: it makes a later
/// cancellation the traveler's doing, and the amounts shown are the server's
/// cancellation quote, read after the decline stands.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/money.dart';
import '../../design/components/navigation.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/layout/app_scaffold.dart';
import '../../design/tokens.dart';
import '../../domain/cancellation.dart';
import '../../domain/problems.dart';
import '../../domain/schedule_change.dart';
import '../../l10n/app_localizations.dart';
import '../journeys/schedule_change_widgets.dart';
import '../problems/problem_widgets.dart';

final _quoteAfterDeclineProvider = FutureProvider.autoDispose
    .family<CancellationQuote, int>((ref, dealId) async {
      final repo = ref.watch(dealRepositoryProvider);
      return repo.cancellationQuote(dealId, cancelToken: cancelOnDispose(ref));
    });

class ScheduleChangeAnswerScreen extends ConsumerStatefulWidget {
  const ScheduleChangeAnswerScreen({required this.dealId, super.key});

  final int dealId;

  @override
  ConsumerState<ScheduleChangeAnswerScreen> createState() =>
      _ScheduleChangeAnswerScreenState();
}

class _ScheduleChangeAnswerScreenState
    extends ConsumerState<ScheduleChangeAnswerScreen> {
  bool _busy = false;
  String? _error;

  Future<void> _answer({required bool accept}) async {
    final l = L.of(context);
    if (!accept) {
      final confirmed = await confirmAction(
        context,
        title: l.scheduleDeclineConfirmTitle,
        body: l.scheduleDeclineConfirmBody,
        confirmLabel: l.scheduleDeclineAction,
        cancelLabel: l.scheduleDeclineKeep,
      );
      if (!confirmed || !mounted) return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(dealRepositoryProvider)
          .answerScheduleChange(widget.dealId, accept: accept);
      if (!mounted) return;
      ref
        ..invalidate(dealScheduleChangeProvider(widget.dealId))
        ..invalidate(dealDetailProvider(widget.dealId))
        // The quote now reflects the answer.
        ..invalidate(_quoteAfterDeclineProvider(widget.dealId));
      AppSnack.success(
        context,
        accept ? l.scheduleAcceptedSnack : l.scheduleDeclinedSnack,
      );
    } on ApiException catch (error) {
      if (!mounted) return;
      // The change may have applied, been withdrawn or the parcel collected
      // since this screen loaded: show what is true now.
      ref.invalidate(dealScheduleChangeProvider(widget.dealId));
      setState(() {
        _error =
            _answerFailure(l, error) ?? describeFailure(context, error).body;
      });
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  String? _answerFailure(L l, ApiException error) {
    if (error.kind == ApiFailureKind.offline ||
        error.kind == ApiFailureKind.timeout) {
      return l.scheduleErrorOffline;
    }
    return switch (error.code.raw) {
      'schedule_change_not_pending' ||
      'schedule_change_not_found' => l.scheduleErrorNotWaiting,
      'schedule_change_answer_not_needed' => l.scheduleErrorNoAnswerNeeded,
      _ => null,
    };
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final change = ref.watch(dealScheduleChangeProvider(widget.dealId));
    final loaded = change.value;

    return AppScaffold(
      topBar: AppTopBar(title: l.scheduleAnswerTitle, showBack: true),
      body: RefreshIndicator(
        onRefresh: () async =>
            ref.invalidate(dealScheduleChangeProvider(widget.dealId)),
        child: AsyncView<SenderScheduleChange?>(
          value: change,
          onRetry: () =>
              ref.invalidate(dealScheduleChangeProvider(widget.dealId)),
          loading: () => ListView(
            padding: AppScrollPadding.page(context),
            children: const [SkeletonDetail()],
          ),
          data: (data) {
            if (data == null) {
              return ListView(
                padding: AppScrollPadding.page(context),
                children: [
                  AppEmptyState(
                    title: l.scheduleNoneTitle,
                    body: l.scheduleNoneBody,
                    icon: Icons.event_available_outlined,
                  ),
                ],
              );
            }
            return ListView(
              padding: AppScrollPadding.pageWithFooter(context),
              children: [
                _Body(
                  change: data,
                  dealId: widget.dealId,
                  error: _error,
                  busy: _busy,
                  onAnswer: _answer,
                ),
              ],
            );
          },
        ),
      ),
      footer: loaded != null && loaded.canAnswer
          ? _Footer(change: loaded, busy: _busy, onAnswer: _answer)
          : null,
    );
  }
}

/// Accept is the primary action, Decline sits beside it with the same weight
/// of target but a quieter style. Changing a mind is allowed while it waits,
/// so each button names the other answer when one is already given.
class _Footer extends StatelessWidget {
  const _Footer({
    required this.change,
    required this.busy,
    required this.onAnswer,
  });

  final SenderScheduleChange change;
  final bool busy;
  final Future<void> Function({required bool accept}) onAnswer;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final accepted = change.consent == ConsentState.accepted;
    final declined = change.consent == ConsentState.declined;

    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        if (!accepted)
          AppButton(
            label: declined ? l.scheduleAcceptInstead : l.scheduleAcceptAction,
            isLoading: busy,
            onPressed: () => onAnswer(accept: true),
          ),
        if (!accepted && !declined) const SizedBox(height: AppSpace.sm),
        if (!declined)
          AppButton(
            label: accepted
                ? l.scheduleDeclineInstead
                : l.scheduleDeclineAction,
            variant: AppButtonVariant.secondary,
            onPressed: busy ? null : () => onAnswer(accept: false),
          ),
      ],
    );
  }
}

class _Body extends ConsumerWidget {
  const _Body({
    required this.change,
    required this.dealId,
    required this.error,
    required this.busy,
    required this.onAnswer,
  });

  final SenderScheduleChange change;
  final int dealId;
  final String? error;
  final bool busy;
  final Future<void> Function({required bool accept}) onAnswer;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    final (headline, tone, icon) = switch ((
      change.informed,
      change.status,
      change.consent,
    )) {
      (true, _, _) => (
        l.scheduleInformedHeadline,
        StatusTone.neutral,
        Icons.event_note_outlined,
      ),
      (_, ScheduleChangeStatus.applied, _) => (
        l.scheduleAppliedHeadline,
        StatusTone.good,
        Icons.event_available_outlined,
      ),
      (_, ScheduleChangeStatus.withdrawn, _) => (
        l.scheduleWithdrawnHeadline,
        StatusTone.neutral,
        Icons.event_busy_outlined,
      ),
      (_, _, ConsentState.accepted) => (
        l.scheduleYouAcceptedHeadline,
        StatusTone.good,
        Icons.check_circle_outline_rounded,
      ),
      (_, _, ConsentState.declined) => (
        l.scheduleYouDeclinedHeadline,
        StatusTone.waiting,
        Icons.event_busy_outlined,
      ),
      _ => (l.scheduleAskedHeadline, StatusTone.action, Icons.schedule_rounded),
    };

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        InfoNotice(
          title: headline,
          message: change.informed
              ? l.scheduleInformedBody
              : switch ((change.status, change.consent)) {
                  (ScheduleChangeStatus.applied, _) => l.scheduleAppliedBody,
                  (ScheduleChangeStatus.withdrawn, _) =>
                    l.scheduleWithdrawnBody,
                  (_, ConsentState.accepted) => l.scheduleDealAcceptedBody,
                  (_, ConsentState.declined) => l.scheduleDealDeclinedBody,
                  _ => l.scheduleAskedBody,
                },
          tone: tone,
          icon: icon,
        ),
        const SizedBox(height: AppSpace.xl),

        SectionHeader(title: l.scheduleCompareTitle),
        FullWidthGroup(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TimeDiffRow(
                label: l.schedulePickup,
                before: change.pickupBefore,
                after: change.pickupAfter,
              ),
              TimeDiffRow(
                label: l.scheduleArrival,
                before: change.arrivalBefore,
                after: change.arrivalAfter,
              ),
              if (change.deadlineAt != null)
                Padding(
                  padding: const EdgeInsets.only(top: AppSpace.sm),
                  child: Text(
                    l.scheduleYourDeadline(
                      LocaleFormats.dateTime(locale, change.deadlineAt!),
                    ),
                    style: text.bodySmall?.copyWith(color: c.textSecondary),
                  ),
                ),
            ],
          ),
        ),

        if (change.reasons.isNotEmpty && !change.informed) ...[
          const SizedBox(height: AppSpace.lg),
          SectionHeader(title: l.scheduleWhyTitle),
          for (final reason in change.reasons)
            Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.xs),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Icon(Icons.circle, size: 6, color: c.textSecondary),
                  ),
                  const SizedBox(width: AppSpace.sm),
                  Expanded(
                    child: Text(
                      changeReasonText(l, reason),
                      style: text.bodyMedium,
                    ),
                  ),
                ],
              ),
            ),
        ],

        if (change.reason.trim().isNotEmpty) ...[
          const SizedBox(height: AppSpace.lg),
          SectionHeader(title: l.scheduleTravelerNote),
          FullWidthGroup(
            child: Text(change.reason.trim(), style: text.bodyMedium),
          ),
        ],

        if (change.legs.any((leg) => leg.changed)) ...[
          const SizedBox(height: AppSpace.lg),
          SectionHeader(title: l.scheduleLegsTitle),
          FullWidthGroup(child: LegChangeList(legs: change.legs)),
        ],

        if (error != null) ...[
          const SizedBox(height: AppSpace.lg),
          InfoNotice(
            message: error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
        ],

        if (change.declinedAndWaiting) ...[
          const SizedBox(height: AppSpace.xl),
          _DeclinedConsequence(dealId: dealId),
        ],

        if (change.informed && change.actions.isNotEmpty) ...[
          const SizedBox(height: AppSpace.xl),
          _InformedActions(dealId: dealId, actions: change.actions),
        ],
      ],
    );
  }
}

/// What cancelling would now mean: the server's quote, read after the decline
/// stands, with the line that says whose cancellation it is.
class _DeclinedConsequence extends ConsumerWidget {
  const _DeclinedConsequence({required this.dealId});

  final int dealId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    final quote = ref.watch(_quoteAfterDeclineProvider(dealId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.scheduleIfYouCancelTitle),
        AsyncView<CancellationQuote>(
          value: quote,
          onRetry: () => ref.invalidate(_quoteAfterDeclineProvider(dealId)),
          loading: () => const SkeletonCardList(count: 1),
          error: (error) => InlineFailure(
            error: error,
            onRetry: () => ref.invalidate(_quoteAfterDeclineProvider(dealId)),
          ),
          data: (data) {
            if (!data.allowed) {
              return InfoNotice(message: l.scheduleCancelNotAvailable);
            }
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (data.isMoneyless)
                  InfoNotice(message: l.depositRefundNote)
                else ...[
                  MoneyBreakdown(
                    lines: [
                      if (data.collected != null)
                        MoneyLine(label: l.moneyTotal, amount: data.collected!),
                      if (data.travelerCompensation != null &&
                          data.travelerCompensation!.isPositive)
                        MoneyLine(
                          label: l.moneyTravelerCompensation,
                          amount: data.travelerCompensation!,
                        ),
                      if (data.platformFee != null &&
                          data.platformFee!.isPositive)
                        MoneyLine(
                          label: l.moneyPlatformFee,
                          amount: data.platformFee!,
                        ),
                      if (data.senderRefund != null)
                        MoneyLine.total(
                          label: l.moneyRefundToYou,
                          amount: data.senderRefund!,
                        ),
                    ],
                  ),
                  if (data.causedByTraveler) ...[
                    const SizedBox(height: AppSpace.sm),
                    Text(
                      l.scheduleCancelCountsAsTraveler,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: context.colors.textSecondary,
                      ),
                    ),
                  ],
                ],
                const SizedBox(height: AppSpace.lg),
                AppButton(
                  label: l.dealActionCancel,
                  variant: AppButtonVariant.destructive,
                  onPressed: () => context.openCancel(dealId),
                ),
              ],
            );
          },
        ),
      ],
    );
  }
}

/// A collected parcel: the sender cannot cancel, and the server names what
/// they can do. Only the two that exist today are drawn.
class _InformedActions extends ConsumerWidget {
  const _InformedActions({required this.dealId, required this.actions});

  final int dealId;
  final List<String> actions;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final l = L.of(context);
    // The kinds the delivery takes now are the server's list.
    final kinds = [
      for (final kind
          in ref.watch(dealProblemsProvider(dealId)).value?.reportableKinds ??
              const <ProblemKind>[])
        if (!kind.isNoShow) kind,
    ];
    final canReport = actions.contains('report_problem') && kinds.isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.scheduleInformedActionsTitle),
        if (canReport)
          AppButton(
            label: l.problemReportAction,
            icon: Icons.report_problem_outlined,
            variant: AppButtonVariant.secondary,
            onPressed: () =>
                showProblemSheet(context, dealId: dealId, kinds: kinds),
          ),
        if (canReport && actions.contains('open_dispute'))
          const SizedBox(height: AppSpace.sm),
        if (actions.contains('open_dispute'))
          AppButton(
            label: l.dealActionDispute,
            icon: Icons.gavel_rounded,
            variant: AppButtonVariant.tertiary,
            onPressed: () => context.openDisputeForm(dealId),
          ),
      ],
    );
  }
}
