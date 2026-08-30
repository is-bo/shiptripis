/// Cancelling a delivery.
///
/// The client shows the consequence **before** the confirmation, and every
/// figure in that consequence comes from the server's quote. No percentage, no
/// cap and no cutoff is hard-coded here — they are policy frozen onto the Deal
/// at funding time and can differ between two deals created a day apart.
///
/// After pickup there is no cancellation at all; the path is a dispute. The
/// server says so through `refusal_code`, and the client renders that rather
/// than deciding it.
library;

import '../core/money/money.dart';
import 'json.dart';

enum CancellationMode {
  /// Nothing has been collected; cancelling just releases the reservation.
  preFunding,

  /// Money is held; a refund and possibly a compensation apply.
  afterFunding,

  unknown,
}

/// Whether a cancel button should exist at all, from the Deal payload.
class CancellationAvailability {
  const CancellationAvailability({
    required this.allowed,
    required this.mode,
    required this.refusalCode,
  });

  static CancellationAvailability? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return CancellationAvailability(
      allowed: readBool(json['allowed']),
      mode: readEnum(
        json['mode'],
        CancellationMode.values,
        fallback: CancellationMode.unknown,
      ),
      refusalCode: readText(json['refusal_code']),
    );
  }

  final bool allowed;
  final CancellationMode mode;

  /// `""`, `not_authorized`, `cancellation_not_available_after_pickup`,
  /// `use_pre_funding_cancellation` or `deal_not_cancellable`.
  final String refusalCode;

  /// The one refusal that has a different next step rather than no next step:
  /// the parcel is already travelling, so a dispute is the route.
  bool get isAfterPickup =>
      refusalCode == 'cancellation_not_available_after_pickup';
}

/// `GET /api/deals/<id>/cancellation` — the priced consequence.
///
/// Returned with `200` even when cancellation is refused, because the refusal
/// itself is what the user needs to read.
class CancellationQuote {
  const CancellationQuote({
    required this.dealId,
    required this.actorRole,
    required this.allowed,
    required this.refusalCode,
    required this.isLate,
    this.collected,
    this.senderRefund,
    this.travelerCompensation,
    this.platformFee,
    this.cutoffAt,
    this.agreedPickupAt,
  });

  factory CancellationQuote.fromJson(Map<String, dynamic> json) =>
      CancellationQuote(
        dealId: readInt(json['deal_id']) ?? 0,
        actorRole: readText(json['actor_role']),
        allowed: readBool(json['allowed']),
        refusalCode: readText(json['refusal_code']),
        collected: Money.eurCentsOrNull(json['collected_eur_cents']),
        senderRefund: Money.eurCentsOrNull(json['sender_refund_eur_cents']),
        travelerCompensation: Money.eurCentsOrNull(
          json['traveler_compensation_eur_cents'],
        ),
        platformFee: Money.eurCentsOrNull(json['platform_fee_eur_cents']),
        isLate: readBool(json['is_late']),
        cutoffAt: readDate(json['cutoff_at']),
        agreedPickupAt: readDate(json['agreed_pickup_at']),
      );

  final int dealId;

  /// `sender`, `traveler`, or empty.
  final String actorRole;

  final bool allowed;
  final String refusalCode;

  /// Total taken from the sender so far.
  final Money? collected;

  /// What goes back to the sender.
  final Money? senderRefund;

  /// What the traveller keeps for a late sender cancellation. Zero when the
  /// traveller cancels — they are never compensated for their own withdrawal.
  final Money? travelerCompensation;

  /// The platform's cut of the cancellation. Policy-configured and currently
  /// zero at launch, but **read the field** rather than assuming.
  final Money? platformFee;

  /// True only for a sender cancelling after the free cutoff.
  final bool isLate;

  /// The instant after which a sender cancellation becomes late.
  final DateTime? cutoffAt;

  final DateTime? agreedPickupAt;

  bool get isSender => actorRole == 'sender';

  /// Nothing was ever collected, so there is nothing to explain financially.
  bool get isMoneyless => collected == null || collected!.isZero;

  bool get compensatesTraveler =>
      travelerCompensation != null && travelerCompensation!.isPositive;
}

/// The settlement actually applied, returned by the cancel call.
class CancellationOutcome {
  const CancellationOutcome({
    required this.mode,
    required this.changed,
    this.settlement,
    this.releasedAllocations,
  });

  factory CancellationOutcome.fromJson(Map<String, dynamic> json) =>
      CancellationOutcome(
        mode: readEnum(
          json['mode'],
          CancellationMode.values,
          fallback: CancellationMode.unknown,
        ),
        changed: readBool(json['changed']),
        settlement: readObject(json['settlement']) == null
            ? null
            : CancellationQuote.fromJson(readObject(json['settlement'])!),
        releasedAllocations: readInt(json['released_allocations']),
      );

  final CancellationMode mode;
  final bool changed;

  /// Present only for an after-funding cancellation. Carries the numbers that
  /// were actually applied, which the client shows instead of re-showing the
  /// quote it displayed a moment earlier.
  final CancellationQuote? settlement;

  final int? releasedAllocations;
}
