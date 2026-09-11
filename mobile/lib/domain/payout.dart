/// Traveler payout models conforming to Phase 8F-H6A mobile payout contract.
///
/// Flutter never calculates eligibility, rails, readiness, settlement amounts,
/// FX rates, or return states. Every field arrives from the server.
library;

import '../core/money/money.dart';
import 'json.dart';
import 'payment.dart' show PayoutStatus;

/// Authoritative preference values accepted by PATCH /api/payouts/methods.
enum PayoutPreference {
  eurOnly('eur_only'),
  dzdOnly('dzd_only'),
  both('both'),
  unknown('');

  const PayoutPreference(this.wire);
  final String wire;

  static PayoutPreference? parse(String? raw) => switch (raw) {
    'eur_only' => eurOnly,
    'dzd_only' => dzdOnly,
    'both' => both,
    null => null,
    _ => unknown,
  };
}

/// Server states for EUR method card.
enum EurPayoutState {
  notConfigured('not_configured'),
  setupRequired('setup_required'),
  pendingVerification('pending_verification'),
  ready('ready'),
  needsAttention('needs_attention'),
  unknown('');

  const EurPayoutState(this.wire);
  final String wire;

  static EurPayoutState parse(String? raw) => switch (raw) {
    'not_configured' => notConfigured,
    'setup_required' => setupRequired,
    'pending_verification' => pendingVerification,
    'ready' => ready,
    'needs_attention' => needsAttention,
    _ => unknown,
  };
}

/// Server states for DZD method card.
enum DzdPayoutState {
  notConfigured('not_configured'),
  setupRequired('setup_required'),
  pendingReview('pending_review'),
  ready('ready'),
  needsAttention('needs_attention'),
  inactive('inactive'),
  unknown('');

  const DzdPayoutState(this.wire);
  final String wire;

  static DzdPayoutState parse(String? raw) => switch (raw) {
    'not_configured' => notConfigured,
    'setup_required' => setupRequired,
    'pending_review' => pendingReview,
    'ready' => ready,
    'needs_attention' => needsAttention,
    'inactive' => inactive,
    _ => unknown,
  };
}

/// Semantic display states from H6A table.
enum PayoutDisplayState {
  awaitingDelivery('awaiting_delivery'),
  protectionActive('protection_active'),
  releasePending('release_pending'),
  ready('ready'),
  processing('processing'),
  sent('sent'),
  paid('paid'),
  needsAttention('needs_attention'),
  cancelled('cancelled'),
  unknown('');

  const PayoutDisplayState(this.wire);
  final String wire;

  static PayoutDisplayState parse(String? raw) => switch (raw) {
    'awaiting_delivery' => awaitingDelivery,
    'protection_active' => protectionActive,
    'release_pending' => releasePending,
    'ready' => ready,
    'processing' => processing,
    'sent' => sent,
    'paid' => paid,
    'needs_attention' => needsAttention,
    'cancelled' => cancelled,
    _ => unknown,
  };
}

/// Payout rails from H6A.
enum PayoutRail {
  stripeEur('stripe_eur'),
  manualDzd('manual_dzd'),
  unavailable('unavailable'),
  unknown('');

  const PayoutRail(this.wire);
  final String wire;

  static PayoutRail parse(String? raw) => switch (raw) {
    'stripe_eur' => stripeEur,
    'manual_dzd' => manualDzd,
    'unavailable' => unavailable,
    _ => unknown,
  };
}

/// Masked DZD profile summary. Full credentials are never exposed after submission.
class DzdProfileSummary {
  const DzdProfileSummary({
    required this.reference,
    required this.reviewState,
    this.ccpLastFour,
    this.ripLastFour,
    this.submittedAt,
  });

  factory DzdProfileSummary.fromJson(Map<String, dynamic> json) =>
      DzdProfileSummary(
        reference: readText(json['reference']),
        reviewState: readText(json['review_state']),
        ccpLastFour: readString(json['ccp_last_four']),
        ripLastFour: readString(json['rip_last_four']),
        submittedAt: readDate(json['submitted_at']),
      );

  static DzdProfileSummary? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DzdProfileSummary.fromJson(json);
  }

  final String reference;
  final String reviewState;
  final String? ccpLastFour;
  final String? ripLastFour;
  final DateTime? submittedAt;
}

/// EUR payout method status from `GET /api/payouts/methods`.
class EurPayoutMethod {
  const EurPayoutMethod({
    required this.state,
    required this.ready,
    required this.supported,
    required this.availableActions,
    required this.supportedCountries,
    this.blockingReason,
    this.country,
    this.checkedAt,
  });

