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
import 'money_perspective.dart';
import 'payment.dart';
import 'payout.dart';
import 'rating.dart';
import 'transport_mode.dart';

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

/// Whether this Deal is still a live shipment. Server-owned.
enum ActivityState {
  active,
  completed,
  cancelled,
  unknown;

  static ActivityState parse(String? raw) => switch (raw) {
    'active' => active,
    'completed' => completed,
    'cancelled' => cancelled,
    _ => unknown,
  };

  String get wire => switch (this) {
    active => 'active',
    completed => 'completed',
    cancelled => 'cancelled',
    unknown => '',
  };
}

/// The journey-timing arrival state.
enum DealArrivalState {
  notReported,
  pendingConfirmation,
  confirmed,
  declined,
  unknown;

  static DealArrivalState parse(String? raw) => switch (raw) {
    'not_reported' => notReported,
    'pending_confirmation' => pendingConfirmation,
    'confirmed' => confirmed,
    'declined' => declined,
    _ => unknown,
  };

  String get wire => switch (this) {
    notReported => 'not_reported',
    pendingConfirmation => 'pending_confirmation',
    confirmed => 'confirmed',
    declined => 'declined',
    unknown => '',
  };
}

/// Where the funded arrival instant comes from.
enum DealArrivalBasis {
  matchDeliveryInterpolation,
  allocatedLegArrival,
  matchedEndLegArrival,
  unavailable,
  unknown;

  static DealArrivalBasis parse(String? raw) => switch (raw) {
    'match_delivery_interpolation' => matchDeliveryInterpolation,
    'allocated_leg_arrival' => allocatedLegArrival,
    'matched_end_leg_arrival' => matchedEndLegArrival,
    'unavailable' => unavailable,
    _ => unknown,
  };
}

/// Server-derived arrival timing and actions projection.
class DealArrivalInfo {
  const DealArrivalInfo({
    required this.state,
    required this.basis,
    required this.materialEarlyThresholdSeconds,
    required this.isMateriallyEarlyNow,
    required this.confirmedArrivalIsNotDelivery,
    required this.reportAvailable,
    required this.decisionAvailable,
    required this.availableActions,
    this.fundedScheduledArrivalAt,
    this.secondsUntilScheduledArrival,
    this.serverTime,
    this.reportedAt,
    this.reportedEarlyBySeconds,
    this.decidedAt,
    this.arrivalConfirmedAt,
    this.deliveryConfirmedAt,
    this.reportUnavailableReason,
    this.decisionUnavailableReason,
  });

  factory DealArrivalInfo.fromJson(Map<String, dynamic> json) {
    final actionsRaw = json['available_actions'] as List<dynamic>? ?? const [];
    final actions = actionsRaw.map((e) => e.toString()).toList(growable: false);

    return DealArrivalInfo(
      state: DealArrivalState.parse(readString(json['state'])),
      basis: DealArrivalBasis.parse(readString(json['basis'])),
      fundedScheduledArrivalAt: readDate(json['funded_scheduled_arrival_at']),
      materialEarlyThresholdSeconds:
          readInt(json['material_early_threshold_seconds']) ?? 21600,
      isMateriallyEarlyNow: readBool(json['is_materially_early_now']),
      secondsUntilScheduledArrival: readInt(
        json['seconds_until_scheduled_arrival'],
      ),
      serverTime: readDate(json['server_time']),
      reportedAt: readDate(json['reported_at']),
      reportedEarlyBySeconds: readInt(json['reported_early_by_seconds']),
      decidedAt: readDate(json['decided_at']),
      arrivalConfirmedAt: readDate(json['arrival_confirmed_at']),
      confirmedArrivalIsNotDelivery: readBool(
        json['confirmed_arrival_is_not_delivery'],
        fallback: true,
      ),
      deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
      reportAvailable: readBool(json['report_available']),
      reportUnavailableReason: readString(json['report_unavailable_reason']),
      decisionAvailable: readBool(json['decision_available']),
      decisionUnavailableReason: readString(
        json['decision_unavailable_reason'],
      ),
      availableActions: actions,
    );
  }

  static DealArrivalInfo? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DealArrivalInfo.fromJson(json);
  }

  final DealArrivalState state;
  final DealArrivalBasis basis;
  final DateTime? fundedScheduledArrivalAt;
  final int materialEarlyThresholdSeconds;
  final bool isMateriallyEarlyNow;
  final int? secondsUntilScheduledArrival;
  final DateTime? serverTime;
  final DateTime? reportedAt;
  final int? reportedEarlyBySeconds;
  final DateTime? decidedAt;
  final DateTime? arrivalConfirmedAt;
  final bool confirmedArrivalIsNotDelivery;
  final DateTime? deliveryConfirmedAt;
  final bool reportAvailable;
  final String? reportUnavailableReason;
  final bool decisionAvailable;
  final String? decisionUnavailableReason;
  final List<String> availableActions;

  bool get canReportEarlyArrival =>
      availableActions.contains('report_early_arrival');
  bool get canConfirmEarlyArrival =>
      availableActions.contains('confirm_early_arrival');
  bool get canDeclineEarlyArrival =>
      availableActions.contains('decline_early_arrival');

  bool get isPendingConfirmation =>
      state == DealArrivalState.pendingConfirmation;
  bool get isConfirmed => state == DealArrivalState.confirmed;
  bool get isDeclined => state == DealArrivalState.declined;
}

