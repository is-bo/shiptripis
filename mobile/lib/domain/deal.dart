/// The Deal: a funded (or funding) agreement between one sender and one
/// traveller, and the object the whole delivery lifecycle hangs off.
///
/// `GET /api/deals/<id>` returns the aggregate — terms, allocations, recipient,
/// handover, protection, dispute, cancellation availability and ratings — in
/// one response. That is deliberate on the server's part and this client
/// honours it: the deal screen makes **one** call, not eight.
///
/// Every lifecycle instant here is server-issued and nullable. The client
/// never computes one. `protection_ends_at` in particular lives on the Deal
/// and *not* on the handover payload, so a protection countdown reads it from
/// here.
library;

import '../core/money/money.dart';
import 'cancellation.dart';
import 'communication_language.dart';
import 'dispute.dart';
import 'handover.dart';
import 'json.dart';
import 'payment.dart';
import 'rating.dart';

enum DealStatus {
  offerAccepted,
  paymentRequired,
  funded,
  pickupReady,
  pickedUp,
  inTransit,
  deliveryReady,
  deliveryConfirmed,
  protectionWindow,
  completed,
  cancelled,
  expired,
  paymentFailed,
  disputed,
  refunded,
  partiallyRefunded,
  unknown;

  /// Money has not been taken yet.
  bool get needsFunding =>
      this == paymentRequired || this == paymentFailed || this == offerAccepted;

  /// Funded and before the parcel changed hands.
  bool get isBeforePickup => this == funded || this == pickupReady;

  bool get isCarrying =>
      this == pickedUp || this == inTransit || this == deliveryReady;

  bool get isAfterDelivery =>
      this == deliveryConfirmed ||
      this == protectionWindow ||
      this == completed ||
      this == disputed;

  bool get isFinished =>
      this == completed ||
      this == cancelled ||
      this == expired ||
      this == refunded ||
      this == partiallyRefunded;

  /// Chat closes on these. `disputed` is deliberately not among them — parties
  /// in a dispute still need to talk.
  bool get closesChat =>
      this == completed ||
      this == cancelled ||
      this == expired ||
      this == refunded ||
      this == partiallyRefunded;
}

class DealTerms {
  const DealTerms({
    required this.currency,
    required this.isLegacy,
    this.travelerReward,
    this.commissionRateBps,
    this.platformFee,
    this.senderTotal,
    this.businessSettingsVersion,
    this.pricingVersion,
  });

  static DealTerms? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final currency = readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']);
    return DealTerms(
      currency: currency,
      travelerReward: Money.minorOrNull(
        json['traveler_reward_minor'],
        currency: currency,
      ),
      commissionRateBps: readInt(json['commission_rate_bps']),
      platformFee: Money.minorOrNull(
        json['platform_fee_minor'],
        currency: currency,
      ),
      senderTotal: Money.minorOrNull(
        json['sender_total_minor'],
        currency: currency,
      ),
      businessSettingsVersion: readInt(json['business_settings_version']),
      pricingVersion: readString(json['pricing_version']),
      isLegacy: readBool(json['is_legacy']),
    );
  }

  final String currency;

  /// What the traveller is paid.
  final Money? travelerReward;

  final int? commissionRateBps;

  /// Added on top of the reward.
  final Money? platformFee;

  /// What the sender pays. Frozen at acceptance.
  final Money? senderTotal;

  final int? businessSettingsVersion;
  final String? pricingVersion;
  final bool isLegacy;
}

enum LegAllocationStatus {
  pendingPayment,
  funded,
  inTransit,
  released,
  completed,
  cancelled,
  unknown,
}

class LegAllocation {
  const LegAllocation({
    required this.id,
    required this.journeyLegId,
    required this.position,
    required this.status,
    this.allocatedWeightKg,
    this.reservedAt,
    this.expiresAt,
    this.releasedAt,
    this.releaseReason,
  });

  factory LegAllocation.fromJson(Map<String, dynamic> json) => LegAllocation(
    id: readInt(json['id']) ?? 0,
    journeyLegId: readInt(json['journey_leg_id']) ?? 0,
    position: readInt(json['journey_leg_position']) ?? 0,
    status: readEnum(
      json['status'],
      LegAllocationStatus.values,
      fallback: LegAllocationStatus.unknown,
    ),
    allocatedWeightKg: readDouble(json['allocated_weight_kg']),
    reservedAt: readDate(json['reserved_at']),
    expiresAt: readDate(json['expires_at']),
    releasedAt: readDate(json['released_at']),
    releaseReason: readString(json['release_reason']),
  );

  final int id;
  final int journeyLegId;
  final int position;
  final LegAllocationStatus status;
  final double? allocatedWeightKg;
  final DateTime? reservedAt;

