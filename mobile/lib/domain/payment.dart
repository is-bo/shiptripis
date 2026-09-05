/// Payments: orders, attempts, providers, deposits, payouts.
///
/// Three things this file is careful about, because getting any of them wrong
/// is a money bug:
///
/// 1. **`outstanding` is a server field, not a subtraction.** The API computes
///    `amount − credited − paid` and publishes the result. This client reads
///    it. There is no code path here that subtracts one [Money] from another,
///    because [Money] has no operators.
///
/// 2. **A redirect is not a payment.** [PaymentOrderStatus] has no
///    `processing` member, because the *order* has no such state: it stays
///    `pending` until a webhook lands. "In flight" lives on the newest
///    [PaymentAttempt]. A screen that returns from a provider must show a
///    confirming state driven by [PaymentOrder.isSettling], never by the
///    redirect's own query string.
///
/// 3. **The dinar amount is a rail detail, not a price.** EUR is canonical.
///    Chargily's DZD figure has exponent 0 — whole dinars — and the server
///    rounds it up. Both the amount and the rate arrive pre-computed, and this
///    file never converts between the two.
library;

import '../core/money/money.dart';
import 'communication_language.dart';
import 'json.dart';

enum PaymentProviderId {
  stripe,
  chargily,
  mock,
  unknown;

  /// Exactly what the server's `ChoiceField` accepts — lowercase, no aliases.
  String get wire => name;
}

/// The order's own status. Note the deliberate absence of a "processing"
/// member: the server has none.
enum PaymentOrderStatus {
  pending,
  partiallyPaid,
  paid,
  refundPending,
  partiallyRefunded,
  refunded,
  cancelled,
  unknown;

  bool get isCollectable => this == pending || this == partiallyPaid;
  bool get isSettled => this == paid;
  bool get isRefunding =>
      this == refundPending || this == partiallyRefunded || this == refunded;
}

enum PaymentAttemptStatus {
  created,
  checkoutPending,
  processing,
  succeeded,
  failed,
  expired,
  cancelled,
  unknown;

  /// Money is on its way and the outcome is not known yet.
  bool get isInFlight =>
      this == created || this == checkoutPending || this == processing;

  bool get isDead => this == failed || this == expired || this == cancelled;
}

enum PaymentPurpose { postingDeposit, dealBalance, boost, unknown }

enum PaymentRefundStatus { pending, processing, succeeded, failed, unknown }

enum PayoutStatus {
  notEligible,
  eligible,
  scheduled,
  processing,
  paid,
  failed,
  cancelled,
  frozen,
  unknown;

  /// Frozen means a dispute is holding the money. Distinct from "not yet due".
  bool get isBlocked => this == frozen || this == failed || this == cancelled;

  bool get isPending =>
      this == notEligible ||
      this == eligible ||
      this == scheduled ||
      this == processing;
}

enum PayoutMethod { undecided, stripeTransfer, manual, unknown }

/// One payment rail: whether it can be used, and what it would charge.
///
/// **The rail decides its settlement currency, and the server decides the
/// amount.** There is no currency choice in this client and no conversion in
/// it either. A row arrives saying "Stripe, EUR, €37.50" or "Chargily, DZD,
/// 5,625 DA against a canonical €37.50" and is rendered as it stands. That is
/// the whole reason [settlementAmount] exists: a single "Pay €37.50" button
/// sitting under a rail that charges dinars is how the screen came to read as
/// "pick a provider, then pick a currency".
class ProviderOption {
  const ProviderOption({
    required this.provider,
    required this.available,
    required this.paymentCurrency,
    required this.supportsGuestPayment,
    required this.unavailableReason,
    this.settlementAmount,
    this.settlementAmountLabel,
    this.canonicalAmount,
    this.eurDzdRate,
    this.rateSettingsVersion,
    this.rateIsIndicative = false,
  });