class DealTerms {
  const DealTerms({
    required this.currency,
    required this.isLegacy,
    this.travelerReward,
    this.commissionRateBps,
    this.platformFee,
    this.senderTotal,
    this.boostAmount,
    this.boostTravelerBonus,
    this.boostPlatformFee,
    this.travelerTotal,
    this.platformTotal,
    this.senderTotalWithBoost,
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
      boostAmount: Money.minorOrNull(
        json['boost_amount_minor'],
        currency: currency,
      ),
      boostTravelerBonus: Money.minorOrNull(
        json['boost_traveler_bonus_minor'],
        currency: currency,
      ),
      boostPlatformFee: Money.minorOrNull(
        json['boost_platform_fee_minor'],
        currency: currency,
      ),
      travelerTotal: Money.minorOrNull(
        json['traveler_total_minor'],
        currency: currency,
      ),
      platformTotal: Money.minorOrNull(
        json['platform_total_minor'],
        currency: currency,
      ),
      senderTotalWithBoost: Money.minorOrNull(
        json['sender_total_with_boost_minor'],
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
  final Money? boostAmount;
  final Money? boostTravelerBonus;
  final Money? boostPlatformFee;
  final Money? travelerTotal;
  final Money? platformTotal;
  final Money? senderTotalWithBoost;

  final int? businessSettingsVersion;
  final String? pricingVersion;
  final bool isLegacy;

  /// The final amount this party sees, using only server-published totals.
  /// Historical rows without Boost totals fall back to their original terms.
  Money? totalFor(MoneyPerspective perspective) => switch (perspective) {
    MoneyPerspective.sender => senderTotalWithBoost ?? senderTotal,
    MoneyPerspective.traveler => travelerTotal ?? travelerReward,
  };
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

/// The constraints on payout timing from `protection.payout_floor`.
class DealPayoutFloor {
  const DealPayoutFloor({
    required this.gateOpen,
    this.protectionEndsAt,
    this.fundedScheduledArrivalFloorAt,
    this.payoutEligibleFrom,
    this.basis,
    this.serverTime,
  });

  factory DealPayoutFloor.fromJson(Map<String, dynamic> json) =>
      DealPayoutFloor(
        protectionEndsAt: readDate(json['protection_ends_at']),
        fundedScheduledArrivalFloorAt: readDate(
          json['funded_scheduled_arrival_floor_at'],
        ),
        payoutEligibleFrom: readDate(json['payout_eligible_from']),
        basis: readString(json['basis']),
        gateOpen: readBool(json['gate_open']),
        serverTime: readDate(json['server_time']),
      );

  static DealPayoutFloor? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DealPayoutFloor.fromJson(json);
  }

  final DateTime? protectionEndsAt;
  final DateTime? fundedScheduledArrivalFloorAt;
  final DateTime? payoutEligibleFrom;
  final String? basis;
  final bool gateOpen;
  final DateTime? serverTime;

  bool get isScheduleFloorBinding => basis == 'schedule_floor';
  bool get isDeliveryProtectionBinding => basis == 'delivery_protection';
}

/// The protection window and the payout it gates.
class ProtectionState {
  const ProtectionState({
    this.protectionEndsAt,
    this.deliveryConfirmedAt,
    this.payout,
    this.payoutFloor,
  });

  static ProtectionState? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    final payout = readObject(json['payout']);
    final floor = readObject(json['payout_floor']);
    return ProtectionState(
      protectionEndsAt: readDate(json['protection_ends_at']),
      deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
      payout: payout == null ? null : DealPayout.fromJson(payout),
      payoutFloor: floor == null ? null : DealPayoutFloor.fromJson(floor),
    );
  }

  final DateTime? protectionEndsAt;
  final DateTime? deliveryConfirmedAt;

  /// Null until the finance side has created the row.
  final DealPayout? payout;

  /// Constraints on release timing, including the funded arrival floor.
  final DealPayoutFloor? payoutFloor;

  bool get isActive {
    final ends = protectionEndsAt;
    return ends != null && ends.isAfter(DateTime.now());
  }
}

enum DealRouteBasis {
  fundedSnapshot,
  liveJourney,
  unknown;

  static DealRouteBasis parse(String? raw) => switch (raw) {
    'funded_snapshot' => fundedSnapshot,
    'live_journey' => liveJourney,
    _ => unknown,
  };
}

class DealRouteEndpoint {
  const DealRouteEndpoint({
    required this.kind,
    required this.name,
    required this.displayLabel,
    this.id,
    this.placeType,
    this.iataCode,
    this.countryCode,
    this.parentName,
  });

  factory DealRouteEndpoint.fromJson(Map<String, dynamic> json) =>
      DealRouteEndpoint(
        kind: readText(json['kind']),
        id: readInt(json['id']),
        name: readText(json['name']),
        displayLabel: readText(json['display_label']),
        placeType: readString(json['place_type']),
        iataCode: readString(json['iata_code']),
        countryCode: readString(json['country_code']),
        parentName: readString(json['parent_name']),
      );

  static DealRouteEndpoint? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DealRouteEndpoint.fromJson(json);
  }

  final String kind;
  final int? id;
  final String name;
  final String displayLabel;
  final String? placeType;
  final String? iataCode;
  final String? countryCode;
  final String? parentName;

  bool get isAirport =>
      placeType == 'airport' || (iataCode != null && iataCode!.isNotEmpty);
}

class DealRouteLeg {
  const DealRouteLeg({
    required this.position,
    required this.mode,
    this.legId,
    this.origin,
    this.destination,
    this.departAt,
    this.arriveAt,
    this.carriesParcel = true,
  });

