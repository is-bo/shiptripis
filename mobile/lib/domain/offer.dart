/// Negotiation: the Match and the chain of Offers on it.
///
/// **The client never derives whose turn it is.** The server publishes
/// `awaiting_party`, `awaiting_user_id` and a per-viewer `allowed_actions`
/// list on every Offer. Reimplementing that state machine locally is how a
/// client ends up offering "Accept" on an offer the user themselves proposed,
/// or after a race has already closed it. [Offer.allowedActions] is the only
/// thing a screen may gate a button on.
///
/// Legacy DZD offers still exist in history. Their money fields are stripped
/// from the wire for V1 offers, and no live endpoint can accept or counter
/// one, so the client renders them read-only and never as an actionable
/// negotiation.
///
/// **An offer's reward is its base reward.** A sender's Boost is added on top,
/// and the server publishes the totals that include it (J6.1) -- the same
/// names a Deal's frozen terms use. The client reads those totals; it never
/// adds a Boost to a reward itself.
library;

import '../core/money/money.dart';
import 'discovery.dart';
import 'json.dart';
import 'location.dart';
import 'money_perspective.dart';

enum OfferStatus {
  pending,
  countered,
  accepted,
  declined,
  withdrawn,
  expired,
  unknown;

  bool get isOpen => this == pending;
  bool get isFinished =>
      this == declined || this == withdrawn || this == expired;
}

enum ProposedBy { traveler, sender, unknown }

/// Which side the ball is with.
enum OfferParty { sender, traveler, unknown }

/// The actions the server says this viewer may take right now.
enum OfferAction { accept, counter, decline, withdraw, unknown }

/// Where an offer's Boost-inclusive totals come from.
///
/// [provisional]: a pending offer. The figures are what accepting it right now
/// would commit; the sender's Boost is not frozen until acceptance, which
/// refuses if they no longer match what the acceptor confirmed.
/// [frozen]: an accepted offer, read from its Deal's immutable terms.
/// [unavailable]: a closed or legacy offer. No Boost was ever recorded on it,
/// so there is no total -- only the base reward.
enum BoostTermsStatus {
  provisional,
  frozen,
  unavailable,
  unknown;

  static BoostTermsStatus parse(Object? raw) => readEnum(
    raw,
    BoostTermsStatus.values,
    fallback: BoostTermsStatus.unknown,
  );
}

/// Which economics contract an offer was written under.
enum EconomicsVersion {
  v1Eur,
  legacyDzd,
  unknown;

  static EconomicsVersion parse(Object? raw) => readEnum(
    raw,
    EconomicsVersion.values,
    fallback: EconomicsVersion.unknown,
    aliases: const {
      'v1_eur': EconomicsVersion.v1Eur,
      'legacy_dzd': EconomicsVersion.legacyDzd,
    },
  );
}

class Offer {
  const Offer({
    required this.id,
    required this.matchId,
    required this.proposedBy,
    required this.proposerId,
    required this.economicsVersion,
    required this.currency,
    required this.status,
    required this.note,
    required this.allowedActions,
    required this.awaitingParty,
    this.parentOfferId,
    this.travelerReward,
    this.commissionRateBps,
    this.platformFee,
    this.senderTotal,
    this.boostTermsStatus = BoostTermsStatus.unknown,
    this.boostAmount,
    this.boostTravelerBonus,
    this.boostPlatformFee,
    this.travelerTotal,
    this.senderTotalWithBoost,
    this.pricingVersion,
    this.businessSettingsVersionId,
    this.termsPricing,
    this.termsCompatibility,
    this.paymentGraceSeconds,
    this.awaitingUserId,
    this.expiresAt,
    this.respondedAt,
    this.createdAt,
    this.updatedAt,
  });