  factory ProviderOption.fromJson(Map<String, dynamic> json) {
    // `settlement_currency` is the newer name for the same server fact; older
    // payloads carry only `payment_currency`. Neither is ever a client choice.
    final currency = readText(json['settlement_currency']).isEmpty
        ? readText(json['payment_currency'])
        : readText(json['settlement_currency']);
    return ProviderOption(
      provider: readEnum(
        json['provider'],
        PaymentProviderId.values,
        fallback: PaymentProviderId.unknown,
      ),
      available: readBool(json['available']),
      paymentCurrency: currency,
      supportsGuestPayment: readBool(json['supports_guest_payment']),
      unavailableReason: readText(json['unavailable_reason']),
      settlementAmount: Money.minorOrNull(
        json['settlement_amount_minor'],
        currency: currency.isEmpty ? 'EUR' : currency,
        exponent: readInt(json['settlement_amount_exponent']),
      ),
      settlementAmountLabel: readString(json['settlement_amount']),
      canonicalAmount: Money.eurCentsOrNull(json['canonical_amount_eur_cents']),
      eurDzdRate: readString(json['eur_dzd_rate']),
      rateSettingsVersion: readInt(json['rate_settings_version']),
      rateIsIndicative: readBool(json['rate_is_indicative']),
    );
  }

  final PaymentProviderId provider;

  /// The combined enabled + configured + configuration-valid + accepting-
  /// checkouts gate. **The only field a "pay with X" button may be enabled
  /// from.**
  final bool available;

  /// The currency this rail settles in. A property of the rail, never of the
  /// payer: EUR for Stripe, DZD for Chargily.
  final String paymentCurrency;

  final bool supportsGuestPayment;

  /// `disabled_by_policy`, `provider_not_configured`,
  /// `provider_configuration_invalid`, `new_checkouts_disabled`,
  /// `amount_below_provider_minimum`, or empty.
  final String unavailableReason;

  /// What this rail will take, in its own currency. Server-computed. Absent on
  /// the standalone providers endpoint, which has no obligation in hand.
  final Money? settlementAmount;

  /// The server's own decimal-string rendering of [settlementAmount].
  final String? settlementAmountLabel;

  /// The canonical EUR obligation the settlement amount stands for. Equal to
  /// [settlementAmount] on a euro rail, which is exactly why the euro rail
  /// shows no equivalence line.
  final Money? canonicalAmount;

  /// Pre-formatted `150.000000`. Non-null only on a dinar rail.
  final String? eurDzdRate;

  final int? rateSettingsVersion;

  /// True when the rate shown is today's rather than a frozen one. The binding
  /// rate is snapshotted onto the attempt when the checkout is created.
  final bool rateIsIndicative;

  bool get chargesForeignCurrency => paymentCurrency.toUpperCase() != 'EUR';

  /// Whether an equivalence line adds anything. It does not on a euro rail,
  /// where the settlement amount and the obligation are the same number.
  bool get showsCanonicalEquivalent =>
      chargesForeignCurrency && canonicalAmount != null;
}

/// `GET /api/payments/providers`.
class ProvidersView {
  const ProvidersView({
    required this.timingMode,
    required this.canonicalCurrency,
    required this.providers,
    this.chargilyRate,
    this.chargilyRateSettingsVersion,
  });

  factory ProvidersView.fromJson(Map<String, dynamic> json) {
    final rate = readObject(json['chargily_rate']);
    return ProvidersView(
      timingMode: readText(json['timing_mode']),
      canonicalCurrency: readText(json['canonical_currency']).isEmpty
          ? 'EUR'
          : readText(json['canonical_currency']),
      providers: readObjectList(json['providers'])
          .map(ProviderOption.fromJson)
          // The mock rail is a local test fixture and is refused in
          // production. It is never offered as a choice.
          .where((p) => p.provider != PaymentProviderId.mock)
          .toList(growable: false),
      chargilyRate: readString(rate?['eur_dzd_rate']),
      chargilyRateSettingsVersion: readInt(rate?['rate_settings_version']),
    );
  }

  /// `posting_deposit` or `after_acceptance` — when the platform charges.
  final String timingMode;

  final String canonicalCurrency;
  final List<ProviderOption> providers;

  /// Pre-formatted by the server to six decimal places. Displayed verbatim,
  /// never re-derived from the micros integer.
  final String? chargilyRate;

  final int? chargilyRateSettingsVersion;

  List<ProviderOption> get usable =>
      providers.where((p) => p.available).toList(growable: false);

  bool get hasUsableProvider => usable.isNotEmpty;
}

class PaymentAttempt {
  const PaymentAttempt({
    required this.id,
    required this.provider,
    required this.status,
    required this.isGuestPayment,
    required this.failureCode,
    this.amount,
    this.paymentCurrency,
    this.providerAmount,
    this.paymentAmountLabel,
    this.eurDzdRate,
    this.checkoutUrl,
    this.expiresAt,
    this.succeededAt,
    this.createdAt,
  });