  factory DealRouteLeg.fromJson(Map<String, dynamic> json) => DealRouteLeg(
    legId: readInt(json['leg_id']),
    position: readInt(json['position']) ?? 0,
    mode: TransportMode.parse(json['mode']),
    origin: DealRouteEndpoint.maybe(json['origin']),
    destination: DealRouteEndpoint.maybe(json['destination']),
    departAt: readDate(json['depart_at']),
    arriveAt: readDate(json['arrive_at']),
    carriesParcel: readBool(json['carries_parcel'], fallback: true),
  );

  final int? legId;
  final int position;
  final TransportMode mode;
  final DealRouteEndpoint? origin;
  final DealRouteEndpoint? destination;
  final DateTime? departAt;
  final DateTime? arriveAt;
  final bool carriesParcel;
}

class DealRoute {
  const DealRoute({required this.basis, required this.legs, this.journeyId});

  factory DealRoute.fromJson(Map<String, dynamic> json) {
    final rawLegs = readObjectList(json['legs']);
    final legs = rawLegs.map(DealRouteLeg.fromJson).toList()
      ..sort((a, b) => a.position.compareTo(b.position));

    return DealRoute(
      basis: DealRouteBasis.parse(readString(json['basis'])),
      journeyId: readInt(json['journey_id']),
      legs: legs,
    );
  }

  static DealRoute? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DealRoute.fromJson(json);
  }

  final DealRouteBasis basis;
  final int? journeyId;
  final List<DealRouteLeg> legs;

  bool get isFundedSnapshot => basis == DealRouteBasis.fundedSnapshot;
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
    this.payoutSummary,
    this.activityState = ActivityState.unknown,
    this.fundedScheduledArrivalFloorAt,
    this.arrivalConfirmedAt,
    this.arrival,
    this.route,
    this.availableActions = const [],
    this.serverTime,
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
    activityState: readEnum(
      json['activity_state'],
      ActivityState.values,
      fallback: ActivityState.unknown,
    ),
    isLegacy: readBool(json['is_legacy']),
    cancellationReason: readString(json['cancellation_reason']),
    fundedAt: readDate(json['funded_at']),
    agreedPickupAt: readDate(json['agreed_pickup_at']),
    pickupConfirmedAt: readDate(json['pickup_confirmed_at']),
    deliveryCodeAvailableAt: readDate(json['delivery_code_available_at']),
    deliveryCodeReleasedAt: readDate(json['delivery_code_released_at']),
    deliveryConfirmedAt: readDate(json['delivery_confirmed_at']),
    fundedScheduledArrivalFloorAt: readDate(
      json['funded_scheduled_arrival_floor_at'],
    ),
    arrivalConfirmedAt: readDate(json['arrival_confirmed_at']),
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
    payoutSummary: PayoutMobile.maybe(json['payout_summary']),
    arrival: DealArrivalInfo.maybe(json['arrival']),
    route: DealRoute.maybe(json['route']),
    availableActions: (json['available_actions'] as List<dynamic>? ?? const [])
        .whereType<String>()
        .toList(growable: false),
    serverTime: readDate(json['server_time']),
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
  final ActivityState activityState;
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

  /// The frozen scheduled-arrival instant — the payout floor.
  final DateTime? fundedScheduledArrivalFloorAt;

  /// The instant an early arrival was confirmed by sender.
  final DateTime? arrivalConfirmedAt;

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
  final PayoutMobile? payoutSummary;
  final DealArrivalInfo? arrival;
  final DealRoute? route;
  final List<String> availableActions;
  final DateTime? serverTime;

  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isFunded => fundedAt != null;

  /// Whether this Deal is an active shipment according to the server.
  bool get isActiveShipment => activityState != ActivityState.unknown
      ? activityState == ActivityState.active
      : !status.isFinished;

  /// Whether this Deal is completed/finished according to the server.
  bool get isCompletedShipment => activityState != ActivityState.unknown
      ? (activityState == ActivityState.completed ||
            activityState == ActivityState.cancelled)
      : (status.isFinished || status.isAfterDelivery);

  bool isSender(int viewerId) => viewerId == senderId;

  MoneyPerspective? moneyPerspectiveFor(int viewerId) =>
      MoneyPerspective.resolve(
        viewerId: viewerId,
        senderId: senderId,
        travelerId: travelerId,
      );

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
