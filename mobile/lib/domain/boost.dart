/// The sender's Boost: an extra reward, in euros, added to what the traveler
/// is offered (J2).
///
/// A Boost raises ranking and goes to the traveler. It cannot make an
/// incompatible traveler compatible. The server states this as a literal
/// contract field, `affects_compatibility`, hard-coded false, and the client
/// surfaces it as [BoostState.affectsCompatibility] so the copy on screen is
/// backed by the API rather than by a promise in a comment. There is no paid
/// Boost package.
library;

import '../core/money/money.dart';
import 'json.dart';

/// The bounds and the rate a client may show before the sender chooses a Boost.
class BoostPolicy {
  const BoostPolicy({
    required this.currency,
    required this.enabled,
    required this.minimumBoost,
    required this.maximumBoost,
    required this.boostCommissionRateBps,
    required this.settingsVersion,
    required this.affectsCompatibility,
    required this.hasExpiry,
  });

  factory BoostPolicy.fromJson(Map<String, dynamic> json) => BoostPolicy(
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
    enabled: readBool(json['enabled']),
    minimumBoost: Money.eurCents(readInt(json['minimum_boost_eur_cents']) ?? 0),
    maximumBoost: Money.eurCents(
      readInt(json['maximum_boost_eur_cents']) ?? 10000,
    ),
    boostCommissionRateBps: readInt(json['boost_commission_rate_bps']) ?? 0,
    settingsVersion: readInt(json['settings_version']) ?? 0,
    affectsCompatibility: readBool(json['affects_compatibility']),
    hasExpiry: readBool(json['has_expiry']),
  );

  final String currency;
  final bool enabled;
  final Money minimumBoost;
  final Money maximumBoost;
  final int boostCommissionRateBps;
  final int settingsVersion;
  final bool affectsCompatibility;
  final bool hasExpiry;
}

/// J2 Additive Boost Economics.
class BoostEconomics {
  const BoostEconomics({
    required this.economicsVersion,
    required this.currency,
    required this.boostEur,
    required this.commissionRateBps,
    required this.travelerBonus,
    required this.platformFee,
    required this.senderCost,
    required this.roundingRule,
  });

  factory BoostEconomics.fromJson(Map<String, dynamic> json) => BoostEconomics(
    economicsVersion: readText(json['economics_version']),
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
    boostEur: Money.eurCents(readInt(json['boost_eur_cents']) ?? 0),
    commissionRateBps: readInt(json['boost_commission_rate_bps']) ?? 0,
    travelerBonus: Money.eurCents(
      readInt(json['boost_traveler_bonus_eur_cents']) ?? 0,
    ),
    platformFee: Money.eurCents(
      readInt(json['boost_platform_fee_eur_cents']) ?? 0,
    ),
    senderCost: Money.eurCents(
      readInt(json['boost_sender_cost_eur_cents']) ?? 0,
    ),
    roundingRule: readText(json['rounding_rule']),
  );

  final String economicsVersion;
  final String currency;
  final Money boostEur;
  final int commissionRateBps;
  final Money travelerBonus;
  final Money platformFee;
  final Money senderCost;
  final String roundingRule;
}

/// A history audit event when a sender sets or updates a Boost.
class BoostIntentHistoryEvent {
  const BoostIntentHistoryEvent({
    required this.reason,
    required this.previousAmount,
    required this.amount,
    required this.createdAt,
  });

  factory BoostIntentHistoryEvent.fromJson(Map<String, dynamic> json) =>
      BoostIntentHistoryEvent(
        reason: readText(json['reason']),
        previousAmount: Money.eurCents(
          readInt(json['previous_eur_cents']) ?? 0,
        ),
        amount: Money.eurCents(readInt(json['amount_eur_cents']) ?? 0),
        createdAt: readDate(json['created_at']) ?? DateTime.now(),
      );

  final String reason;
  final Money previousAmount;
  final Money amount;
  final DateTime createdAt;
}

/// `GET /api/parcels/<id>/boost`.
class BoostState {
  const BoostState({
    required this.deliveryRequestId,
    required this.requestStatusRaw,
    required this.isOwner,
    required this.rankingBoostActive,
    required this.rankingBoostWeight,
    required this.affectsCompatibility,
    this.rankingBoostExpiresAt,
    this.boostEur = Money.zeroEur,
    this.economics,
    this.policy,
    this.canEdit = false,
    this.eligibleUntil,
    this.history = const [],
  });

  factory BoostState.fromJson(Map<String, dynamic> json) => BoostState(
    deliveryRequestId: readInt(json['delivery_request_id']) ?? 0,
    requestStatusRaw: readText(json['request_status']),
    isOwner: readBool(json['is_owner']),
    rankingBoostActive: readBool(json['ranking_boost_active']),
    rankingBoostWeight: readInt(json['ranking_boost_weight']) ?? 0,
    rankingBoostExpiresAt: readDate(json['ranking_boost_expires_at']),
    affectsCompatibility: readBool(json['affects_compatibility']),
    boostEur: Money.eurCents(readInt(json['boost_eur_cents']) ?? 0),
    economics: readObject(json['economics']) == null
        ? null
        : BoostEconomics.fromJson(readObject(json['economics'])!),
    policy: readObject(json['policy']) == null
        ? null
        : BoostPolicy.fromJson(readObject(json['policy'])!),
    canEdit: readBool(json['can_edit']),
    eligibleUntil: readDate(json['eligible_until']),
    history: readObjectList(
      json['history'],
    ).map(BoostIntentHistoryEvent.fromJson).toList(growable: false),
  );

  final int deliveryRequestId;
  final String requestStatusRaw;
  final bool isOwner;
  final bool rankingBoostActive;
  final int rankingBoostWeight;
  final DateTime? rankingBoostExpiresAt;

  /// Contractually false.
  final bool affectsCompatibility;

  /// J2 additive boost reward.
  final Money boostEur;
  final BoostEconomics? economics;
  final BoostPolicy? policy;
  final bool canEdit;
  final DateTime? eligibleUntil;
  final List<BoostIntentHistoryEvent> history;

  bool get isBoosted => boostEur.isPositive;
}
