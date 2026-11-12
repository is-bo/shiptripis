/// The trip-progress controls: the stepper on a journey, the question card on
/// Home and the sheet a reminder opens.
///
/// What a report is, and is not: a statement the traveler makes about a leg.
/// Senders read it marked "reported by the traveler". Nothing here decides
/// order or time. The server lists the buttons it will accept
/// (`next_actions`), and this file draws exactly those.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/format/locale_formats.dart';
import '../../design/components/feedback.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/components/timeline.dart';
import '../../design/tokens.dart';
import '../../domain/progress.dart';
import '../../l10n/app_localizations.dart';
import 'progress_actions.dart';

// ---------------------------------------------------------------------------
// The stepper on the journey
// ---------------------------------------------------------------------------

/// "Trip progress": one step per leg, one large button for what comes next,
/// and an undo for the last update while the server still allows it.
class JourneyProgressSection extends ConsumerStatefulWidget {
  const JourneyProgressSection({required this.journeyId, super.key});

  final int journeyId;

  @override
  ConsumerState<JourneyProgressSection> createState() =>
      _JourneyProgressSectionState();
}

class _JourneyProgressSectionState
    extends ConsumerState<JourneyProgressSection> {
  bool _busy = false;
  String? _error;

  Future<void> _run(Future<String?> Function() action, String? success) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final failure = await action();
    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = failure;
    });
    if (failure == null && success != null) AppSnack.success(context, success);
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final progress = ref.watch(journeyProgressProvider(widget.journeyId));

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SectionHeader(title: l.progressTitle, subtitle: l.progressIntro),
        AsyncView<JourneyProgress>(
          value: progress,
          onRetry: () =>
              ref.invalidate(journeyProgressProvider(widget.journeyId)),
          loading: () => const SkeletonCardList(count: 1),
          error: (error) => InlineFailure(
            error: error,
            onRetry: () =>
                ref.invalidate(journeyProgressProvider(widget.journeyId)),
          ),
          data: (data) => _content(context, data),
        ),
      ],
    );
  }

  Widget _content(BuildContext context, JourneyProgress data) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    if (data.legs.isEmpty) return const SizedBox.shrink();

    // The current leg is the first one that has not arrived. The server's
    // action list for it is what the button offers.
    final currentIndex = data.legs.indexWhere((leg) => !leg.isFinished);
    final current = currentIndex < 0 ? null : data.legs[currentIndex];
    final action = current?.primaryAction;

    // Undo belongs to the most recent live update that can still be taken
    // back, whichever leg it was on.
    ProgressReport? undoable;
    for (final leg in data.legs) {
      for (final report in leg.liveReports) {
        if (report.canRetract &&
            (undoable == null ||
                report.reportedAt.isAfter(undoable.reportedAt))) {
          undoable = report;
        }
      }
    }

    final steps = [
      for (final (index, leg) in data.legs.indexed)
        LifecycleStep(
          label: l.proofLegLabel(
            leg.position + 1,
            leg.originName,
            leg.destinationName,
          ),
          state: leg.isFinished
              ? LifecycleState.done
              : index == currentIndex
              ? LifecycleState.waitingOnYou
              : LifecycleState.upcoming,
          detail: leg.liveReports.isEmpty
              ? null
              : [
                  for (final report in leg.liveReports)
                    '${progressReportedLabel(l, report.kind)} · '
                        '${LocaleFormats.dateTime(locale, report.reportedAt)}',
                ].join('\n'),
        ),
    ];

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        LifecycleTimeline(steps: steps),
        if (action != null) ...[
          const SizedBox(height: AppSpace.sm),
          AppButton(
            label: progressActionLabel(l, action.kind),
            icon: Icons.flag_outlined,
            isLoading: _busy,
            onPressed: action.canReportNow && current != null
                ? () => _run(
                    () => sendProgress(
                      ref,
                      context,
                      journeyId: widget.journeyId,
                      legId: current.legId,
                      kind: action.kind,
                    ),
                    l.progressSent,
                  )
                : null,
          ),
          const SizedBox(height: AppSpace.sm),
          // A disabled button always says what would enable it.
          Text(
            !action.canReportNow && action.availableAt != null
                ? l.progressAvailableFrom(
                    LocaleFormats.dateTime(locale, action.availableAt!),
                  )
                : l.progressNeedsNetwork,
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: context.colors.textTertiary),
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: _error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
        ],
        if (undoable != null) ...[
          const SizedBox(height: AppSpace.md),
          _UndoRow(
            report: undoable,
            busy: _busy,
            onUndo: () => _run(
              () => undoProgress(
                ref,
                context,
                journeyId: widget.journeyId,
                progressId: undoable!.id,
              ),
              l.progressUndone,
            ),
          ),
        ],
      ],
    );
  }
}

