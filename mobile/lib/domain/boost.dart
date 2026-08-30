/// Paid visibility boosts.
///
/// A boost changes **ranking only**. It cannot make an incompatible traveller
/// compatible, and it cannot conjure a match. The server states this as a
/// literal contract field — `affects_compatibility` is hard-coded false — and
/// the client surfaces it as [BoostState.affectsCompatibility] so the copy on
/// screen is backed by the API rather than by a promise in a comment.
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
    this.price,
  });

  factory BoostPackage.fromJson(Map<String, dynamic> json) => BoostPackage(
    code: readText(json['code']),
    label: readText(json['label']),
    durationSeconds: readInt(json['duration_seconds']) ?? 0,
    price: Money.eurCentsOrNull(json['price_eur_cents']),
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
  final Money? price;

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
    this.settingsVersion,
  });

  factory BoostCatalogue.fromJson(Map<String, dynamic> json) => BoostCatalogue(
    enabled: readBool(json['enabled']),
    maxActivePerRequest: readInt(json['max_active_per_request']) ?? 0,
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
    settingsVersion: readInt(json['settings_version']),
    packages: readObjectList(
      json['packages'],
    ).map(BoostPackage.fromJson).toList(growable: false),
  );

  final bool enabled;
  final int maxActivePerRequest;
  final String currency;
  final int? settingsVersion;
  final List<BoostPackage> packages;

  bool get isAvailable => enabled && packages.isNotEmpty;
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
    this.price,
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
      price: Money.eurCentsOrNull(json['price_eur_cents']),
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
  final Money? price;
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

/// `GET /api/parcels/<id>/boosts`.
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
  });

  factory BoostState.fromJson(Map<String, dynamic> json) => BoostState(
    deliveryRequestId: readInt(json['delivery_request_id']) ?? 0,
    requestStatusRaw: readText(json['request_status']),
    isOwner: readBool(json['is_owner']),
    rankingBoostActive: readBool(json['ranking_boost_active']),
    rankingBoostWeight: readInt(json['ranking_boost_weight']) ?? 0,
    rankingBoostExpiresAt: readDate(json['ranking_boost_expires_at']),
    // Always false. Read rather than assumed so the promise on screen is the
    // API's, not ours.
    affectsCompatibility: readBool(json['affects_compatibility']),
    activeCount: readInt(json['active_count']) ?? 0,
    occupiedSlots: readInt(json['occupied_slots']) ?? 0,
    purchases: readObjectList(
      json['purchases'],
    ).map(BoostPurchase.fromJson).toList(growable: false),
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

  BoostPurchase? get pendingPurchase {
    for (final purchase in purchases) {
      if (purchase.awaitsPayment) return purchase;
    }
    return null;
  }
}