  factory PaymentAttempt.fromJson(Map<String, dynamic> json) {
    final currency = readText(json['payment_currency']);
    return PaymentAttempt(
      id: readInt(json['id']) ?? 0,
      provider: readEnum(
        json['provider'],
        PaymentProviderId.values,
        fallback: PaymentProviderId.unknown,
      ),
      status: readEnum(
        json['status'],
        PaymentAttemptStatus.values,
        fallback: PaymentAttemptStatus.unknown,
      ),
      amount: Money.eurCentsOrNull(json['amount_eur_cents']),
      paymentCurrency: currency.isEmpty ? null : currency,
      providerAmount: Money.minorOrNull(
        json['provider_amount_minor'],
        currency: currency.isEmpty ? 'EUR' : currency,
        exponent: readInt(json['provider_amount_exponent']),
      ),
      paymentAmountLabel: readString(json['payment_amount']),
      eurDzdRate: readString(json['eur_dzd_rate']),
      checkoutUrl: readString(json['checkout_url']),
      failureCode: readText(json['failure_code']),
      isGuestPayment: readBool(json['is_guest_payment']),
      expiresAt: readDate(json['expires_at']),
      succeededAt: readDate(json['succeeded_at']),
      createdAt: readDate(json['created_at']),
    );
  }

  final int id;
  final PaymentProviderId provider;
  final PaymentAttemptStatus status;

  /// Canonical EUR, even for a dinar attempt.
  final Money? amount;

  final String? paymentCurrency;

  /// What the rail actually charges, in its own currency.
  final Money? providerAmount;

  /// The server's own decimal-string rendering of [providerAmount]. Preferred
  /// for display where it exists.
  final String? paymentAmountLabel;

  /// Pre-formatted `150.000000`.
  final String? eurDzdRate;

  /// Hosted checkout page. There is no client secret and no embedded form;
  /// this URL is the whole redirect contract.
  final String? checkoutUrl;

  final String failureCode;
  final bool isGuestPayment;
  final DateTime? expiresAt;
  final DateTime? succeededAt;
  final DateTime? createdAt;

  bool get isExpired {
    final at = expiresAt;
    return at != null && at.isBefore(DateTime.now());
  }

  bool get canResume => status.isInFlight && checkoutUrl != null && !isExpired;
}

class PaymentRefund {
  const PaymentRefund({
    required this.id,
    required this.status,
    required this.reason,
    this.amount,
    this.createdAt,
  });

  factory PaymentRefund.fromJson(Map<String, dynamic> json) => PaymentRefund(
    id: readInt(json['id']) ?? 0,
    status: readEnum(
      json['status'],
      PaymentRefundStatus.values,
      fallback: PaymentRefundStatus.unknown,
    ),
    reason: readText(json['reason']),
    amount: Money.eurCentsOrNull(json['amount_eur_cents']),
    createdAt: readDate(json['created_at']),
  );

  final int id;
  final PaymentRefundStatus status;

  /// `deal_cancelled`, `dispute_resolution`, `deposit_expiry`, …
  final String reason;

  final Money? amount;
  final DateTime? createdAt;
}

/// The Chargily conversion, computed and frozen by the server.
class ChargilyQuote {
  const ChargilyQuote({
    required this.eurDzdRate,
    this.canonicalAmount,
    this.paymentAmount,
    this.rateSettingsVersion,
  });

  static ChargilyQuote? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return ChargilyQuote(
      canonicalAmount: Money.eurCentsOrNull(json['canonical_amount_eur_cents']),
      // DZD has no minor unit: exponent 0, whole dinars.
      paymentAmount: Money.minorOrNull(
        json['payment_amount_dzd'],
        currency: 'DZD',
        exponent: 0,
      ),
      eurDzdRate: readText(json['eur_dzd_rate']),
      rateSettingsVersion: readInt(json['rate_settings_version']),
    );
  }

  final Money? canonicalAmount;
  final Money? paymentAmount;
  final String eurDzdRate;
  final int? rateSettingsVersion;
}

class PaymentOrder {
  const PaymentOrder({
    required this.publicReference,
    required this.purpose,
    required this.status,
    required this.currency,
    required this.attempts,
    required this.refunds,
    required this.providers,
    this.amount,
    this.depositCredit,
    this.paid,
    this.refunded,
    this.outstanding,
    this.dealId,
    this.deliveryRequestId,
    this.paidAt,
    this.createdAt,
    this.chargilyQuote,
    this.isReducedProjection = false,
  });