  factory EurPayoutMethod.fromJson(Map<String, dynamic> json) => EurPayoutMethod(
    state: EurPayoutState.parse(readString(json['state'])),
    ready: readBool(json['ready']),
    supported: readBool(json['supported']),
    blockingReason: readString(json['blocking_reason']),
    country: readString(json['country']),
    checkedAt: readDate(json['checked_at']),
    availableActions: (json['available_actions'] as List<dynamic>? ?? const [])
        .map((e) => e.toString())
        .where((s) => s.isNotEmpty)
        .toList(growable: false),
    supportedCountries:
        (json['supported_countries'] as List<dynamic>? ?? const [])
            .map((e) => e.toString())
            .toList(growable: false),
  );

  static EurPayoutMethod? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : EurPayoutMethod.fromJson(json);
  }

  final EurPayoutState state;
  final bool ready;
  final bool supported;
  final String? blockingReason;
  final String? country;
  final DateTime? checkedAt;
  final List<String> availableActions;
  final List<String> supportedCountries;

  bool can(String action) => availableActions.contains(action);
}

/// DZD payout method status from `GET /api/payouts/methods`.
class DzdPayoutMethod {
  const DzdPayoutMethod({
    required this.state,
    required this.ready,
    required this.supported,
    required this.availableActions,
    this.blockingReason,
    this.country,
    this.profile,
    this.replacementScope,
  });

  factory DzdPayoutMethod.fromJson(Map<String, dynamic> json) => DzdPayoutMethod(
    state: DzdPayoutState.parse(readString(json['state'])),
    ready: readBool(json['ready']),
    supported: readBool(json['supported']),
    blockingReason: readString(json['blocking_reason']),
    country: readString(json['country']),
    profile: DzdProfileSummary.maybe(json['profile']),
    replacementScope: readString(json['replacement_scope']),
    availableActions: (json['available_actions'] as List<dynamic>? ?? const [])
        .map((e) => e.toString())
        .where((s) => s.isNotEmpty)
        .toList(growable: false),
  );

  static DzdPayoutMethod? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : DzdPayoutMethod.fromJson(json);
  }

  final DzdPayoutState state;
  final bool ready;
  final bool supported;
  final String? blockingReason;
  final String? country;
  final DzdProfileSummary? profile;
  final String? replacementScope;
  final List<String> availableActions;

  bool can(String action) => availableActions.contains(action);
}

/// Root response from `GET /api/payouts/methods` and `PATCH /api/payouts/methods`.
class PayoutMethodsSummary {
  const PayoutMethodsSummary({
    required this.contractVersion,
    required this.preferenceRequired,
    required this.revisions,
    required this.availableActions,
    this.preference,
    this.eur,
    this.dzd,
    this.preferenceScope,
  });

  factory PayoutMethodsSummary.fromJson(Map<String, dynamic> json) {
    final revMap = <String, int>{};
    final rawRevs = readObject(json['revisions']);
    if (rawRevs != null) {
      for (final entry in rawRevs.entries) {
        final val = readInt(entry.value);
        if (val != null) revMap[entry.key] = val;
      }
    }

    final rawActions = json['available_actions'] as List<dynamic>? ?? const [];
    final actions = rawActions.map((e) => e.toString()).toList(growable: false);

    return PayoutMethodsSummary(
      contractVersion: readText(json['contract_version']),
      preference: PayoutPreference.parse(readString(json['preference'])),
      preferenceRequired: readBool(json['preference_required']),
      revisions: revMap,
      eur: EurPayoutMethod.maybe(json['eur']),
      dzd: DzdPayoutMethod.maybe(json['dzd']),
      availableActions: actions,
      preferenceScope: readString(json['preference_scope']),
    );
  }

  final String contractVersion;
  final PayoutPreference? preference;
  final bool preferenceRequired;
  final Map<String, int> revisions;
  final EurPayoutMethod? eur;
  final DzdPayoutMethod? dzd;
  final List<String> availableActions;
  final String? preferenceScope;

  int revisionFor(String currency) => revisions[currency] ?? 0;
  bool can(String action) => availableActions.contains(action);
}

/// Normalized mobile payout representation from `payout_status`.
/// Used in `mobile` field of Payouts, `payout_summary` of Deal, and `GET /api/payouts/<ref>`.
class PayoutMobile {
  const PayoutMobile({
    required this.reference,
    required this.dealId,
    required this.rail,
    required this.amountEurCents,
    required this.state,
    required this.displayState,
    required this.messageKey,
    required this.protectionActive,
    required this.availableActions,
    this.settlementCurrency,
    this.dzdAmount,
    this.fxRateMicros,
    this.protectionEndsAt,
    this.serverTime,
    this.eligibleAt,
    this.blockingReason,
    this.updatedAt,
    this.sentAt,
    this.paidAt,
    this.destinationScope,
  });

