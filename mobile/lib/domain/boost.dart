/// Paid visibility boosts.
///
/// A boost changes ranking and commits most of its value to the eventual
/// traveller. It cannot make an incompatible traveller compatible. The server
/// states this as a literal contract field — `affects_compatibility` is
/// hard-coded false — and the client surfaces it as
/// [BoostState.affectsCompatibility] so the copy on screen is backed by the API
/// rather than by a promise in a comment.
///
/// Buying a boost creates a payment order and nothing else. Activation happens
/// when that order is confirmed paid by a webhook. Returning from a checkout
/// page activates nothing, and the UI must not imply otherwise.
library;

import '../core/money/money.dart';
import 'json.dart';

enum BoostStatus {
  pendingPayment,
  active,
  expired,
  cancelled,

  /// Paid, but the request stopped being boostable before activation. The
  /// platform refunds it automatically.
  unusable,

  refunded,
  unknown;

  bool get occupiesSlot => this == pendingPayment || this == active;
}

class BoostPackage {
  const BoostPackage({
    required this.code,
    required this.label,
    required this.durationSeconds,
    required this.rankingWeight,
    required this.currency,
  });

  factory BoostPackage.fromJson(Map<String, dynamic> json) => BoostPackage(
    code: readText(json['code']),
    label: readText(json['label']),
    durationSeconds: readInt(json['duration_seconds']) ?? 0,
    rankingWeight: readInt(json['ranking_weight']) ?? 0,
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
  );

  final String code;

  /// Server-authored label. Shown as-is; the client does not compose its own
  /// name from the duration.
  final String label;

  final int durationSeconds;

  /// A ranking bonus applied after compatibility filtering.
  final int rankingWeight;

  final String currency;

  Duration get duration => Duration(seconds: durationSeconds);
}

/// `GET /api/boosts/packages`.
class BoostCatalogue {
  const BoostCatalogue({
    required this.enabled,
    required this.maxActivePerRequest,
    required this.currency,
    required this.packages,
    required this.minimumAmount,
    required this.travelerShareBps,
    this.settingsVersion,
  });

  factory BoostCatalogue.fromJson(Map<String, dynamic> json) => BoostCatalogue(
    enabled: readBool(json['enabled']),
    maxActivePerRequest: readInt(json['max_active_per_request']) ?? 0,
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
    settingsVersion: readInt(json['settings_version']),
    minimumAmount:
        Money.eurCentsOrNull(json['minimum_amount_eur_cents']) ??
        Money.eurCents(500),
    travelerShareBps: readInt(json['traveler_share_bps']) ?? 0,
    packages: readObjectList(
      json['packages'],
    ).map(BoostPackage.fromJson).toList(growable: false),
  );

  final bool enabled;
  final int maxActivePerRequest;
  final String currency;
  final int? settingsVersion;
  final Money minimumAmount;
  final int travelerShareBps;
  final List<BoostPackage> packages;

  bool get isAvailable => enabled && packages.isNotEmpty;
}

class BoostPreview {
  const BoostPreview({
    required this.settingsVersion,
    required this.amount,
    required this.travelerBonus,
    required this.platformRevenue,
    required this.travelerShareBps,
    required this.durationSeconds,
    required this.rankingWeight,
  });

  factory BoostPreview.fromJson(Map<String, dynamic> json) {
    final visibility = readObject(json['visibility']);
    return BoostPreview(
      settingsVersion: readInt(json['settings_version']) ?? 0,
      amount: Money.eurCentsOrNull(json['amount_eur_cents'])!,
      travelerBonus: Money.eurCentsOrNull(json['traveler_boost_eur_cents'])!,
      platformRevenue: Money.eurCentsOrNull(json['platform_boost_eur_cents'])!,
      travelerShareBps: readInt(json['traveler_share_bps']) ?? 0,
      durationSeconds: readInt(visibility?['duration_seconds']) ?? 0,
      rankingWeight: readInt(visibility?['ranking_weight']) ?? 0,
    );
  }

