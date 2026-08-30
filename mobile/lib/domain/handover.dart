/// Pickup and delivery handover.
///
/// ## The one invariant this file exists to make structurally true
///
/// **The traveller can never obtain the delivery code.** The server refuses
/// them with `403 not_authorized`, and its handover-state payload hard-codes
/// `traveler_can_view_delivery_code: false`. This client mirrors that shape
/// rather than reimplementing the rule:
///
/// * [RevealedCode] is the *only* type that carries plaintext. It is
///   constructed exclusively from the sender-only reveal endpoints, is never
///   held by a repository, never written to storage, never logged, and never
///   embedded in any other model — including [HandoverState], which is the
///   object both parties receive.
/// * [HandoverState.travelerCanViewDeliveryCode] is parsed and exposed
///   precisely so a test can assert it, and so no screen ever has to invent
///   the answer.
///
/// The 30-minute buffer is likewise the server's clock. The client renders a
/// countdown to `delivery_code_available_at` and, when it elapses, *asks the
/// server again*. It never treats its own timer reaching zero as permission.
library;

import 'json.dart';

enum HandoverCodeStatus {
  buffered,
  active,
  used,
  locked,
  superseded,
  cancelled,
  unknown,
}

enum HandoverKind { pickup, delivery, unknown }

/// What the state endpoint says about one of the two codes.
///
/// Carries no code material. `exists` goes false once a code leaves its live
/// statuses, which is itself deliberate: a traveller cannot learn from here
/// whether a code was used or locked.
class HandoverCodeSlot {
  const HandoverCodeSlot({
    required this.exists,
    required this.status,
    this.lockedUntil,
    this.rotation,
  });

  static HandoverCodeSlot fromJson(Object? raw) {
    final json = readObject(raw);
    if (json == null) {
      return const HandoverCodeSlot(
        exists: false,
        status: HandoverCodeStatus.unknown,
      );
    }
    return HandoverCodeSlot(
      exists: readBool(json['exists']),
      status: readEnum(
        json['status'],
        HandoverCodeStatus.values,
        fallback: HandoverCodeStatus.unknown,
      ),
      lockedUntil: readDate(json['locked_until']),
      rotation: readInt(json['rotation']),
    );
  }

  final bool exists;
  final HandoverCodeStatus status;

  /// Set while a code is in a timed lockout after too many wrong attempts.
  final DateTime? lockedUntil;

  final int? rotation;

  bool get isLockedNow {
    final until = lockedUntil;
    return until != null && until.isAfter(DateTime.now());
  }
}

/// `GET /api/deals/<id>/handover`.
///
/// The same JSON shape reaches both parties; only the `can*` booleans differ.
/// Neither projection contains code material.
class HandoverState {
  const HandoverState({
    required this.dealStatusRaw,
    required this.inDeliveryCodeBuffer,
    required this.pickup,
    required this.delivery,
    required this.canRevealPickupCode,
    required this.canRevealDeliveryCode,
    required this.travelerCanViewDeliveryCode,
    required this.canSubmitPickupCode,
    required this.canSubmitDeliveryCode,
    this.pickupConfirmedAt,
    this.deliveryCodeAvailableAt,
    this.deliveryCodeReleasedAt,
    this.deliveryConfirmedAt,
  });