  factory PayoutMobile.fromJson(Map<String, dynamic> json) {
    final rawActions = json['available_actions'] as List<dynamic>? ?? const [];
    final actions = rawActions.map((e) => e.toString()).toList(growable: false);

    return PayoutMobile(
      reference: readText(json['reference']),
      dealId: readInt(json['deal_id']) ?? 0,
      rail: PayoutRail.parse(readString(json['rail'])),
      settlementCurrency: readString(json['settlement_currency']),
      amountEurCents: readInt(json['amount_eur_cents']) ?? 0,
      dzdAmount: readInt(json['dzd_amount']),
      fxRateMicros: readInt(json['fx_rate_micros']),
      state: readEnum(
        json['state'],
        PayoutStatus.values,
        fallback: PayoutStatus.unknown,
      ),
      displayState: PayoutDisplayState.parse(readString(json['display_state'])),
      messageKey: readText(json['message_key']),
      protectionActive: readBool(json['protection_active']),
      protectionEndsAt: readDate(json['protection_ends_at']),
      serverTime: readDate(json['server_time']),
      eligibleAt: readDate(json['eligible_at']),
      blockingReason: readString(json['blocking_reason']),
      availableActions: actions,
      updatedAt: readDate(json['updated_at']),
      sentAt: readDate(json['sent_at']),
      paidAt: readDate(json['paid_at']),
      destinationScope: readString(json['destination_scope']),
    );
  }

  static PayoutMobile? maybe(Object? raw) {
    final json = readObject(raw);
    return json == null ? null : PayoutMobile.fromJson(json);
  }

  final String reference;
  final int dealId;
  final PayoutRail rail;
  final String? settlementCurrency;
  final int amountEurCents;
  final int? dzdAmount;
  final int? fxRateMicros;
  final PayoutStatus state;
  final PayoutDisplayState displayState;
  final String messageKey;
  final bool protectionActive;
  final DateTime? protectionEndsAt;
  final DateTime? serverTime;
  final DateTime? eligibleAt;
  final String? blockingReason;
  final List<String> availableActions;
  final DateTime? updatedAt;
  final DateTime? sentAt;
  final DateTime? paidAt;
  final String? destinationScope;

  Money get canonicalEurAmount => Money.eurCents(amountEurCents);

  bool can(String action) => availableActions.contains(action);

  /// Formatted exchange rate string if fxRateMicros is provided (e.g. 260000000 -> 260).
  /// Micros is integer 1,000,000 * rate.
  String? get formattedFxRate {
    final micros = fxRateMicros;
    if (micros == null || micros <= 0) return null;
    final rate = micros / 1000000.0;
    if (rate == rate.roundToDouble()) {
      return rate.toInt().toString();
    }
    return rate.toStringAsFixed(2);
  }
}

/// Paginated payout history response from `GET /api/payouts?page=X&page_size=Y`.
class PayoutHistoryPage {
  const PayoutHistoryPage({
    required this.count,
    required this.results,
    this.next,
    this.previous,
  });

  factory PayoutHistoryPage.fromJson(Map<String, dynamic> json) =>
      PayoutHistoryPage(
        count: readInt(json['count']) ?? 0,
        next: readString(json['next']),
        previous: readString(json['previous']),
        results:
            (json['results'] as List<dynamic>? ?? const [])
                .whereType<Map>()
                .map((r) => PayoutListItem.fromJson(Map<String, dynamic>.from(r)))
                .toList(growable: false),
      );

  final int count;
  final String? next;
  final String? previous;
  final List<PayoutListItem> results;

  bool get hasNext => next != null && next!.isNotEmpty;
}

/// Item in the payout history list containing legacy fields plus `mobile`.
class PayoutListItem {
  const PayoutListItem({
    required this.id,
    required this.dealId,
    required this.amountEurCents,
    required this.method,
    required this.status,
    required this.reference,
    this.payoutCurrency,
    this.payoutAmountLabel,
    this.eligibleAt,
    this.paidAt,
    this.createdAt,
    this.mobile,
  });

  factory PayoutListItem.fromJson(Map<String, dynamic> json) => PayoutListItem(
    id: readInt(json['id']) ?? 0,
    dealId: readInt(json['deal_id']) ?? 0,
    amountEurCents: readInt(json['amount_eur_cents']) ?? 0,
    method: readText(json['method']),
    status: readText(json['status']),
    reference: readText(json['reference']),
    payoutCurrency: readString(json['payout_currency']),
    payoutAmountLabel: readString(json['payout_amount']),
    eligibleAt: readDate(json['eligible_at']),
    paidAt: readDate(json['paid_at']),
    createdAt: readDate(json['created_at']),
    mobile: PayoutMobile.maybe(json['mobile']),
  );

  final int id;
  final int dealId;
  final int amountEurCents;
  final String method;
  final String status;
  final String reference;
  final String? payoutCurrency;
  final String? payoutAmountLabel;
  final DateTime? eligibleAt;
  final DateTime? paidAt;
  final DateTime? createdAt;
  final PayoutMobile? mobile;

  Money get amountEur => Money.eurCents(amountEurCents);
}