  factory PaymentOrder.fromJson(
    Map<String, dynamic> json, {
    bool isReducedProjection = false,
  }) => PaymentOrder(
    publicReference: readText(json['public_reference']),
    purpose: readEnum(
      json['purpose'],
      PaymentPurpose.values,
      fallback: PaymentPurpose.unknown,
    ),
    status: readEnum(
      json['status'],
      PaymentOrderStatus.values,
      fallback: PaymentOrderStatus.unknown,
    ),
    currency: readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']),
    amount: Money.eurCentsOrNull(json['amount_eur_cents']),
    depositCredit: Money.eurCentsOrNull(json['deposit_credit_eur_cents']),
    paid: Money.eurCentsOrNull(json['paid_eur_cents']),
    refunded: Money.eurCentsOrNull(json['refunded_eur_cents']),
    outstanding: Money.eurCentsOrNull(json['outstanding_eur_cents']),
    dealId: readInt(json['deal_id']),
    deliveryRequestId: readInt(json['delivery_request_id']),
    paidAt: readDate(json['paid_at']),
    createdAt: readDate(json['created_at']),
    attempts: readObjectList(
      json['attempts'],
    ).map(PaymentAttempt.fromJson).toList(growable: false),
    refunds: readObjectList(
      json['refunds'],
    ).map(PaymentRefund.fromJson).toList(growable: false),
    providers: readObjectList(json['providers'])
        .map(ProviderOption.fromJson)
        .where((p) => p.provider != PaymentProviderId.mock)
        .toList(growable: false),
    chargilyQuote: ChargilyQuote.maybe(json['chargily_quote']),
    isReducedProjection: isReducedProjection,
  );

  final String publicReference;
  final PaymentPurpose purpose;
  final PaymentOrderStatus status;
  final String currency;

  final Money? amount;

  /// A posting deposit already paid and applied to this order. Rendered as a
  /// subtraction and labelled as already paid — never as another charge.
  final Money? depositCredit;

  final Money? paid;
  final Money? refunded;

  /// What is left to pay. Server-computed. The client never derives it.
  final Money? outstanding;

  final int? dealId;
  final int? deliveryRequestId;
  final DateTime? paidAt;
  final DateTime? createdAt;

  /// Newest first.
  final List<PaymentAttempt> attempts;

  final List<PaymentRefund> refunds;

  /// Only present while something is still owed.
  final List<ProviderOption> providers;

  final ChargilyQuote? chargilyQuote;

  /// True for the traveller's cut-down view of a Deal's balance order: status
  /// and outstanding only, no attempts and no payer detail.
  final bool isReducedProjection;

  PaymentAttempt? get latestAttempt => attempts.isEmpty ? null : attempts.first;

  /// A payment left the app and the server has not heard back yet. This — not
  /// a redirect's query string — is what a "confirming your payment" screen
  /// waits on.
  bool get isSettling =>
      !status.isSettled && (latestAttempt?.status.isInFlight ?? false);

  /// The last attempt died and nothing is in flight, so the user can start
  /// another one.
  bool get lastAttemptFailed =>
      !status.isSettled && (latestAttempt?.status.isDead ?? false);

  bool get hasOutstanding => outstanding != null && outstanding!.isPositive;

  bool get hasCredit => depositCredit != null && depositCredit!.isPositive;
}

/// `GET /api/parcels/<id>/posting-deposit`.
class PostingDepositState {
  const PostingDepositState({
    required this.timingMode,
    required this.depositRequired,
    required this.requestStatusRaw,
    this.quote,
    this.order,
  });

  factory PostingDepositState.fromJson(Map<String, dynamic> json) =>
      PostingDepositState(
        timingMode: readText(json['timing_mode']),
        depositRequired: readBool(json['deposit_required']),
        requestStatusRaw: readText(json['request_status']),
        quote: DepositQuote.maybe(json['quote']),
        order: readObject(json['order']) == null
            ? null
            : PaymentOrder.fromJson(readObject(json['order'])!),
      );

  final String timingMode;
  final bool depositRequired;
  final String requestStatusRaw;

  /// Present only before an order exists.
  final DepositQuote? quote;

  /// Present once an order exists.
  final PaymentOrder? order;

