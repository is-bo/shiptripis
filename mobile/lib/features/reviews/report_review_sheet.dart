/// Reporting a review: five reasons and an optional note.
///
/// Whether the viewer may report it, and what the report comes to, is the
/// server's. The sheet files the report and says what the server answered; it
/// never claims a review was removed.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api/api_exception.dart';
import '../../core/api/error_codes.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart';
import '../../design/components/forms.dart';
import '../../design/components/primitives.dart';
import '../../design/components/sheets.dart';
import '../../design/tokens.dart';
import '../../domain/reviews.dart';
import '../../l10n/app_localizations.dart';

const _noteLimit = 500;

String reviewReasonLabel(L l, ReviewReason reason) => switch (reason) {
  ReviewReason.offensive => l.reviewReasonOffensive,
  ReviewReason.personalInformation => l.reviewReasonPersonalInformation,
  ReviewReason.unrelated => l.reviewReasonUnrelated,
  ReviewReason.untrue => l.reviewReasonUntrue,
  ReviewReason.other => l.reviewReasonOther,
};

/// Opens the sheet. Answers what the server says became of the report, or null
/// when it was dismissed. [onStale] runs when the server says the review is
/// gone or already removed, so the list behind the sheet can re-read.
///
/// [journeyId] and [requestId] are the Find Travelers context, together.
Future<MyReport?> showReportReviewSheet(
  BuildContext context, {
  required int ratingId,
  int? journeyId,
  int? requestId,
  VoidCallback? onStale,
}) => showAppSheet<MyReport>(
  context,
  builder: (_) => _ReportSheet(
    ratingId: ratingId,
    journeyId: journeyId,
    requestId: requestId,
    onStale: onStale,
  ),
);

class _ReportSheet extends ConsumerStatefulWidget {
  const _ReportSheet({
    required this.ratingId,
    this.journeyId,
    this.requestId,
    this.onStale,
  });

  final int ratingId;
  final int? journeyId;
  final int? requestId;
  final VoidCallback? onStale;

  @override
  ConsumerState<_ReportSheet> createState() => _ReportSheetState();
}

class _ReportSheetState extends ConsumerState<_ReportSheet> {
  final _note = TextEditingController();
  ReviewReason? _reason;
  bool _busy = false;
  String? _error;

  @override
  void dispose() {
    _note.dispose();
    super.dispose();
  }

  Future<void> _send() async {
    final reason = _reason;
    if (reason == null || _busy) return;
    final l = L.of(context);
    final messenger = ScaffoldMessenger.maybeOf(context);
    final navigator = Navigator.of(context);
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final receipt = await ref
          .read(ratingRepositoryProvider)
          .report(
            ratingId: widget.ratingId,
            reason: reason,
            note: _note.text,
            journeyId: widget.journeyId,
            requestId: widget.requestId,
          );
      if (!mounted) return;
      navigator.pop(receipt.state);
      messenger?.showSnackBar(SnackBar(content: Text(l.reviewReportThanks)));
    } on ApiException catch (error) {
      if (error.code == ApiErrorCode.reviewRemoved ||
          error.code == ApiErrorCode.reviewNotFound) {
        widget.onStale?.call();
      }
      if (!mounted) return;
      setState(() {
        _busy = false;
        _error = switch (error.code) {
          ApiErrorCode.ownReview => l.reviewReportOwn,
          ApiErrorCode.reviewRemoved => l.reviewReportRemoved,
          ApiErrorCode.reviewNotFound => l.reviewReportGone,
          _ => describeFailure(context, error).body,
        };
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;
    final text = Theme.of(context).textTheme;

    return AppSheet(
      title: l.reviewReportSheetTitle,
      subtitle: l.reviewReportSheetIntro,
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
            label: l.reviewReportSend,
            isLoading: _busy,
            onPressed: _reason == null ? null : _send,
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final option in ReviewReason.values)
            _ReasonRow(
              label: reviewReasonLabel(l, option),
              selected: option == _reason,
              onTap: _busy ? null : () => setState(() => _reason = option),
            ),
          const SizedBox(height: AppSpace.md),
          AppTextField(
            label: l.reviewReportNoteLabel,
            hint: l.reviewReportNoteHint,
            controller: _note,
            minLines: 2,
            maxLines: 4,
            maxLength: _noteLimit,
            enabled: !_busy,
            textInputAction: TextInputAction.newline,
            keyboardType: TextInputType.multiline,
            textCapitalization: TextCapitalization.sentences,
          ),
        ],
      ),
    );
  }
}

class _ReasonRow extends StatelessWidget {
  const _ReasonRow({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final l = L.of(context);
    final c = context.colors;

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
                  selected
                      ? Icons.radio_button_checked_rounded
                      : Icons.radio_button_unchecked_rounded,
                  color: selected ? c.brandInk : c.textTertiary,
                ),
                const SizedBox(width: AppSpace.md),
                Expanded(
                  child: Text(
                    label,
                    style: Theme.of(context).textTheme.bodyLarge,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
