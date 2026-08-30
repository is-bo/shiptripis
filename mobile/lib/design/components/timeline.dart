/// The delivery lifecycle, rendered as a line.
///
/// This is the route motif turned inward: where `route.dart` draws the
/// physical journey, this draws the deal's journey through its states. Same
/// rail, same nodes, same reading direction, so a user learns one visual idea
/// and applies it twice.
///
/// Two rules:
///
/// * **A step's state comes from the server.** A step is done because the API
///   returned a timestamp for it, not because the client thinks it should be.
///   [LifecycleStep] carries no logic; the caller maps API state onto it.
///
/// * **"Waiting on you" is visually distinct from "waiting on them".** The
///   single most useful thing this component can tell someone is whether the
///   delivery is stuck on their own action, so that state gets the attention
///   colour and an explicit label rather than a shared "in progress" grey.
library;

import 'package:flutter/material.dart';

import '../tokens.dart';
import 'primitives.dart';
import 'status.dart';

enum LifecycleState {
  /// Finished. Carries a timestamp label.
  done,

  /// The current step, and it needs this user to act.
  waitingOnYou,

  /// The current step, and it needs the other party, a provider, or a timer.
  waitingOnThem,

  /// Not reached yet.
  upcoming,

  /// Reached and went wrong — a failed payment, a dispute, a cancellation.
  failed,
}

@immutable
class LifecycleStep {
  const LifecycleStep({
    required this.label,
    required this.state,
    this.detail,
    this.timeLabel,
    this.actionLabel,
    this.onAction,
  });

  final String label;
  final LifecycleState state;

  /// One line of explanation. Present on the current step, usually absent
  /// elsewhere — a timeline where every row explains itself is a wall of text.
  final String? detail;

  /// Formatted timestamp for a completed step.
  final String? timeLabel;

  /// The action that advances this step. Only ever on a [waitingOnYou] step.
  final String? actionLabel;
  final VoidCallback? onAction;
}

class LifecycleTimeline extends StatelessWidget {
  const LifecycleTimeline({
    required this.steps,
    this.collapseCompleted = false,
    super.key,
  });

  final List<LifecycleStep> steps;

  /// Hides all but the last completed step. For a long-running delivery whose
  /// early history is no longer interesting.
  final bool collapseCompleted;

  @override
  Widget build(BuildContext context) {
    if (steps.isEmpty) return const SizedBox.shrink();

    var visible = steps;
    var hiddenCount = 0;
    if (collapseCompleted) {
      final lastDone = steps.lastIndexWhere(
        (s) => s.state == LifecycleState.done,
      );
      if (lastDone > 0) {
        hiddenCount = lastDone;
        visible = steps.sublist(lastDone);
      }
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (hiddenCount > 0) _CollapsedRow(count: hiddenCount),
        for (var i = 0; i < visible.length; i++)
          _StepRow(
            step: visible[i],
            isFirst: i == 0 && hiddenCount == 0,
            isLast: i == visible.length - 1,
          ),
      ],
    );
  }
}

const double _railWidth = 26;

class _CollapsedRow extends StatelessWidget {
  const _CollapsedRow({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    return SizedBox(
      height: 26,
      child: Row(
        children: [
          SizedBox(
            width: _railWidth,
            child: Center(
              child: Container(width: 1.5, color: c.hairlineStrong),
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Text(
            '+$count',
            style: Theme.of(
              context,
            ).textTheme.bodySmall?.copyWith(color: c.textTertiary),
          ),
        ],
      ),
    );
  }
}

class _StepRow extends StatelessWidget {
  const _StepRow({
    required this.step,
    required this.isFirst,
    required this.isLast,
  });

  final LifecycleStep step;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    final tone = switch (step.state) {
      LifecycleState.done => StatusTone.good,
      LifecycleState.waitingOnYou => StatusTone.action,
      LifecycleState.waitingOnThem => StatusTone.waiting,
      LifecycleState.upcoming => StatusTone.neutral,
      LifecycleState.failed => StatusTone.bad,
    };
    final style = StatusStyle.of(context, tone);
    final isCurrent =
        step.state == LifecycleState.waitingOnYou ||
        step.state == LifecycleState.waitingOnThem;
    final isFuture = step.state == LifecycleState.upcoming;

    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: _railWidth,
            child: Column(
              children: [
                SizedBox(
                  height: 8,
                  child: isFirst
                      ? null
                      : Center(
                          child: Container(width: 1.5, color: c.hairlineStrong),
                        ),
                ),
                _Node(state: step.state, accent: style.accent),
                Expanded(
                  child: isLast
                      ? const SizedBox.shrink()
                      : Center(
                          child: Container(
                            width: 1.5,
                            // The rail ahead of the current step is lighter:
                            // the future is drawn, but not asserted.
                            color: isFuture || isCurrent
                                ? c.hairline
                                : c.hairlineStrong,
                          ),
                        ),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpace.md),
          Expanded(
            child: Padding(
              padding: const EdgeInsets.only(bottom: AppSpace.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          step.label,
                          style: text.titleSmall?.copyWith(
                            color: isFuture ? c.textTertiary : c.textPrimary,
                            fontWeight: isCurrent
                                ? FontWeight.w700
                                : FontWeight.w600,
                          ),
                        ),
                      ),
                      if (step.timeLabel != null) ...[
                        const SizedBox(width: AppSpace.sm),
                        Text(
                          step.timeLabel!,
                          style: text.bodySmall?.copyWith(
                            color: c.textTertiary,
                          ),
                        ),
                      ],
                    ],
                  ),
                  if (step.detail != null) ...[
                    const SizedBox(height: AppSpace.xs),
                    Text(
                      step.detail!,
                      style: text.bodySmall?.copyWith(
                        color: isFuture ? c.textTertiary : c.textSecondary,
                      ),
                    ),
                  ],
                  if (step.actionLabel != null && step.onAction != null) ...[
                    const SizedBox(height: AppSpace.md),
                    AppButton(
                      label: step.actionLabel!,
                      onPressed: step.onAction,
                      expand: false,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Node extends StatelessWidget {
  const _Node({required this.state, required this.accent});

  final LifecycleState state;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    final c = context.colors;

    // Shape, not only colour: done is a tick, failed is a cross, the current
    // step is a filled ring, the future is a hollow dot. Legible in greyscale
    // and to anyone who cannot separate the hues.
    return switch (state) {
      LifecycleState.done => Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(color: accent, shape: BoxShape.circle),
        child: Icon(Icons.check_rounded, size: 12, color: c.surface),
      ),
      LifecycleState.failed => Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(color: accent, shape: BoxShape.circle),
        child: Icon(Icons.close_rounded, size: 12, color: c.surface),
      ),
      LifecycleState.waitingOnYou || LifecycleState.waitingOnThem => Container(
        width: 18,
        height: 18,
        decoration: BoxDecoration(
          color: c.surface,
          shape: BoxShape.circle,
          border: Border.all(color: accent, width: 3),
        ),
      ),
      LifecycleState.upcoming => Padding(
        padding: const EdgeInsets.all(4),
        child: Container(
          width: 10,
          height: 10,
          decoration: BoxDecoration(
            color: c.surface,
            shape: BoxShape.circle,
            border: Border.all(color: c.hairlineStrong, width: 1.5),
          ),
        ),
      ),
    };
  }
}