  /// When an unfunded reservation lapses. The sender's funding deadline.
  final DateTime? expiresAt;

  final DateTime? releasedAt;
  final String? releaseReason;
}

/// The protection window and the payout it gates.
class ProtectionState {
  const ProtectionState({
    this.protectionEndsAt,
    this.deliveryConfirmedAt,
    this.payout,
  });

  static ProtectionState? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final payout = readObject(json['payout']);
    return ProtectionState(
      protectionEndsAt: readDate(json['protection_ends_at']),
      deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
      payout: payout == null ? null : DealPayout.fromJson(payout),
    );
  }

  final DateTime? protectionEndsAt;
  final DateTime? deliveryConfirmedAt;

  /// Null until the finance side has created the row.
  final DealPayout? payout;

  bool get isActive {
    final ends = protectionEndsAt;
    return ends != null && ends.isAfter(DateTime.now());
  }
}

/// The payout block nested on a Deal. Thinner than the standalone [Payout].
class DealPayout {
  const DealPayout({
    required this.status,
    required this.method,
    this.amount,
    this.eligibleAt,
    this.paidAt,
  });

  factory DealPayout.fromJson(Map<String, dynamic> json) => DealPayout(
    status: readEnum(
      json['status'],
      PayoutStatus.values,
      fallback: PayoutStatus.unknown,
    ),
    method: readEnum(
      json['method'],
      PayoutMethod.values,
      fallback: PayoutMethod.unknown,
    ),
    amount: Money.eurCentsOrNull(json['amount_eur_cents']),
    eligibleAt: readDate(json['eligible_at']),
    paidAt: readDate(json['paid_at']),
  );

  final PayoutStatus status;
  final PayoutMethod method;
  final Money? amount;
  final DateTime? eligibleAt;
  final DateTime? paidAt;
}

/// The recipient, projected for whoever is asking.
///
/// The traveller never receives the recipient's email or phone at any stage —
/// so the platform stays between them — and receives the name only after
/// pickup is confirmed.
class RecipientView {
  const RecipientView({
    required this.recorded,
    this.fullName,
    this.email,
    this.phone,
    this.deliveryNote,
    this.communicationLanguage,
    this.revision,
    this.updatedAt,
  });

  static RecipientView? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return RecipientView(
      // The sender's full projection has no `recorded` key; its presence at
      // all means a recipient exists.
      recorded: readBool(json['recorded'], fallback: true),
      fullName: readString(json['full_name']),
      email: readString(json['email']),
      phone: readString(json['phone']),
      deliveryNote: readString(json['delivery_note']),
      // Absent on the traveller's projection, and absent entirely against a
      // deployment older than the preference. `maybe` keeps those two cases
      // distinguishable from a stored blank, which the server itself already
      // resolves to English.
      communicationLanguage: CommunicationLanguage.maybe(
        json['communication_language'],
      ),
      revision: readInt(json['revision']),
      updatedAt: readDate(json['updated_at']),
    );
  }

  final bool recorded;
  final String? fullName;

  /// Sender-only. Never rendered on a traveller screen and never logged.
  final String? email;

  /// Sender-only.
  final String? phone;

  final String? deliveryNote;

  /// Sender-only, and the language of the recipient's delivery-code email.
  ///
  /// Null means the server did not send the field to this viewer — it never
  /// means English. An edit form reads it to preserve what is stored rather
  /// than re-deriving it from the sender's own preference.
  final CommunicationLanguage? communicationLanguage;

  final int? revision;
  final DateTime? updatedAt;

  /// True when this viewer got the full record rather than the existence flag.
  bool get isFullRecord => email != null;

  @override
  String toString() => 'RecipientView(recorded: $recorded, details redacted)';
}

class NoShowRecord {
  const NoShowRecord({required this.party, this.recordedAt, this.note});

  static NoShowRecord? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return NoShowRecord(
      party: readText(json['party']),
      recordedAt: readDate(json['recorded_at']),
      note: readString(json['note']),
    );
  }

  final String party;
  final DateTime? recordedAt;
  final String? note;
}

class Deal {
  const Deal({
    required this.id,
    required this.senderId,
    required this.travelerId,
    required this.status,
    required this.isLegacy,
    required this.legAllocations,
    this.acceptedOfferId,
    this.matchId,
    this.deliveryRequestId,
    this.journeyId,
    this.cancellationReason,
    this.fundedAt,
    this.agreedPickupAt,
    this.pickupConfirmedAt,
    this.deliveryCodeAvailableAt,
    this.deliveryCodeReleasedAt,
    this.deliveryConfirmedAt,
    this.protectionEndsAt,
    this.ratingWindowEndsAt,
    this.completedAt,
    this.cancelledAt,
    this.terms,
    this.recipient,
    this.handover,
    this.protection,
    this.dispute,
    this.cancellation,
    this.ratings,
    this.noShow,
    this.createdAt,
    this.updatedAt,
  });

