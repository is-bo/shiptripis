/// Trip progress: what a traveler says about each leg of a journey.
///
/// A report is a statement, never a status. "Departed" does not move a deal,
/// release money or open a payout gate; it is shown to the sender as
/// "reported by the traveler" and nothing more. Which button is offered, and
/// when, is the server's call (`next_actions`): this file parses those
/// answers and decides nothing about ordering or time.
///
/// Routes (L5A): `GET /api/journeys/<id>/progress`,
/// `POST /api/journeys/<id>/legs/<leg>/progress`,
/// `POST /api/journeys/<id>/progress/<report>/retract` and
/// `GET /api/journeys/progress/pending`.
library;

import 'json.dart';

enum ProgressKind {
  atPort,
  departed,
  arrived;

  static ProgressKind? parse(Object? raw) => switch (readString(raw)) {
    'at_port' => atPort,
    'departed' => departed,
    'arrived' => arrived,
    _ => null,
  };

  String get wire => switch (this) {
    atPort => 'at_port',
    departed => 'departed',
    arrived => 'arrived',
  };
}

/// One report on a leg. A retracted one stays in the list so the history is
/// honest, but it is never shown as a live fact.
class ProgressReport {
  const ProgressReport({
    required this.id,
    required this.kind,
    required this.reportedAt,
    required this.canRetract,
    this.retractedAt,
    this.retractableUntil,
  });

  static ProgressReport? maybe(Map<String, dynamic> json) {
    final id = readInt(json['id']);
    final kind = ProgressKind.parse(json['kind']);
    final reportedAt = readDate(json['reported_at']);
    if (id == null || kind == null || reportedAt == null) return null;
    return ProgressReport(
      id: id,
      kind: kind,
      reportedAt: reportedAt,
      retractedAt: readDate(json['retracted_at']),
      retractableUntil: readDate(json['retractable_until']),
      canRetract: readBool(json['can_retract']),
    );
  }

  final int id;
  final ProgressKind kind;
  final DateTime reportedAt;
  final DateTime? retractedAt;

  /// The end of the undo window. Display only: the server refuses a late
  /// retraction whatever this says.
  final DateTime? retractableUntil;

  /// The server's answer, including "a later report depends on this one".
  final bool canRetract;

  bool get isLive => retractedAt == null;
}

/// A button the server offers for a leg.
class ProgressAction {
  const ProgressAction({
    required this.kind,
    required this.canReportNow,
    this.availableAt,
  });

  static ProgressAction? maybe(Map<String, dynamic> json) {
    final kind = ProgressKind.parse(json['kind']);
    if (kind == null) return null;
    return ProgressAction(
      kind: kind,
      availableAt: readDate(json['available_at']),
      canReportNow: readBool(json['can_report_now']),
    );
  }

  final ProgressKind kind;

  /// When the report opens (24 hours before the planned time).
  final DateTime? availableAt;
  final bool canReportNow;
}

class LegProgress {
  const LegProgress({
    required this.legId,
    required this.position,
    required this.originName,
    required this.destinationName,
    required this.reports,
    required this.nextActions,
  });

  factory LegProgress.fromJson(Map<String, dynamic> json) => LegProgress(
    legId: readInt(json['leg_id']) ?? 0,
    position: readInt(json['position']) ?? 0,
    originName: readText(json['origin_name']),
    destinationName: readText(json['destination_name']),
    reports: readObjectList(
      json['reports'],
    ).map(ProgressReport.maybe).nonNulls.toList(growable: false),
    nextActions: readObjectList(
      json['next_actions'],
    ).map(ProgressAction.maybe).nonNulls.toList(growable: false),
  );

  final int legId;
  final int position;
  final String originName;
  final String destinationName;
  final List<ProgressReport> reports;
  final List<ProgressAction> nextActions;

  Iterable<ProgressReport> get liveReports => reports.where((r) => r.isLive);

  ProgressReport? liveReport(ProgressKind kind) {
    for (final report in liveReports) {
      if (report.kind == kind) return report;
    }
    return null;
  }

  /// The single action to put in front of the traveler: the first one the
  /// server offers, in the order it lists them (port, departed, arrived).
  ProgressAction? get primaryAction =>
      nextActions.isEmpty ? null : nextActions.first;

  bool get isFinished => liveReport(ProgressKind.arrived) != null;
}

class JourneyProgress {
  const JourneyProgress({required this.journeyId, required this.legs});

  factory JourneyProgress.fromJson(Map<String, dynamic> json) =>
      JourneyProgress(
        journeyId: readInt(json['journey_id']) ?? 0,
        legs:
            readObjectList(
                json['legs'],
              ).map(LegProgress.fromJson).toList(growable: false)
              ..sort((a, b) => a.position.compareTo(b.position)),
      );

  final int journeyId;
  final List<LegProgress> legs;
}

/// A question that is due now: "did you depart from {place}?".
class PendingProgressQuestion {
  const PendingProgressQuestion({
    required this.journeyId,
    required this.legId,
    required this.kind,
    required this.placeName,
    this.plannedAt,
  });

  static PendingProgressQuestion? maybe(Map<String, dynamic> json) {
    final journeyId = readInt(json['journey_id']);
    final legId = readInt(json['leg_id']);
    final kind = ProgressKind.parse(json['kind']);
    if (journeyId == null || legId == null || kind == null) return null;
    return PendingProgressQuestion(
      journeyId: journeyId,
      legId: legId,
      kind: kind,
      placeName: readText(json['place_name']),
      plannedAt: readDate(json['planned_at']),
    );
  }

  final int journeyId;
  final int legId;
  final ProgressKind kind;
  final String placeName;
  final DateTime? plannedAt;
}

/// A traveler report as it appears on a deal's timeline (sender's view).
class DealProgressUpdate {
  const DealProgressUpdate({
    required this.progressId,
    required this.kind,
    this.reportedAt,
  });

  final int progressId;
  final ProgressKind kind;
  final DateTime? reportedAt;

  /// The reports still standing on a deal's timeline, oldest first.
  ///
  /// The timeline is append-only: a retraction is a later event naming the
  /// same `progress_id`, so a retracted report is dropped here rather than
  /// shown as a fact the traveler took back.
  static List<DealProgressUpdate> fromTimeline(Object? raw) {
    final retracted = <int>{};
    final reports = <DealProgressUpdate>[];
    for (final event in readObjectList(raw)) {
      final payload = readObject(event['payload']) ?? const {};
      final id = readInt(payload['progress_id']);
      if (id == null) continue;
      switch (readString(event['kind'])) {
        case 'traveler_progress_retracted':
          retracted.add(id);
        case 'traveler_progress':
          final kind = ProgressKind.parse(payload['progress_kind']);
          if (kind == null) continue;
          reports.add(
            DealProgressUpdate(
              progressId: id,
              kind: kind,
              reportedAt:
                  readDate(payload['reported_at']) ??
                  readDate(event['created_at']),
            ),
          );
      }
    }
    return reports
        .where((r) => !retracted.contains(r.progressId))
        .toList(growable: false);
  }
}