  factory Offer.fromJson(Map<String, dynamic> json) {
    final terms = readObject(json['terms_snapshot']);
    final reservation =
        readObject(terms?['reservation']) ??
        readObject(readObject(terms?['policy'])?['reservation']);

    return Offer(
      id: readInt(json['id']) ?? 0,
      matchId: readInt(json['match']) ?? 0,
      parentOfferId: readInt(json['parent_offer']),
      proposedBy: readEnum(
        json['proposed_by'],
        ProposedBy.values,
        fallback: ProposedBy.unknown,
      ),
      proposerId: readInt(json['proposer_id']) ?? 0,
      economicsVersion: EconomicsVersion.parse(json['economics_version']),
      currency: readText(json['currency']).isEmpty
          ? 'EUR'
          : readText(json['currency']),
      travelerReward: Money.eurCentsOrNull(json['traveler_reward_minor']),
      commissionRateBps: readInt(json['commission_rate_bps']),
      platformFee: Money.eurCentsOrNull(json['platform_fee_minor']),
      senderTotal: Money.eurCentsOrNull(json['sender_total_minor']),
      boostTermsStatus: BoostTermsStatus.parse(json['boost_terms_status']),
      boostAmount: Money.eurCentsOrNull(json['boost_amount_minor']),
      boostTravelerBonus: Money.eurCentsOrNull(
        json['boost_traveler_bonus_minor'],
      ),
      boostPlatformFee: Money.eurCentsOrNull(json['boost_platform_fee_minor']),
      travelerTotal: Money.eurCentsOrNull(json['traveler_total_minor']),
      senderTotalWithBoost: Money.eurCentsOrNull(
        json['sender_total_with_boost_minor'],
      ),
      pricingVersion: readString(json['pricing_version']),
      businessSettingsVersionId: readInt(json['business_settings_version_id']),
      termsPricing: PricingQuote.maybe(terms?['pricing']),
      termsCompatibility: Compatibility.maybe(terms?['compatibility']),
      paymentGraceSeconds: readInt(reservation?['payment_grace_seconds']),
      status: readEnum(
        json['status'],
        OfferStatus.values,
        fallback: OfferStatus.unknown,
      ),
      note: readText(json['note']),
      expiresAt: readDate(json['expires_at']),
      respondedAt: readDate(json['responded_at']),
      awaitingParty: readEnum(
        json['awaiting_party'],
        OfferParty.values,
        fallback: OfferParty.unknown,
      ),
      awaitingUserId: readInt(json['awaiting_user_id']),
      allowedActions: readStringList(json['allowed_actions'])
          .map(
            (raw) => readEnum(
              raw,
              OfferAction.values,
              fallback: OfferAction.unknown,
            ),
          )
          .where((a) => a != OfferAction.unknown)
          .toSet(),
      createdAt: readDate(json['created_at']),
      updatedAt: readDate(json['updated_at']),
    );
  }

  final int id;
  final int matchId;
  final int? parentOfferId;
  final ProposedBy proposedBy;
  final int proposerId;
  final EconomicsVersion economicsVersion;
  final String currency;

  /// The **base** reward negotiated on this offer, before any Boost. Absent on
  /// a legacy DZD offer, whose money fields the server does not serialise into
  /// the V1 shape.
  final Money? travelerReward;

  final int? commissionRateBps;

  /// Added on top of the base reward. Never a deduction from it.
  final Money? platformFee;

  /// Base reward plus base fee, before any Boost. Server-computed.
  final Money? senderTotal;

  final BoostTermsStatus boostTermsStatus;

  /// The sender's Boost, and the part of it the Traveler receives. Null when
  /// [boostTermsStatus] is not provisional or frozen.
  final Money? boostAmount;
  final Money? boostTravelerBonus;

  /// ShipTrip's commission on the Boost, charged to the sender.
  final Money? boostPlatformFee;

  /// What the Traveler is paid, Boost included. Server-computed.
  final Money? travelerTotal;

  /// What the sender owes, Boost and its commission included. Server-computed.
  final Money? senderTotalWithBoost;

  final String? pricingVersion;
  final int? businessSettingsVersionId;

  /// The frozen pricing snapshot. Note that a recommendation is **never**
  /// included here, even for the sender who proposed — capture it from the
  /// quote or discovery response before proposing if it needs to be shown
  /// afterwards.
  final PricingQuote? termsPricing;

  final Compatibility? termsCompatibility;

  /// How long the sender has to fund a Deal once this offer is accepted.
  final int? paymentGraceSeconds;

  final OfferStatus status;
  final String note;
  final DateTime? expiresAt;
  final DateTime? respondedAt;

  final OfferParty awaitingParty;
  final int? awaitingUserId;

  /// Per-viewer. The only permission source a button may consult.
  final Set<OfferAction> allowedActions;

  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isV1 => economicsVersion == EconomicsVersion.v1Eur;

  /// True when this offer's totals include a Boost the Traveler receives.
  bool get hasBoost => boostTravelerBonus?.isPositive ?? false;

  /// True when the server published Boost-inclusive totals for this offer.
  bool get hasTotals => travelerTotal != null && senderTotalWithBoost != null;

  bool get canAccept => allowedActions.contains(OfferAction.accept);
  bool get canCounter => allowedActions.contains(OfferAction.counter);
  bool get canDecline => allowedActions.contains(OfferAction.decline);
  bool get canWithdraw => allowedActions.contains(OfferAction.withdraw);
  bool get hasAnyAction => allowedActions.isNotEmpty;

  bool isAwaiting(int userId) =>
      status.isOpen && awaitingUserId != null && awaitingUserId == userId;

  bool wasProposedBy(int userId) => proposerId == userId;

