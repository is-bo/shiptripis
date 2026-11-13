/// Problem reports on a delivery: the no-show action and banner, the list of
/// reports, and the sheet that makes one.
///
/// A report is a statement. It cancels nothing, refunds nothing and marks
/// nobody; the sheet says so before it is sent. Which kinds can be reported,
/// and whether the "did not come" window is open, are the server's answers
/// (`DealProblems`): there is no clock and no status test on the phone.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../core/api/api_exception.dart';
import '../../core/format/locale_formats.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/components/status.dart';
import '../../design/tokens.dart';
import '../../domain/deal.dart';
import '../../domain/problems.dart';
import '../../l10n/app_localizations.dart';

// ---------------------------------------------------------------------------
// Words
// ---------------------------------------------------------------------------

String problemKindLabel(L l, ProblemKind kind) => switch (kind) {
  ProblemKind.senderUnavailable => l.problemKindSenderUnavailable,
  ProblemKind.travelerNoShow => l.problemKindTravelerNoShow,
  ProblemKind.recipientUnavailable => l.problemKindRecipientUnavailable,
  ProblemKind.parcelMismatch => l.problemKindParcelMismatch,
  ProblemKind.parcelDamaged => l.problemKindParcelDamaged,
  ProblemKind.tripDisrupted => l.problemKindTripDisrupted,
  ProblemKind.customsDelay => l.problemKindCustomsDelay,
  ProblemKind.other => l.problemKindOther,
};

IconData _kindIcon(ProblemKind kind) => switch (kind) {
  ProblemKind.senderUnavailable ||
  ProblemKind.travelerNoShow => Icons.person_off_outlined,
  ProblemKind.recipientUnavailable => Icons.home_work_outlined,
  ProblemKind.parcelMismatch => Icons.compare_arrows_rounded,
  ProblemKind.parcelDamaged => Icons.broken_image_outlined,
  ProblemKind.tripDisrupted => Icons.flight_land_rounded,
  ProblemKind.customsDelay => Icons.assured_workload_outlined,
  ProblemKind.other => Icons.more_horiz_rounded,
};

/// The report's state in the words of the person who made it or read it.
({String label, StatusTone tone, IconData icon}) _statusCopy(
  L l,
  ProblemStatus status,
) => switch (status) {
  ProblemStatus.open || ProblemStatus.unknown => (
    label: l.problemStatusOpen,
    tone: StatusTone.waiting,
    icon: Icons.hourglass_empty_rounded,
  ),
  ProblemStatus.escalated => (
    label: l.problemStatusEscalated,
    tone: StatusTone.action,
    icon: Icons.support_agent_rounded,
  ),
  ProblemStatus.acknowledged => (
    label: l.problemStatusAcknowledged,
    tone: StatusTone.progress,
    icon: Icons.visibility_outlined,
  ),
  ProblemStatus.closed => (
    label: l.problemStatusClosed,
    tone: StatusTone.neutral,
    icon: Icons.check_circle_outline_rounded,
  ),
};

/// A refusal in the user's terms, or null for the generic failure copy.
String? problemFailureMessage(L l, ApiException error) {
  if (error.kind == ApiFailureKind.offline ||
      error.kind == ApiFailureKind.timeout) {
    return l.problemErrorOffline;
  }
  return switch (error.code.raw) {
    'no_show_report_not_allowed' => l.problemErrorNoShowClosed,
    'problem_report_not_allowed' => l.problemErrorNotAllowed,
    'problem_note_too_long' => l.problemErrorNoteTooLong,
    'not_a_party' => l.stateForbiddenBody,
    _ => null,
  };
}

// ---------------------------------------------------------------------------
// The no-show card and banner, above the delivery's actions
// ---------------------------------------------------------------------------

/// "The sender did not come" / "The traveler did not come", the report's state
/// once it is made, and the banner the other person sees.
///
/// Renders nothing while the server says there is nothing to do or know, and
/// nothing while it loads or fails: a missing optional card must never replace
/// the delivery.
class NoShowBlock extends ConsumerWidget {
  const NoShowBlock({required this.deal, super.key});

  final Deal deal;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final problems = ref.watch(dealProblemsProvider(deal.id)).value;
    if (problems == null) return const SizedBox.shrink();

    final l = L.of(context);
    final mine = problems.myNoShowReport;
    final against = problems.noShowAgainstMe;
    final canChat = deal.matchId != null;
    void openChat() => context.openChatThread(deal.matchId!, dealId: deal.id);