class _UndoRow extends StatelessWidget {
  const _UndoRow({
    required this.report,
    required this.busy,
    required this.onUndo,
  });

  final ProgressReport report;
  final bool busy;
  final VoidCallback onUndo;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    return AppInsetGroup(
      child: Row(
        children: [
          Expanded(
            child: Text(
              '${progressReportedLabel(l, report.kind)}\n'
              '${l.progressUndoHint}',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                color: context.colors.textSecondary,
              ),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          AppButton(
            label: l.progressUndo,
            variant: AppButtonVariant.tertiary,
            expand: false,
            onPressed: busy ? null : onUndo,
          ),
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The question
// ---------------------------------------------------------------------------

/// "Did you depart from {place}?" with "Yes" and "Not yet".
///
/// One piece of UI for Home (a card) and for the reminder (a sheet), so both
/// answer the same way. "Not yet" asks nothing of the server: the question
/// simply goes away for now, and the server asks again on its own schedule.
class ProgressQuestion extends ConsumerStatefulWidget {
  const ProgressQuestion({
    required this.journeyId,
    required this.legId,
    required this.kind,
    required this.place,
    required this.onClose,
    this.showBody = false,
    super.key,
  });

  final int journeyId;
  final int legId;
  final ProgressKind kind;
  final String place;

  /// Called after "Not yet" or after a report went through.
  final VoidCallback onClose;

  /// The sheet explains who sees the answer; the Home card is already terse.
  final bool showBody;

  @override
  ConsumerState<ProgressQuestion> createState() => _ProgressQuestionState();
}

class _ProgressQuestionState extends ConsumerState<ProgressQuestion> {
  bool _busy = false;
  String? _error;

  Future<void> _yes() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    final failure = await sendProgress(
      ref,
      context,
      journeyId: widget.journeyId,
      legId: widget.legId,
      kind: widget.kind,
    );
    if (!mounted) return;
    if (failure == null) {
      widget.onClose();
      return;
    }
    setState(() {
      _busy = false;
      _error = failure;
    });
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          progressQuestionLabel(l, widget.kind, widget.place),
          style: text.titleSmall,
        ),
        if (widget.showBody) ...[
          const SizedBox(height: AppSpace.xs),
          Text(
            l.progressQuestionBody,
            style: text.bodyMedium?.copyWith(color: c.textSecondary),
          ),
        ],
        if (_error != null) ...[
          const SizedBox(height: AppSpace.md),
          InfoNotice(
            message: _error!,
            tone: StatusTone.bad,
            icon: Icons.error_outline_rounded,
          ),
        ],
        const SizedBox(height: AppSpace.lg),
        AppButton(
          label: progressYesLabel(l, widget.kind),
          isLoading: _busy,
          onPressed: _yes,
        ),
        const SizedBox(height: AppSpace.sm),
        AppButton(
          label: l.progressNotYet,
          variant: AppButtonVariant.tertiary,
          onPressed: _busy
              ? null
              : () {
                  ref
                      .read(dismissedProgressQuestionsProvider.notifier)
                      .dismiss(widget.legId, widget.kind);
                  widget.onClose();
                },
        ),
        const SizedBox(height: AppSpace.xs),
        Text(
          l.progressNeedsNetwork,
          style: text.bodySmall?.copyWith(color: c.textTertiary),
        ),
      ],
    );
  }
}

/// The reminder's destination: the same question, as a sheet.
Future<void> showProgressQuestionSheet(
  BuildContext context, {
  required int journeyId,
  required int legId,
  required ProgressKind kind,
  required String place,
}) => showAppSheet<void>(
  context,
  builder: (sheetContext) => AppSheet(
    title: L.of(sheetContext).progressTitle,
    child: ProgressQuestion(
      journeyId: journeyId,
      legId: legId,
      kind: kind,
      place: place,
      showBody: true,
      onClose: () => Navigator.of(sheetContext).maybePop(),
    ),
  ),
);

/// The Home "needs attention" card.
class ProgressQuestionCard extends ConsumerWidget {
  const ProgressQuestionCard({required this.question, super.key});

  final PendingProgressQuestion question;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return AppCard(
      accent: StatusTone.action,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Icon(
              question.kind == ProgressKind.arrived
                  ? Icons.flight_land_rounded
                  : Icons.flight_takeoff_rounded,
              size: 20,
              color: context.colors.attention,
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: ProgressQuestion(
              journeyId: question.journeyId,
              legId: question.legId,
              kind: question.kind,
              place: question.placeName,
              // The question disappears by itself once the server's list
              // refreshes; nothing to close on Home.
              onClose: () {},
            ),
          ),
        ],
      ),
    );
  }
}