  bool get isPaid => order?.status.isSettled ?? false;
  bool get isAwaitingPayment =>
      depositRequired && (order?.hasOutstanding ?? quote != null);
}

class DepositQuote {
  const DepositQuote({
    required this.clamped,
    this.amount,
    this.percentBps,
    this.minimum,
    this.maximum,
    this.estimatedSenderTotal,
  });

  static DepositQuote? maybe(Object? raw) {
    final json = readObject(raw);
    if (json == null) return null;
    return DepositQuote(
      amount: Money.eurCentsOrNull(json['amount_eur_cents']),
      percentBps: readInt(json['percent_bps']),
      minimum: Money.eurCentsOrNull(json['min_eur_cents']),
      maximum: Money.eurCentsOrNull(json['max_eur_cents']),
      estimatedSenderTotal: Money.eurCentsOrNull(
        json['estimated_sender_total_eur_cents'],
      ),
      clamped: readText(json['clamped']),
    );
  }

  /// What to charge. Rendered as-is; the percentage is never applied locally.
  final Money? amount;

  final int? percentBps;
  final Money? minimum;
  final Money? maximum;
  final Money? estimatedSenderTotal;

  /// `""`, `"min"` or `"max"` — whether the amount hit a policy floor or cap.
  final String clamped;
}

/// `GET /api/deals/<id>/payment`.
class DealPaymentState {
  const DealPaymentState({
    required this.dealId,
    required this.dealStatusRaw,
    required this.currency,
    required this.viewerIsTraveler,
    this.senderTotal,
    this.travelerReward,
    this.platformFee,
    this.boostAmount,
    this.travelerBoostBonus,
    this.platformBoostRevenue,
    this.travelerTotal,
    this.platformTotal,
    this.senderTotalWithBoost,
    this.order,
  });

  factory DealPaymentState.fromJson(
    Map<String, dynamic> json, {
    required bool viewerIsTraveler,
  }) {
    final order = readObject(json['order']);
    return DealPaymentState(
      dealId: readInt(json['deal_id']) ?? 0,
      dealStatusRaw: readText(json['deal_status']),
      currency: readText(json['currency']).isEmpty
          ? 'EUR'
          : readText(json['currency']),
      senderTotal: Money.eurCentsOrNull(json['sender_total_eur_cents']),
      travelerReward: Money.eurCentsOrNull(json['traveler_reward_eur_cents']),
      platformFee: Money.eurCentsOrNull(json['platform_fee_eur_cents']),
      boostAmount: Money.eurCentsOrNull(json['boost_amount_eur_cents']),
      travelerBoostBonus: Money.eurCentsOrNull(
        json['traveler_boost_bonus_eur_cents'],
      ),
      platformBoostRevenue: Money.eurCentsOrNull(
        json['platform_boost_revenue_eur_cents'],
      ),
      travelerTotal: Money.eurCentsOrNull(json['traveler_total_eur_cents']),
      platformTotal: Money.eurCentsOrNull(json['platform_total_eur_cents']),
      senderTotalWithBoost: Money.eurCentsOrNull(
        json['sender_total_with_boost_eur_cents'],
      ),
      order: order == null
          ? null
          : PaymentOrder.fromJson(
              order,
              // The traveller's copy carries status and outstanding only.
              isReducedProjection: viewerIsTraveler,
            ),
      viewerIsTraveler: viewerIsTraveler,
    );
  }

  final int dealId;
  final String dealStatusRaw;
  final String currency;
  final Money? senderTotal;
  final Money? travelerReward;
  final Money? platformFee;
  final Money? boostAmount;
  final Money? travelerBoostBonus;
  final Money? platformBoostRevenue;
  final Money? travelerTotal;
  final Money? platformTotal;
  final Money? senderTotalWithBoost;
  final PaymentOrder? order;
  final bool viewerIsTraveler;

  bool get isFunded => order?.status.isSettled ?? false;
}

/// The anonymous view behind a guest payment link. Carries no counterparty
/// information at all — by design.
class GuestPaymentView {
  const GuestPaymentView({
    required this.description,
    required this.currency,
    required this.providers,
    this.amount,
    this.expiresAt,
  });