  /// The primary amount for one party, selected from two server totals.
  ///
  /// Both include the Boost. There is deliberately no fallback to the base
  /// reward: on an offer with a Boost that fallback is the very number that
  /// understated what a Traveler was accepting. Null means "no total", and a
  /// screen then labels whatever base figure it shows as the base.
  Money? amountFor(MoneyPerspective perspective) => switch (perspective) {
    MoneyPerspective.sender => senderTotalWithBoost,
    MoneyPerspective.traveler => travelerTotal,
  };
}

enum MatchStatus {
  pending,
  accepted,
  inTransit,
  delivered,
  completed,
  cancelled,
  expired,
  unknown;

  bool get isNegotiating => this == pending;
  bool get isFinished =>
      this == completed || this == cancelled || this == expired;
}

/// The parcel summary embedded in a Match. Deliberately thin — the full
/// request is a separate fetch.
class MatchParcel {
  const MatchParcel({
    required this.id,
    required this.kind,
    this.actualWeightKg,
    this.targetTravelerId,
    this.origin,
    this.destination,
  });

  static MatchParcel? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return MatchParcel(
      id: readInt(json['id']) ?? 0,
      kind: readText(json['kind']),
      actualWeightKg: readDouble(json['actual_weight_kg']),
      targetTravelerId: readInt(json['target_traveler_id']),
      // Either a coarse Location or, for a legacy row, an airport. Both are
      // handled by AppLocation.maybe.
      origin: AppLocation.maybe(json['origin']),
      destination: AppLocation.maybe(json['destination']),
    );
  }

  final int id;
  final String kind;
  final double? actualWeightKg;
  final int? targetTravelerId;
  final AppLocation? origin;
  final AppLocation? destination;
}

class Match {
  const Match({
    required this.id,
    required this.parcelId,
    required this.senderId,
    required this.travelerId,
    required this.senderName,
    required this.travelerName,
    required this.status,
    this.journeyId,
    this.startLegId,
    this.endLegId,
    this.dealId,
    this.matchedDistanceBand,
    this.compatibility,
    this.parcel,
    this.latestOffer,
    this.acceptedOffer,
    this.createdAt,
    this.updatedAt,
  });

  factory Match.fromJson(Map<String, dynamic> json) {
    final latest = readObject(json['latest_offer']);
    final accepted = readObject(json['accepted_offer']);
    return Match(
      id: readInt(json['id']) ?? 0,
      parcelId: readInt(json['parcel_id']) ?? 0,
      journeyId: readInt(json['journey_id']),
      startLegId: readInt(json['start_leg_id']),
      endLegId: readInt(json['end_leg_id']),
      dealId: readInt(json['deal_id']),
      senderId: readInt(json['sender_id']) ?? 0,
      travelerId: readInt(json['traveler_id']) ?? 0,
      senderName: readText(json['sender_name']),
      travelerName: readText(json['traveler_name']),
      status: readEnum(
        json['status'],
        MatchStatus.values,
        fallback: MatchStatus.unknown,
      ),
      matchedDistanceBand: DistanceBand.maybe(json['matched_distance_band']),
      compatibility: Compatibility.maybe(json['compatibility_snapshot']),
      parcel: MatchParcel.maybe(json['parcel']),
      latestOffer: latest == null ? null : Offer.fromJson(latest),
      acceptedOffer: accepted == null ? null : Offer.fromJson(accepted),
      createdAt: readDate(json['created_at']),
      updatedAt: readDate(json['updated_at']),
    );
  }

  final int id;
  final int parcelId;

  /// Set on a V1 match. A legacy match has `trip_id` instead and no legs; the
  /// client treats such a match as history.
  final int? journeyId;
  final int? startLegId;
  final int? endLegId;

  /// Null until an offer is accepted.
  final int? dealId;

  final int senderId;
  final int travelerId;
  final String senderName;
  final String travelerName;
  final MatchStatus status;
  final DistanceBand? matchedDistanceBand;
  final Compatibility? compatibility;
  final MatchParcel? parcel;
  final Offer? latestOffer;
  final Offer? acceptedOffer;
  final DateTime? createdAt;
  final DateTime? updatedAt;

  bool get isV1 => journeyId != null;
  bool get hasDeal => dealId != null;

  int counterpartyId(int viewerId) =>
      viewerId == senderId ? travelerId : senderId;

  String counterpartyName(int viewerId) =>
      viewerId == senderId ? travelerName : senderName;

  bool isSender(int viewerId) => viewerId == senderId;

  MoneyPerspective? moneyPerspectiveFor(int viewerId) =>
      MoneyPerspective.resolve(
        viewerId: viewerId,
        senderId: senderId,
        travelerId: travelerId,
      );

  /// True when this viewer is the one holding up the negotiation.
  bool awaitsViewer(int viewerId) => latestOffer?.isAwaiting(viewerId) ?? false;
}