  static HandoverState? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return HandoverState(
      dealStatusRaw: readText(json['deal_status']),
      pickupConfirmedAt: readDate(json['pickup_confirmed_at']),
      deliveryCodeAvailableAt: readDate(json['delivery_code_available_at']),
      deliveryCodeReleasedAt: readDate(json['delivery_code_released_at']),
      deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
      inDeliveryCodeBuffer: readBool(json['in_delivery_code_buffer']),
      pickup: HandoverCodeSlot.fromJson(json['pickup']),
      delivery: HandoverCodeSlot.fromJson(json['delivery']),
      canRevealPickupCode: readBool(json['can_reveal_pickup_code']),
      canRevealDeliveryCode: readBool(json['can_reveal_delivery_code']),
      travelerCanViewDeliveryCode: readBool(
        json['traveler_can_view_delivery_code'],
      ),
      canSubmitPickupCode: readBool(json['can_submit_pickup_code']),
      canSubmitDeliveryCode: readBool(json['can_submit_delivery_code']),
    );
  }

  final String dealStatusRaw;
  final DateTime? pickupConfirmedAt;

  /// When the 30-minute safety buffer ends. The countdown target, and the only
  /// clock the client is allowed to show.
  final DateTime? deliveryCodeAvailableAt;

  final DateTime? deliveryCodeReleasedAt;
  final DateTime? deliveryConfirmedAt;

  /// True while the buffer is still open. Server-computed.
  final bool inDeliveryCodeBuffer;

  final HandoverCodeSlot pickup;
  final HandoverCodeSlot delivery;

  final bool canRevealPickupCode;
  final bool canRevealDeliveryCode;

  /// Always false. Present so the invariant is assertable from the client
  /// side, not because it could ever be true.
  final bool travelerCanViewDeliveryCode;

  final bool canSubmitPickupCode;
  final bool canSubmitDeliveryCode;

  bool get isPickupConfirmed => pickupConfirmedAt != null;
  bool get isDeliveryConfirmed => deliveryConfirmedAt != null;
  bool get isDeliveryCodeReleased => deliveryCodeReleasedAt != null;
}

/// Plaintext. Sender-only, transient, never stored.
///
/// Held in screen state for as long as the sender is looking at it and dropped
/// when they leave. Nothing in this app persists, caches or logs an instance.
class RevealedCode {
  const RevealedCode({
    required this.code,
    required this.formatted,
    required this.kind,
    this.availableAt,
    this.rotation,
  });

  factory RevealedCode.fromJson(Map<String, dynamic> json) => RevealedCode(
    code: readText(json['code']),
    formatted: readText(json['formatted']),
    kind: readEnum(
      json['kind'],
      HandoverKind.values,
      fallback: HandoverKind.unknown,
    ),
    availableAt: readDate(json['available_at']),
    rotation: readInt(json['rotation']),
  );

  /// Ungrouped, for copying.
  final String code;

  /// Grouped `ABCD-EFGH`, for reading aloud. This is what a screen displays.
  final String formatted;

  final HandoverKind kind;
  final DateTime? availableAt;
  final int? rotation;

  /// Never let a code reach a log, a crash report or a `toString()` dump.
  @override
  String toString() => 'RevealedCode(${kind.name}, redacted)';
}

/// The result of submitting a code.
class HandoverSubmission {
  const HandoverSubmission({
    required this.dealId,
    required this.kind,
    required this.dealStatusRaw,
    required this.changed,
  });

  factory HandoverSubmission.fromJson(Map<String, dynamic> json) =>
      HandoverSubmission(
        dealId: readInt(json['deal_id']) ?? 0,
        kind: readEnum(
          json['kind'],
          HandoverKind.values,
          fallback: HandoverKind.unknown,
        ),
        // This is the **Deal's** new status, not the code's.
        dealStatusRaw: readText(json['status']),
        changed: readBool(json['changed']),
      );

  final int dealId;
  final HandoverKind kind;
  final String dealStatusRaw;
  final bool changed;
}

/// What a rejected code submission told us, read from the error envelope.
///
/// Extracted rather than parsed from prose: `attempts_remaining`,
/// `locked_until` and `requires_new_code` are structured fields the server
/// attaches to `handover_code_invalid` and `handover_code_locked`.
class CodeAttemptOutcome {
  const CodeAttemptOutcome({
    this.attemptsRemaining,
    this.lockedUntil,
    this.requiresNewCode = false,
    this.retryAfterSeconds,
  });

  final int? attemptsRemaining;
  final DateTime? lockedUntil;

  /// True once the code is permanently locked — only a sender rotation issues
  /// a usable one again.
  final bool requiresNewCode;

  /// Present on a rate-limit refusal.
  final int? retryAfterSeconds;
}
