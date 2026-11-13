/// Route changes: a traveler's new times on a live journey.
///
/// The server decides everything that matters. Which parcels are affected,
/// which senders must agree (`material`), which are only told (`informed`),
/// whether the change waits or applies at once, and whether the sender can
/// still answer (`can_answer`) are all read from the payload. This file
/// parses; it measures no threshold, compares no deadline and picks no
/// button.
///
/// Routes (L9A): `GET/POST /api/journeys/<id>/schedule-changes`, `.../preview`,
/// `.../<change>/withdraw`, `GET /api/deals/<id>/schedule-change` and
/// `POST /api/deals/<id>/schedule-change/accept|decline`.
library;

import 'json.dart';
import 'transport_mode.dart';

enum ScheduleChangeStatus {
  pendingSenders,
  applied,
  withdrawn,
  unknown;

  static ScheduleChangeStatus parse(Object? raw) => switch (readString(raw)) {
    'pending_senders' => pendingSenders,
    'applied' => applied,
    'withdrawn' => withdrawn,
    _ => unknown,
  };
}

enum ConsentState {
  pending,
  accepted,
  declined,
  none;

  static ConsentState parse(Object? raw) => switch (readString(raw)) {
    'pending' => pending,
    'accepted' => accepted,
    'declined' => declined,
    _ => none,
  };
}

/// Why a parcel needs its sender's agreement.
enum ChangeReason {
  deadline,
  shift,
  pickup;

  static ChangeReason? parse(Object? raw) => switch (readString(raw)) {
    'deadline' => deadline,
    'shift' => shift,
    'pickup' => pickup,
    _ => null,
  };
}

/// One leg's times before and after.
class LegTimeChange {
  const LegTimeChange({
    required this.legId,
    required this.position,
    required this.mode,
    required this.originName,
    required this.destinationName,
    required this.changed,
    this.departBefore,
    this.arriveBefore,
    this.departAfter,
    this.arriveAfter,
  });

  factory LegTimeChange.fromJson(Map<String, dynamic> json) => LegTimeChange(
    legId: readInt(json['leg_id']) ?? 0,
    position: readInt(json['position']) ?? 0,
    mode: TransportMode.parse(json['mode']),
    originName: readText(json['origin_name']),
    destinationName: readText(json['destination_name']),
    departBefore: readDate(json['depart_at_before']),
    arriveBefore: readDate(json['arrive_at_before']),
    departAfter: readDate(json['depart_at_after']),
    arriveAfter: readDate(json['arrive_at_after']),
    changed: readBool(json['changed']),
  );

  final int legId;
  final int position;
  final TransportMode mode;
  final String originName;
  final String destinationName;
  final DateTime? departBefore;
  final DateTime? arriveBefore;
  final DateTime? departAfter;
  final DateTime? arriveAfter;
  final bool changed;
}

/// One parcel a change touches, as the traveler sees it.
class AffectedParcel {
  const AffectedParcel({
    required this.dealId,
    required this.material,
    required this.informed,
    required this.reasons,
    required this.consent,
    this.trackingNumber,
    this.arrivalBefore,
    this.arrivalAfter,
  });

  static AffectedParcel? maybe(Map<String, dynamic> json) {
    final dealId = readInt(json['deal_id']);
    if (dealId == null) return null;
    return AffectedParcel(
      dealId: dealId,
      trackingNumber: readTrackingNumber(json['tracking_number']),
      material: readBool(json['material']),
      informed: readBool(json['informed']),
      reasons: readStringList(
        json['reasons'],
      ).map(ChangeReason.parse).nonNulls.toList(growable: false),
      arrivalBefore: readDate(json['arrival_before']),
      arrivalAfter: readDate(json['arrival_after']),
      consent: ConsentState.parse(json['consent_state']),
    );
  }

  final int dealId;
  final String? trackingNumber;

  /// The sender must agree.
  final bool material;

  /// Already collected: the sender is told, not asked.
  final bool informed;
  final List<ChangeReason> reasons;
  final DateTime? arrivalBefore;
  final DateTime? arrivalAfter;
  final ConsentState consent;
}

/// A text the server wants shown with the review ("Your ticket will be
/// checked again...").
class ChangeNotice {
  const ChangeNotice({required this.code, required this.text});

  static ChangeNotice? maybe(Map<String, dynamic> json) {
    final text = readText(json['text']).trim();
    return text.isEmpty
        ? null
        : ChangeNotice(code: readText(json['code']), text: text);
  }

  final String code;
  final String text;
}

/// `POST .../schedule-changes/preview`: what the change would do.
class SchedulePreview {
  const SchedulePreview({
    required this.legs,
    required this.parcels,
    required this.appliesAtOnce,
    required this.notices,
  });

  factory SchedulePreview.fromJson(Map<String, dynamic> json) =>
      SchedulePreview(
        legs: readObjectList(
          json['legs'],
        ).map(LegTimeChange.fromJson).toList(growable: false),
        parcels: readObjectList(
          json['parcels'],
        ).map(AffectedParcel.maybe).nonNulls.toList(growable: false),
        appliesAtOnce: readBool(json['applies_at_once']),
        notices: readObjectList(
          json['notices'],
        ).map(ChangeNotice.maybe).nonNulls.toList(growable: false),
      );