    final children = <Widget>[
      if (against != null)
        InfoNotice(
          title: problems.isSender
              ? l.noShowAgainstSenderTitle
              : l.noShowAgainstTravelerTitle,
          message: problems.isSender
              ? l.noShowAgainstSenderBody
              : l.noShowAgainstTravelerBody,
          tone: StatusTone.action,
          icon: Icons.person_search_outlined,
          actionLabel: canChat ? l.noShowReplyInChat : null,
          onAction: canChat ? openChat : null,
        ),
      if (mine != null)
        _MyNoShowCard(
          problems: problems,
          report: mine,
          onChat: canChat ? openChat : null,
        ),
      if (problems.canReportNoShow) ...[
        if (against != null) const SizedBox(height: AppSpace.md),
        AppButton(
          label: problems.isSender
              ? l.noShowActionTraveler
              : l.noShowActionSender,
          icon: Icons.person_off_outlined,
          variant: AppButtonVariant.secondary,
          onPressed: () => showProblemSheet(
            context,
            dealId: deal.id,
            kinds: [problems.noShowKind],
            noShow: true,
          ),
        ),
      ],
    ];
    if (children.isEmpty) return const SizedBox.shrink();

    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: children,
      ),
    );
  }
}

class _MyNoShowCard extends StatelessWidget {
  const _MyNoShowCard({
    required this.problems,
    required this.report,
    required this.onChat,
  });

  final DealProblems problems;
  final ShipmentProblem report;
  final VoidCallback? onChat;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final status = _statusCopy(l, report.status);

    return AppCard(
      accent: status.tone,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  problems.isSender
                      ? l.noShowReportedTraveler
                      : l.noShowReportedSender,
                  style: text.titleSmall,
                ),
              ),
              const SizedBox(width: AppSpace.sm),
              StatusPill(
                label: status.label,
                tone: status.tone,
                icon: status.icon,
                compact: true,
              ),
            ],
          ),
          const SizedBox(height: AppSpace.sm),
          Text(l.noShowNextBody, style: text.bodyMedium),
          if (onChat != null) ...[
            const SizedBox(height: AppSpace.md),
            AppButton(
              label: l.noShowMessageInChat,
              icon: Icons.forum_outlined,
              variant: AppButtonVariant.tertiary,
              onPressed: onChat,
            ),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The list, and "Report a problem"
// ---------------------------------------------------------------------------

/// Every report on the delivery, and the button for a new one. Hidden when
/// there is neither.
class ProblemsSection extends ConsumerWidget {
  const ProblemsSection({required this.dealId, super.key});

  final int dealId;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final problems = ref.watch(dealProblemsProvider(dealId)).value;
    if (problems == null) return const SizedBox.shrink();

    final general = [
      for (final kind in problems.reportableKinds)
        if (!kind.isNoShow) kind,
    ];
    if (problems.reports.isEmpty && general.isEmpty) {
      return const SizedBox.shrink();
    }

    final l = L.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpace.xl),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (problems.reports.isNotEmpty) ...[
            SectionHeader(title: l.problemsTitle),
            for (final report in problems.reports) ...[
              _ReportCard(report: report),
              const SizedBox(height: AppSpace.sm),
            ],
          ],
          if (general.isNotEmpty) ...[
            const SizedBox(height: AppSpace.xs),
            AppButton(
              label: l.problemReportAction,
              icon: Icons.report_problem_outlined,
              variant: AppButtonVariant.tertiary,
              onPressed: () =>
                  showProblemSheet(context, dealId: dealId, kinds: general),
            ),
          ],
        ],
      ),
    );
  }
}

class _ReportCard extends StatelessWidget {
  const _ReportCard({required this.report});

  final ShipmentProblem report;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final locale = Localizations.localeOf(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final status = _statusCopy(l, report.status);

    return Semantics(
      container: true,
      child: AppCard(
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(_kindIcon(report.kind), size: 20, color: c.textSecondary),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Text(
                    problemKindLabel(l, report.kind),
                    style: text.titleSmall,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpace.sm),
            Wrap(
              spacing: AppSpace.sm,
              runSpacing: AppSpace.xs,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                StatusPill(
                  label: status.label,
                  tone: status.tone,
                  icon: status.icon,
                  compact: true,
                ),
                Text(
                  [
                    report.reportedByMe
                        ? l.problemReportedByYou
                        : l.problemReportedByOther,
                    if (report.createdAt != null)
                      LocaleFormats.dateTime(locale, report.createdAt!),
                  ].join(' · '),
                  style: text.bodySmall?.copyWith(color: c.textTertiary),
                ),
              ],
            ),
            if (report.note.trim().isNotEmpty) ...[
              const SizedBox(height: AppSpace.sm),
              Text(report.note.trim(), style: text.bodyMedium),
            ],
          ],
        ),
      ),
    );
  }
}