  factory GuestPaymentView.fromJson(Map<String, dynamic> json) =>
      GuestPaymentView(
        amount: Money.eurCentsOrNull(json['amount_eur_cents']),
        currency: readText(json['currency']).isEmpty
            ? 'EUR'
            : readText(json['currency']),
        description: readText(json['description']),
        expiresAt: readDate(json['expires_at']),
        providers: readObjectList(json['providers'])
            .map(ProviderOption.fromJson)
            .where((p) => p.provider != PaymentProviderId.mock)
            .toList(growable: false),
      );

  final Money? amount;
  final String currency;
  final String description;
  final DateTime? expiresAt;

  /// Already filtered server-side to rails that are usable right now.
  final List<ProviderOption> providers;
}

/// The link the sender shares. The raw token is returned exactly once.
class GuestPaymentLink {
  const GuestPaymentLink({
    required this.token,
    required this.currency,
    required this.communicationLanguage,
    this.amount,
    this.expiresAt,
  });

  factory GuestPaymentLink.fromJson(Map<String, dynamic> json) =>
      GuestPaymentLink(
        token: readText(json['token']),
        currency: readText(json['currency']).isEmpty
            ? 'EUR'
            : readText(json['currency']),
        amount: Money.eurCentsOrNull(json['amount_eur_cents']),
        expiresAt: readDate(json['expires_at']),
        communicationLanguage: CommunicationLanguage.parse(
          json['communication_language'],
        ),
      );

  /// Opaque bearer string. Never parsed, never logged, never persisted.
  final String token;

  final String currency;
  final Money? amount;
  final DateTime? expiresAt;

  /// What the server snapshotted onto the link. Echoed back so the issuer can
  /// see which language the payer's receipt will use; it is not re-sent and
  /// changing it later means reissuing the link.
  final CommunicationLanguage communicationLanguage;

  @override
  String toString() => 'GuestPaymentLink(redacted)';
}

/// The reduced checkout response on the anonymous guest path.
class GuestCheckout {
  const GuestCheckout({
    required this.checkoutUrl,
    required this.provider,
    required this.paymentCurrency,
    this.amount,
    this.expiresAt,
  });

  factory GuestCheckout.fromJson(Map<String, dynamic> json) => GuestCheckout(
    checkoutUrl: readText(json['checkout_url']),
    provider: readEnum(
      json['provider'],
      PaymentProviderId.values,
      fallback: PaymentProviderId.unknown,
    ),
    paymentCurrency: readText(json['payment_currency']),
    amount: Money.eurCentsOrNull(json['amount_eur_cents']),
    expiresAt: readDate(json['expires_at']),
  );

  final String checkoutUrl;
  final PaymentProviderId provider;
  final String paymentCurrency;
  final Money? amount;
  final DateTime? expiresAt;
}

class Payout {
  const Payout({
    required this.id,
    required this.status,
    required this.method,
    this.dealId,
    this.amount,
    this.eligibleAt,
    this.scheduledFor,
    this.payoutCurrency,
    this.payoutAmountLabel,
    this.reference,
    this.paidAt,
    this.createdAt,
  });

  factory Payout.fromJson(Map<String, dynamic> json) => Payout(
    id: readInt(json['id']) ?? 0,
    dealId: readInt(json['deal_id']),
    amount: Money.eurCentsOrNull(json['amount_eur_cents']),
    method: readEnum(
      json['method'],
      PayoutMethod.values,
      fallback: PayoutMethod.unknown,
    ),
    status: readEnum(
      json['status'],
      PayoutStatus.values,
      fallback: PayoutStatus.unknown,
    ),
    eligibleAt: readDate(json['eligible_at']),
    scheduledFor: readDate(json['scheduled_for']),
    payoutCurrency: readString(json['payout_currency']),
    payoutAmountLabel: readString(json['payout_amount']),
    reference: readString(json['reference']),
    paidAt: readDate(json['paid_at']),
    createdAt: readDate(json['created_at']),
  );

  final int id;
  final int? dealId;

  /// The traveller's canonical obligation, in EUR.
  final Money? amount;

  final PayoutMethod method;
  final PayoutStatus status;

  /// When the protection window closes and the money becomes releasable.
  final DateTime? eligibleAt;

  final DateTime? scheduledFor;

  /// The currency it was actually settled in, once settled.
  final String? payoutCurrency;

  /// The server's decimal-string rendering of the settled amount. Null until
  /// settlement.
  final String? payoutAmountLabel;

  final String? reference;
  final DateTime? paidAt;
  final DateTime? createdAt;
}