  factory Deal.fromJson(Map<String, dynamic> json) => Deal(
    id: readInt(json['id']) ?? 0,
    acceptedOfferId: readInt(json['accepted_offer_id']),
    matchId: readInt(json['match_id']),
    deliveryRequestId: readInt(json['delivery_request_id']),
    journeyId: readInt(json['journey_id']),
    senderId: readInt(json['sender_id']) ?? 0,
    travelerId: readInt(json['traveler_id']) ?? 0,
    status: readEnum(
      json['status'],
      DealStatus.values,
      fallback: DealStatus.unknown,
    ),
    isLegacy: readBool(json['is_legacy']),
    cancellationReason: readString(json['cancellation_reason']),
    fundedAt: readDate(json['funded_at']),
    agreedPickupAt: readDate(json['agreed_pickup_at']),
    pickupConfirmedAt: readDate(json['pickup_confirmed_at']),
    deliveryCodeAvailableAt: readDate(json['delivery_code_available_at']),
    deliveryCodeReleasedAt: readDate(json['delivery_code_released_at']),
    deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
    protectionEndsAt: readDate(json['protection_ends_at']),
    ratingWindowEndsAt: readDate(json['rating_window_ends_at']),
    completedAt: readDate(json['completed_at']),
    cancelledAt: readDate(json['cancelled_at']),
    terms: DealTerms.maybe(json['terms']),
    legAllocations:
        (readObjectList(
            json['leg_allocations'],
          ).map(LegAllocation.fromJson).toList()
          ..sort((a, b) => a.position.compareTo(b.position))),
    recipient: RecipientView.maybe(json['recipient']),
    handover: HandoverState.maybe(json['handover']),
    protection: ProtectionState.maybe(json['protection']),
    dispute: DisputeSummary.maybe(json['dispute']),
    cancellation: CancellationAvailability.maybe(json['cancellation']),
    ratings: RatingState.maybe(json['ratings']),
    noShow: NoShowRecord.maybe(json['no_show']),
    createdAt: readDate(json['created_at']),
    updatedAt: readDate(json['updated_at']),
  );

  final int id;
  final int? acceptedOfferId;
  final int? matchId;
  final int? deliveryRequestId;
  final int? journeyId;
  final int senderId;
  final int travelerId;
  final DealStatus status;
  final bool isLegacy;
  final String? cancellationReason;

  // ---- Server-issued lifecycle instants. Never computed here. ----

  /// The privacy boundary: exact locations and chat unlock from here.
  final DateTime? fundedAt;

  final DateTime? agreedPickupAt;
  final DateTime? pickupConfirmedAt;

  /// End of the 30-minute delivery-code safety buffer.
  final DateTime? deliveryCodeAvailableAt;

  final DateTime? deliveryCodeReleasedAt;
  final DateTime? deliveryConfirmedAt;

  /// End of the 48-hour protection window. Payout waits for it; a dispute
  /// freezes it.
  final DateTime? protectionEndsAt;

  final DateTime? ratingWindowEndsAt;
  final DateTime? completedAt;
  final DateTime? cancelledAt;

  final DealTerms? terms;
  final List<LegAllocation> legAllocations;

  // ---- Detail-only blocks. Absent on the list projection. ----

  final RecipientView? recipient;
  final HandoverState? handover;
  final ProtectionState? protection;
  final DisputeSummary? dispute;
  final CancellationAvailability? cancellation;
  final RatingState? ratings;
  final NoShowRecord? noShow;

  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isFunded => fundedAt != null;

  bool isSender(int viewerId) => viewerId == senderId;

  int counterpartyId(int viewerId) =>
      viewerId == senderId ? travelerId : senderId;

  /// A dispute is open and money is frozen behind it.
  bool get hasActiveDispute => dispute?.isActive ?? false;

  /// The deadline for funding, from the reservation held on the journey legs.
  /// Null once funded or when no reservation carries one.
  DateTime? get fundingDeadline {
    if (isFunded) return null;
    final deadlines = legAllocations
        .where((a) => a.status == LegAllocationStatus.pendingPayment)
        .map((a) => a.expiresAt)
        .whereType<DateTime>()
        .toList(growable: false);
    if (deadlines.isEmpty) return null;
    return deadlines.reduce((a, b) => a.isBefore(b) ? a : b);
  }

  /// Whether the traveller is still waiting on money that a protection window
  /// or a dispute is holding.
  bool get payoutIsHeld {
    final payout = protection?.payout;
    if (payout == null) return false;
    return payout.status.isPending || payout.status == PayoutStatus.frozen;
  }
}