// ---------------------------------------------------------------------------
// The sheet
// ---------------------------------------------------------------------------

/// The no-show goes straight to the note, with its one kind; the general
/// report lists [kinds] and waits for a choice, even when only one is offered.
Future<void> showProblemSheet(
  BuildContext context, {
  required int dealId,
  required List<ProblemKind> kinds,
  bool noShow = false,
}) => showAppSheet<void>(
  context,
  builder: (_) => _ProblemSheet(dealId: dealId, kinds: kinds, noShow: noShow),
);

class _ProblemSheet extends ConsumerStatefulWidget {
  const _ProblemSheet({
    required this.dealId,
    required this.kinds,
    required this.noShow,
  });

  final int dealId;
  final List<ProblemKind> kinds;
  final bool noShow;

  @override
  ConsumerState<_ProblemSheet> createState() => _ProblemSheetState();
}

class _ProblemSheetState extends ConsumerState<_ProblemSheet> {
  static const _noteLimit = 1000;

  final _note = TextEditingController();
  ProblemKind? _kind;
  bool _busy = false;
  String? _error;

  ProblemKind? get _chosen => widget.noShow ? widget.kinds.first : _kind;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final kind = _chosen;
    if (kind == null || _busy) return;
    final l = L.of(context);
    final messenger = ScaffoldMessenger.maybeOf(context);
    final navigator = Navigator.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref
          .read(problemRepositoryProvider)
          .report(dealId: widget.dealId, kind: kind, note: _note.text);
      ref.invalidate(dealProblemsProvider(widget.dealId));
      ref
        ..invalidate(unreadNotificationsProvider)
        ..invalidate(unreadActiveNotificationsProvider);
      if (!mounted) return;
      navigator.pop();
      messenger?.showSnackBar(SnackBar(content: Text(l.problemSent)));
    } on ApiException catch (error) {
      // The window may have closed, or a pickup been confirmed: show what the
      // server says is true now, behind the sentence.
      if (error.isStale || error.code.raw.endsWith('_not_allowed')) {
        ref.invalidate(dealProblemsProvider(widget.dealId));
      }
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error =
            problemFailureMessage(l, error) ??
            describeFailure(context, error).body;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final text = Theme.of(context).textTheme;
    final c = context.colors;
    final kind = _chosen;
    final noShow = widget.noShow;

    return AppSheet(
      title: noShow
          ? problemKindLabel(l, widget.kinds.first)
          : l.problemSheetTitle,
      subtitle: noShow ? l.noShowSheetIntro : l.problemSheetIntro,
      footer: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_error != null) ...[
            Semantics(
              liveRegion: true,
              child: Text(
                _error!,
                style: text.bodyMedium?.copyWith(color: c.danger),
              ),
            ),
            const SizedBox(height: AppSpace.md),
          ],
          AppButton(
            label: noShow ? l.noShowSendAction : l.problemSendAction,
            isLoading: _busy,
            onPressed: kind == null ? null : _send,
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!noShow) ...[
            for (final option in widget.kinds)
              _KindRow(
                kind: option,
                selected: option == _kind,
                onTap: _busy ? null : () => setState(() => _kind = option),
              ),
            const SizedBox(height: AppSpace.md),
          ],
          AppTextField(
            label: l.problemNoteLabel,
            hint: l.problemNoteHint,
            controller: _note,
            minLines: 3,
            maxLines: 5,
            maxLength: _noteLimit,
            enabled: !_busy,
            textInputAction: TextInputAction.newline,
            keyboardType: TextInputType.multiline,
            textCapitalization: TextCapitalization.sentences,
          ),
          const SizedBox(height: AppSpace.md),
          // What happens next, said before the button is pressed.
          InfoNotice(
            message: noShow ? l.noShowNextBody : l.problemNextBody,
            icon: Icons.info_outline_rounded,
          ),
        ],
      ),
    );
  }
}

class _KindRow extends StatelessWidget {
  const _KindRow({
    required this.kind,
    required this.selected,
    required this.onTap,
  });

  final ProblemKind kind;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final label = problemKindLabel(l, kind);

    return Semantics(
      button: true,
      selected: selected,
      label: label,
      hint: selected ? l.a11ySelected : l.a11yNotSelected,
      onTap: onTap,
      child: ExcludeSemantics(
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppRadius.md),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minHeight: 52),
            child: Row(
              children: [
                Icon(
                  _kindIcon(kind),
                  color: selected ? c.brandInk : c.textTertiary,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ),
                if (selected) Icon(Icons.check_rounded, color: c.brandInk),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
