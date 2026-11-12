/// The words and the one write behind every trip-progress control.
///
/// Three places ask the traveler the same question: the stepper on the
/// journey, the "needs attention" row on Home and the sheet a reminder opens.
/// They share this file so a report is made the same way, and refused with the
/// same words, wherever it starts.
///
/// A report needs the network. There is no queue: if the request cannot reach
/// the server nothing is saved, and the message says so.
library;

import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../data/repositories.dart';
import '../../design/components/feedback.dart' show describeFailure;
import '../../domain/progress.dart';
import '../../l10n/app_localizations.dart';

/// "I've departed": the button that makes the statement.
String progressActionLabel(L l, ProgressKind kind) => switch (kind) {
  ProgressKind.atPort => l.progressActionAtPort,
  ProgressKind.departed => l.progressActionDeparted,
  ProgressKind.arrived => l.progressActionArrived,
};

/// "Departed": the statement once it has been made.
String progressReportedLabel(L l, ProgressKind kind) => switch (kind) {
  ProgressKind.atPort => l.progressReportedAtPort,
  ProgressKind.departed => l.progressReportedDeparted,
  ProgressKind.arrived => l.progressReportedArrived,
};

/// "Did you depart from Marseille?". Falls back to the bare question when the
/// server sent no place name rather than printing an empty hole.
String progressQuestionLabel(L l, ProgressKind kind, String place) {
  final named = place.trim();
  return switch (kind) {
    ProgressKind.atPort =>
      named.isEmpty
          ? l.progressQuestionAtPortBare
          : l.progressQuestionAtPort(named),
    ProgressKind.departed =>
      named.isEmpty
          ? l.progressQuestionDepartedBare
          : l.progressQuestionDeparted(named),
    ProgressKind.arrived =>
      named.isEmpty
          ? l.progressQuestionArrivedBare
          : l.progressQuestionArrived(named),
  };
}

/// "Yes, departed".
String progressYesLabel(L l, ProgressKind kind) => switch (kind) {
  ProgressKind.atPort => l.progressYesAtPort,
  ProgressKind.departed => l.progressYesDeparted,
  ProgressKind.arrived => l.progressYesArrived,
};

/// A refusal in the traveler's terms, or null to fall back to the generic
/// failure copy (a server fault, an expired session).
String? progressFailureMessage(L l, ApiException error) {
  if (error.kind == ApiFailureKind.offline ||
      error.kind == ApiFailureKind.timeout) {
    return l.progressErrorOffline;
  }
  return switch (error.code.raw) {
    'progress_too_early' => l.progressErrorTooEarly,
    'progress_out_of_order' ||
    'progress_kind_not_allowed' => l.progressErrorOutOfOrder,
    'journey_not_reportable' => l.progressErrorNotReportable,
    'progress_retract_window_closed' => l.progressErrorUndoClosed,
    'progress_has_followup' => l.progressErrorHasFollowup,
    'journey_not_owned' => l.journeyErrorNotOwned,
    _ => null,
  };
}

/// Makes the report and reconciles what depends on it.
///
/// Returns null on success, otherwise the sentence to show. Never throws for
/// an API failure. The screen decides where the sentence goes (a snackbar on
/// the page, inline inside a sheet).
Future<String?> sendProgress(
  WidgetRef ref,
  BuildContext context, {
  required int journeyId,
  required int legId,
  required ProgressKind kind,
}) => _run(
  ref,
  context,
  journeyId,
  () => ref
      .read(journeyRepositoryProvider)
      .reportProgress(journeyId: journeyId, legId: legId, kind: kind),
);

Future<String?> undoProgress(
  WidgetRef ref,
  BuildContext context, {
  required int journeyId,
  required int progressId,
}) => _run(
  ref,
  context,
  journeyId,
  () => ref
      .read(journeyRepositoryProvider)
      .retractProgress(journeyId: journeyId, progressId: progressId),
);

Future<String?> _run(
  WidgetRef ref,
  BuildContext context,
  int journeyId,
  Future<void> Function() write,
) async {
  final l = L.of(context);
  try {
    await write();
  } on ApiException catch (error) {
    // A refusal that says the picture is out of date is answered by showing
    // the current picture, not just a sentence.
    if (error.isStale || error.code.raw.startsWith('progress_')) {
      ref.invalidate(journeyProgressProvider(journeyId));
      ref.invalidate(pendingProgressProvider);
    }
    final specific = progressFailureMessage(l, error);
    if (specific != null) return specific;
    // The screen that asked may be gone by now; there is nobody to tell.
    return context.mounted ? describeFailure(context, error).body : '';
  }
  ref
    ..invalidate(journeyProgressProvider(journeyId))
    ..invalidate(pendingProgressProvider)
    ..invalidate(unreadNotificationsProvider)
    ..invalidate(unreadActiveNotificationsProvider);
  return null;
}
