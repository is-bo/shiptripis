/// Problem reports on a delivery.
///
/// A report is a statement, never a status. It does not move the deal, cancel
/// it or refund anything: staff decide, through the dispute, cancellation and
/// no-show actions that already exist. This file parses what the server says
/// and decides nothing: which kinds are offered now, and whether the no-show
/// window is open, are the server's answers (`reportable_kinds`,
/// `can_report_no_show`), never worked out from clocks on the phone.
///
/// Routes (L9A): `GET` and `POST /api/deals/<id>/problems`.
library;

import 'json.dart';

enum ProblemKind {
  senderUnavailable,
  travelerNoShow,
  recipientUnavailable,
  parcelMismatch,
  parcelDamaged,
  tripDisrupted,
  customsDelay,
  other;

  static ProblemKind? parse(Object? raw) => switch (readString(raw)) {
    'sender_unavailable' => senderUnavailable,
    'traveler_no_show' => travelerNoShow,
    'recipient_unavailable' => recipientUnavailable,
    'parcel_mismatch' => parcelMismatch,
    'parcel_damaged' => parcelDamaged,
    'trip_disrupted' => tripDisrupted,
    'customs_delay' => customsDelay,
    'other' => other,
    _ => null,
  };

  String get wire => switch (this) {
    senderUnavailable => 'sender_unavailable',
    travelerNoShow => 'traveler_no_show',
    recipientUnavailable => 'recipient_unavailable',
    parcelMismatch => 'parcel_mismatch',
    parcelDamaged => 'parcel_damaged',
    tripDisrupted => 'trip_disrupted',
    customsDelay => 'customs_delay',
    other => 'other',
  };

  /// "The other person did not come": answered by its own action, not by the
  /// general list.
  bool get isNoShow => this == senderUnavailable || this == travelerNoShow;
}

enum ProblemStatus {
  open,
  escalated,
  acknowledged,
  closed,
  unknown;

  static ProblemStatus parse(Object? raw) => switch (readString(raw)) {
    'open' => open,
    'escalated' => escalated,
    'acknowledged' => acknowledged,
    'closed' => closed,
    _ => unknown,
  };

  bool get isLive => this != closed;
}

class ShipmentProblem {
  const ShipmentProblem({
    required this.id,
    required this.kind,
    required this.status,
    required this.reportedByMe,
    required this.note,
    this.createdAt,
    this.closedAt,
  });

  /// Null for a kind this app does not know, so one new server kind costs the
  /// user that row and not the screen.
  static ShipmentProblem? maybe(Map<String, dynamic> json) {
    final id = readInt(json['id']);
    final kind = ProblemKind.parse(json['kind']);
    if (id == null || kind == null) return null;
    return ShipmentProblem(
      id: id,
      kind: kind,
      status: ProblemStatus.parse(json['status']),
      reportedByMe: readBool(json['reported_by_me']),
      note: readText(json['note']),
      createdAt: readDate(json['created_at']),
      closedAt: readDate(json['closed_at']),
    );
  }

  final int id;
  final ProblemKind kind;
  final ProblemStatus status;

  /// Whose report it is. Both people read every report on their delivery.
  final bool reportedByMe;

  /// Shown to both people.
  final String note;
  final DateTime? createdAt;
  final DateTime? closedAt;
}

/// Why the no-show action is not offered now. Display only.
enum NoShowReason {
  /// The sender or traveler already has a live report of this kind.
  alreadyReported,
  tooEarly,
  notOpen;

  static NoShowReason? parse(Object? raw) => switch (readString(raw)) {
    '' || null => null,
    'already_reported' => alreadyReported,
    'pickup_time_not_reached' => tooEarly,
    _ => notOpen,
  };
}

/// `GET /api/deals/<id>/problems`.
class DealProblems {
  const DealProblems({
    required this.dealId,
    required this.isSender,
    required this.noShowKind,
    required this.canReportNoShow,
    required this.noShowReason,
    required this.reportableKinds,
    required this.reports,
    this.noShowAvailableAt,
  });

  factory DealProblems.fromJson(Map<String, dynamic> json) => DealProblems(
    dealId: readInt(json['deal_id']) ?? 0,
    isSender: readText(json['viewer_role']) == 'sender',
    noShowKind:
        ProblemKind.parse(json['no_show_kind']) ?? ProblemKind.travelerNoShow,
    canReportNoShow: readBool(json['can_report_no_show']),
    noShowReason: NoShowReason.parse(json['no_show_reason']),
    noShowAvailableAt: readDate(json['no_show_available_at']),
    reportableKinds: readStringList(
      json['reportable_kinds'],
    ).map(ProblemKind.parse).nonNulls.toList(growable: false),
    reports: readObjectList(
      json['results'],
    ).map(ShipmentProblem.maybe).nonNulls.toList(growable: false),
  );

  final int dealId;
  final bool isSender;

  /// The no-show this viewer can make: the traveler's report that the sender
  /// did not come, or the sender's that the traveler did not.
  final ProblemKind noShowKind;
  final bool canReportNoShow;
  final NoShowReason? noShowReason;
  final DateTime? noShowAvailableAt;

  /// The general kinds the delivery takes now. Empty outside the reportable
  /// statuses.
  final List<ProblemKind> reportableKinds;
  final List<ShipmentProblem> reports;

  /// A live report of the no-show kind made by this viewer.
  ShipmentProblem? get myNoShowReport {
    for (final report in reports) {
      if (report.kind == noShowKind &&
          report.reportedByMe &&
          report.status.isLive) {
        return report;
      }
    }
    return null;
  }

  /// A live no-show report made by the other person. It is the other person's
  /// words about this viewer; the banner offers chat and the viewer's own
  /// report, nothing that decides anything.
  ShipmentProblem? get noShowAgainstMe {
    for (final report in reports) {
      if (report.kind.isNoShow &&
          !report.reportedByMe &&
          report.status.isLive) {
        return report;
      }
    }
    return null;
  }

  bool get canReportAnything => canReportNoShow || reportableKinds.isNotEmpty;
}