  final List<LegTimeChange> legs;
  final List<AffectedParcel> parcels;
  final bool appliesAtOnce;
  final List<ChangeNotice> notices;

  List<AffectedParcel> get mustAgree =>
      parcels.where((p) => p.material).toList(growable: false);
  List<AffectedParcel> get onlyTold =>
      parcels.where((p) => !p.material).toList(growable: false);
}

/// A change as its traveler sees it.
class ScheduleChange {
  const ScheduleChange({
    required this.id,
    required this.status,
    required this.reason,
    required this.legs,
    required this.parcels,
    required this.waitingFor,
    this.createdAt,
    this.appliedAt,
    this.withdrawnAt,
    this.withdrawnBy = '',
  });

  static ScheduleChange? maybe(Map<String, dynamic> json) {
    final id = readInt(json['id']);
    if (id == null) return null;
    return ScheduleChange(
      id: id,
      status: ScheduleChangeStatus.parse(json['status']),
      reason: readText(json['reason']),
      createdAt: readDate(json['created_at']),
      appliedAt: readDate(json['applied_at']),
      withdrawnAt: readDate(json['withdrawn_at']),
      withdrawnBy: readText(json['withdrawn_by']),
      legs: readObjectList(
        json['legs'],
      ).map(LegTimeChange.fromJson).toList(growable: false),
      parcels: readObjectList(
        json['parcels'],
      ).map(AffectedParcel.maybe).nonNulls.toList(growable: false),
      waitingFor: readInt(json['waiting_for']) ?? 0,
    );
  }

  final int id;
  final ScheduleChangeStatus status;
  final String reason;
  final DateTime? createdAt;
  final DateTime? appliedAt;
  final DateTime? withdrawnAt;

  /// `traveler` or `no_longer_valid`.
  final String withdrawnBy;
  final List<LegTimeChange> legs;
  final List<AffectedParcel> parcels;

  /// Senders whose agreement is still missing.
  final int waitingFor;

  bool get isWaiting => status == ScheduleChangeStatus.pendingSenders;
}

/// The latest change touching one parcel, as its sender sees it.
class SenderScheduleChange {
  const SenderScheduleChange({
    required this.id,
    required this.dealId,
    required this.status,
    required this.reason,
    required this.material,
    required this.informed,
    required this.reasons,
    required this.consent,
    required this.canAnswer,
    required this.actions,
    required this.legs,
    this.arrivalBefore,
    this.arrivalAfter,
    this.pickupBefore,
    this.pickupAfter,
    this.deadlineAt,
    this.appliedAt,
  });

  static SenderScheduleChange? maybe(int dealId, Object? raw) {
    final json = readObject(raw);
    final id = readInt(json?['id']);
    if (json == null || id == null) return null;
    return SenderScheduleChange(
      id: id,
      dealId: dealId,
      status: ScheduleChangeStatus.parse(json['status']),
      reason: readText(json['reason']),
      material: readBool(json['material']),
      informed: readBool(json['informed']),
      reasons: readStringList(
        json['reasons'],
      ).map(ChangeReason.parse).nonNulls.toList(growable: false),
      consent: ConsentState.parse(json['consent_state']),
      canAnswer: readBool(json['can_answer']),
      actions: readStringList(json['actions']),
      arrivalBefore: readDate(json['arrival_before']),
      arrivalAfter: readDate(json['arrival_after']),
      pickupBefore: readDate(json['pickup_before']),
      pickupAfter: readDate(json['pickup_after']),
      deadlineAt: readDate(json['deadline_at']),
      appliedAt: readDate(json['applied_at']),
      legs: readObjectList(
        json['legs'],
      ).map(LegTimeChange.fromJson).toList(growable: false),
    );
  }

  final int id;
  final int dealId;
  final ScheduleChangeStatus status;
  final String reason;
  final bool material;

  /// Collected already: told, never asked.
  final bool informed;
  final List<ChangeReason> reasons;
  final ConsentState consent;

  /// The server's answer to "may this person accept or decline now".
  final bool canAnswer;

  /// For a collected parcel, the two actions that exist today:
  /// `report_problem` and `open_dispute`.
  final List<String> actions;
  final List<LegTimeChange> legs;
  final DateTime? arrivalBefore;
  final DateTime? arrivalAfter;
  final DateTime? pickupBefore;
  final DateTime? pickupAfter;
  final DateTime? deadlineAt;
  final DateTime? appliedAt;

  bool get isWaiting => status == ScheduleChangeStatus.pendingSenders;

  /// The sender has said no and the change still waits: cancelling is now
  /// the traveler's doing, and the cancellation quote says so.
  bool get declinedAndWaiting => isWaiting && consent == ConsentState.declined;

  /// Worth the sender's attention on the delivery now: they are asked, or the
  /// change is waiting with their answer on it, or they were told.
  bool get needsAttention => canAnswer || declinedAndWaiting;
}

/// One leg's new times, as the traveler sends them. Instants, never local
/// wall-clock strings: the server reads them as timezone-aware.
class LegTimesInput {
  const LegTimesInput({
    required this.legId,
    required this.departAt,
    required this.arriveAt,
  });

  final int legId;
  final DateTime departAt;
  final DateTime arriveAt;

  Map<String, Object?> toJson() => {
    'id': legId,
    'depart_at': departAt.toUtc().toIso8601String(),
    'arrive_at': arriveAt.toUtc().toIso8601String(),
  };
}