  final int settingsVersion;
  final Money amount;
  final Money travelerBonus;
  final Money platformRevenue;
  final int travelerShareBps;
  final int durationSeconds;
  final int rankingWeight;
}

class BoostPurchase {
  const BoostPurchase({
    required this.publicReference,
    required this.packageCode,
    required this.status,
    required this.durationSeconds,
    required this.rankingWeight,
    required this.currency,
    required this.dispositionReason,
    this.deliveryRequestId,
    this.packageLabel,
    this.amount,
    this.travelerBonus,
    this.platformRevenue,
    this.activatedAt,
    this.expiresAt,
    this.cancelledAt,
    this.createdAt,
    this.paymentOrderReference,
    this.paymentStatusRaw,
    this.paymentOutstanding,
  });

  factory BoostPurchase.fromJson(Map<String, dynamic> json) {
    final snapshot = readObject(json['package_snapshot']);
    return BoostPurchase(
      publicReference: readText(json['public_reference']),
      deliveryRequestId: readInt(json['delivery_request_id']),
      packageCode: readText(json['package_code']),
      packageLabel: readString(snapshot?['label']),
      status: readEnum(
        json['status'],
        BoostStatus.values,
        fallback: BoostStatus.unknown,
      ),
      durationSeconds: readInt(json['duration_seconds']) ?? 0,
      amount: Money.eurCentsOrNull(json['amount_eur_cents']),
      travelerBonus: Money.eurCentsOrNull(json['traveler_boost_eur_cents']),
      platformRevenue: Money.eurCentsOrNull(json['platform_boost_eur_cents']),
      currency: readText(json['currency']).isEmpty
          ? 'EUR'
          : readText(json['currency']),
      rankingWeight: readInt(json['ranking_weight']) ?? 0,
      activatedAt: readDate(json['activated_at']),
      expiresAt: readDate(json['expires_at']),
      cancelledAt: readDate(json['cancelled_at']),
      dispositionReason: readText(json['disposition_reason']),
      createdAt: readDate(json['created_at']),
      paymentOrderReference: readString(json['payment_order_reference']),
      paymentStatusRaw: readString(json['payment_status']),
      paymentOutstanding: Money.eurCentsOrNull(
        json['payment_outstanding_eur_cents'],
      ),
    );
  }

  final String publicReference;
  final int? deliveryRequestId;
  final String packageCode;
  final String? packageLabel;
  final BoostStatus status;
  final int durationSeconds;
  final Money? amount;
  final Money? travelerBonus;
  final Money? platformRevenue;
  final String currency;
  final int rankingWeight;
  final DateTime? activatedAt;
  final DateTime? expiresAt;
  final DateTime? cancelledAt;
  final String dispositionReason;
  final DateTime? createdAt;

  /// The order to take to the standard checkout route. Buying a boost never
  /// opens a provider session by itself.
  final String? paymentOrderReference;

  final String? paymentStatusRaw;
  final Money? paymentOutstanding;

  bool get isActive => status == BoostStatus.active;

  bool get awaitsPayment =>
      status == BoostStatus.pendingPayment &&
      (paymentOutstanding?.isPositive ?? true);
}

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
    required this.activeCount,
    required this.occupiedSlots,
    required this.purchases,
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
    activeCount: readInt(json['active_count']) ?? 0,
    occupiedSlots: readInt(json['occupied_slots']) ?? 0,
    purchases: readObjectList(
      json['purchases'],
    ).map(BoostPurchase.fromJson).toList(growable: false),
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

  final int activeCount;
  final int occupiedSlots;
  final List<BoostPurchase> purchases;

  /// J2 additive boost reward.
  final Money boostEur;
  final BoostEconomics? economics;
  final BoostPolicy? policy;
  final bool canEdit;
  final DateTime? eligibleUntil;
  final List<BoostIntentHistoryEvent> history;

  bool get isBoosted => boostEur.isPositive;

  BoostPurchase? get pendingPurchase {
    for (final purchase in purchases) {
      if (purchase.awaitsPayment) return purchase;
    }
    return null;
  }
}
