/// J2 Authoritative Posting Pricing & Request Pricing domain models.
///
/// Under Phase J2, all monetary calculations (rewards, platform fees,
/// deposits, boosts, balances, and traveler payouts) are calculated
/// authoritatively on the backend. This file defines the read contracts
/// returned by `POST /api/parcels/pricing-quote` and `GET /api/parcels/<id>/pricing`.
library;

import '../core/money/money.dart';
import 'boost.dart';
import 'deal.dart';
import 'json.dart';

/// One economics breakdown block: traveler payout, platform fee, sender total.
class EconomicsBlock {
  const EconomicsBlock({
    required this.travelerReward,
    required this.platformFee,
    required this.senderTotal,
  });

  factory EconomicsBlock.fromJson(Map<String, dynamic> json) => EconomicsBlock(
    travelerReward: Money.eurCents(
      readInt(json['traveler_reward_minor']) ??
          readInt(json['traveler_reward_eur_cents']) ??
          0,
    ),
    platformFee: Money.eurCents(
      readInt(json['platform_fee_minor']) ??
          readInt(json['platform_fee_eur_cents']) ??
          0,
    ),
    senderTotal: Money.eurCents(
      readInt(json['sender_total_minor']) ??
          readInt(json['sender_total_eur_cents']) ??
          0,
    ),
  );

  final Money travelerReward;
  final Money platformFee;
  final Money senderTotal;
}

/// Deposit bounds and recommendation from pricing quote / request pricing.
class PostingDepositQuote {
  const PostingDepositQuote({
    required this.currency,
    required this.required,
    required this.recommendedDeposit,
    required this.minimumDeposit,
    this.maximumDeposit,
    this.chosenDeposit,
    required this.percentBps,
    required this.recommendationBasis,
    required this.isFlexible,
    this.orderStatus,
    this.paid,
    this.outstanding,
  });

  factory PostingDepositQuote.fromJson(Map<String, dynamic> json) {
    final currency = readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']);
    final rec =
        readInt(json['recommended_eur_cents']) ??
        readInt(json['rec_eur_cents']) ??
        300;
    final min =
        readInt(json['minimum_eur_cents']) ??
        readInt(json['min_eur_cents']) ??
        readInt(json['chosen_min_eur_cents']) ??
        300;
    // `maximum_eur_cents` is the obligation ceiling. `max_eur_cents` is only
    // the upper clamp on the *recommendation*; reading it as a ceiling would
    // cap a sender's deposit at a number that is not a limit (J6.3).
    final maxCents = readInt(json['maximum_eur_cents']);
    final chosenCents = readInt(json['chosen_eur_cents']);
    final paidCents = readInt(json['paid_eur_cents']);
    final outstandingCents = readInt(json['outstanding_eur_cents']);

    return PostingDepositQuote(
      currency: currency,
      required: readBool(json['required']),
      recommendedDeposit: Money.eurCents(rec),
      minimumDeposit: Money.eurCents(min),
      maximumDeposit: maxCents != null ? Money.eurCents(maxCents) : null,
      chosenDeposit: chosenCents != null ? Money.eurCents(chosenCents) : null,
      percentBps: readInt(json['percent_bps']) ?? 1000,
      recommendationBasis: Money.eurCents(
        readInt(json['recommendation_basis_eur_cents']) ?? 0,
      ),
      isFlexible: readBool(json['is_flexible']),
      orderStatus: readText(json['order_status']),
      paid: paidCents != null ? Money.eurCents(paidCents) : null,
      outstanding: outstandingCents != null
          ? Money.eurCents(outstandingCents)
          : null,
    );
  }

  final String currency;
  final bool required;
  final Money recommendedDeposit;
  final Money minimumDeposit;
  final Money? maximumDeposit;
  final Money? chosenDeposit;
  final int percentBps;
  final Money recommendationBasis;
  final bool isFlexible;
  final String? orderStatus;
  final Money? paid;
  final Money? outstanding;
}

/// Boost pricing block from pricing quote / request pricing.
///
/// Describes the Boost on its own. The sender's whole obligation, Boost
/// included, is [ChosenTerms.senderTotalWithBoost] — never a sum of this block
/// and the base economics.
class PricingBoostQuote {
  const PricingBoostQuote({
    required this.amount,
    required this.commissionFee,
    required this.senderCost,
    required this.travelerBonus,
    this.baseReward,
    this.totalOfferedReward,
    this.policy,
  });

  factory PricingBoostQuote.fromJson(Map<String, dynamic> json) {
    final policyRaw = readObject(json['policy']);
    final baseCents = readInt(json['base_reward_eur_cents']);
    final totalCents = readInt(json['total_offered_reward_eur_cents']);
    return PricingBoostQuote(
      amount: Money.eurCents(readInt(json['boost_eur_cents']) ?? 0),
      commissionFee: Money.eurCents(
        readInt(json['boost_platform_fee_eur_cents']) ?? 0,
      ),
      senderCost: Money.eurCents(
        readInt(json['boost_sender_cost_eur_cents']) ?? 0,
      ),
      travelerBonus: Money.eurCents(
        readInt(json['boost_traveler_bonus_eur_cents']) ?? 0,
      ),
      // Absent until a reward is chosen. Null, not €0.00.
      baseReward: baseCents != null ? Money.eurCents(baseCents) : null,
      totalOfferedReward: totalCents != null
          ? Money.eurCents(totalCents)
          : null,
      policy: policyRaw != null ? BoostPolicy.fromJson(policyRaw) : null,
    );
  }

  final Money amount;
  final Money commissionFee;
  final Money senderCost;
  final Money travelerBonus;
  final Money? baseReward;
  final Money? totalOfferedReward;
  final BoostPolicy? policy;
}

/// J6.3 — what committing the chosen reward with the current Boost would
/// freeze, published by the server as `chosen_terms`.
///
/// The same field names and meanings as an Offer (J6.1) and a Deal's terms,
/// parsed through [DealTerms] so the three cannot drift. Every figure is the
/// server's; nothing here adds a Boost to anything.
class ChosenTerms {
  const ChosenTerms({required this.status, this.terms});

  static const provisional = 'provisional';
  static const frozen = 'frozen';
  static const unavailable = 'unavailable';

  factory ChosenTerms.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const ChosenTerms(status: unavailable);
    final status = readText(json['terms_status']);
    return ChosenTerms(
      status: status.isEmpty ? unavailable : status,
      terms: DealTerms.maybe(json),
    );
  }

  final String status;
  final DealTerms? terms;

  /// Base reward. Same meaning as `traveler_reward_minor` everywhere.
  Money? get baseReward => terms?.travelerReward;
  Money? get platformFee => terms?.platformFee;

  /// Base reward + base fee. Not the whole obligation when a Boost is set.
  Money? get baseSenderTotal => terms?.senderTotal;
  Money? get boostAmount => terms?.boostAmount;
  Money? get boostFee => terms?.boostPlatformFee;
  Money? get travelerTotal => terms?.travelerTotal;
  Money? get senderTotalWithBoost => terms?.senderTotalWithBoost;

  /// True only when both totals are published. A screen that cannot show
  /// both shows neither, rather than a base total posing as the whole.
  bool get hasTotals =>
      status != unavailable &&
      travelerTotal != null &&
      senderTotalWithBoost != null;

  bool get hasBoost => boostAmount?.isPositive ?? false;
}

/// Permitted actions determined authoritatively by the backend.
class PricingActions {
  const PricingActions({
    required this.canEditBoost,
    required this.canChooseDeposit,
    required this.canCancel,
  });

  factory PricingActions.fromJson(Map<String, dynamic> json) => PricingActions(
    canEditBoost: readBool(json['can_edit_boost']),
    canChooseDeposit: readBool(json['can_choose_deposit']),
    canCancel: readBool(json['can_cancel']),
  );

  final bool canEditBoost;
  final bool canChooseDeposit;
  final bool canCancel;
}

/// The response from `POST /api/parcels/pricing-quote`.
class PostingPricingQuote {
  const PostingPricingQuote({
    required this.currency,
    required this.minimumReward,
    required this.recommendedReward,
    this.chosenReward,
    required this.minimumEconomics,
    required this.recommendedEconomics,
    this.chosenEconomics,
    required this.chosenIsBelowMinimum,
    required this.chosenIsBelowRecommended,
    required this.deposit,
    required this.boost,
    this.chosenTerms = const ChosenTerms(status: ChosenTerms.unavailable),
    required this.commissionRateBps,
    required this.pricingVersion,
  });

  factory PostingPricingQuote.fromJson(Map<String, dynamic> json) {
    final currency = readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']);
    final minReward = Money.eurCents(
      readInt(json['minimum_reward_eur_cents']) ?? 0,
    );
    final recReward = Money.eurCents(
      readInt(json['recommended_reward_eur_cents']) ?? 0,
    );
    final chosenRewardCents = readInt(json['chosen_reward_eur_cents']);
    final chosenReward = chosenRewardCents != null
        ? Money.eurCents(chosenRewardCents)
        : null;

    final minEcon = EconomicsBlock.fromJson(
      readObject(json['minimum_economics']) ?? const {},
    );
    final recEcon = EconomicsBlock.fromJson(
      readObject(json['recommended_economics']) ?? const {},
    );
    final chosenEconRaw = readObject(json['chosen_economics']);
    final chosenEcon = chosenEconRaw != null
        ? EconomicsBlock.fromJson(chosenEconRaw)
        : null;

    return PostingPricingQuote(
      currency: currency,
      minimumReward: minReward,
      recommendedReward: recReward,
      chosenReward: chosenReward,
      minimumEconomics: minEcon,
      recommendedEconomics: recEcon,
      chosenEconomics: chosenEcon,
      chosenIsBelowMinimum: readBool(json['chosen_is_below_minimum']),
      chosenIsBelowRecommended: readBool(json['chosen_is_below_recommended']),
      deposit: PostingDepositQuote.fromJson(
        readObject(json['deposit']) ?? const {},
      ),
      boost: PricingBoostQuote.fromJson(readObject(json['boost']) ?? const {}),
      chosenTerms: ChosenTerms.fromJson(readObject(json['chosen_terms'])),
      commissionRateBps: readInt(json['commission_rate_bps']) ?? 0,
      pricingVersion: readText(json['pricing_version']),
    );
  }

  final String currency;
  final Money minimumReward;
  final Money recommendedReward;
  final Money? chosenReward;
  final EconomicsBlock minimumEconomics;
  final EconomicsBlock recommendedEconomics;
  final EconomicsBlock? chosenEconomics;
  final bool chosenIsBelowMinimum;
  final bool chosenIsBelowRecommended;
  final PostingDepositQuote deposit;
  final PricingBoostQuote boost;

  /// The Boost-inclusive totals. Read these for "Traveler receives" and "You
  /// pay"; [chosenEconomics] is base-only.
  final ChosenTerms chosenTerms;
  final int commissionRateBps;
  final String pricingVersion;
}

/// The response from `GET /api/parcels/<id>/pricing`.
class RequestPricing {
  const RequestPricing({
    required this.deliveryRequestId,
    required this.requestStatus,
    required this.currency,
    required this.minimumReward,
    required this.recommendedReward,
    this.chosenReward,
    required this.minimumEconomics,
    required this.recommendedEconomics,
    this.chosenEconomics,
    required this.chosenIsBelowMinimum,
    required this.chosenIsBelowRecommended,
    required this.deposit,
    required this.boost,
    this.chosenTerms = const ChosenTerms(status: ChosenTerms.unavailable),
    required this.actions,
  });

  factory RequestPricing.fromJson(Map<String, dynamic> json) {
    final currency = readText(json['currency']).isEmpty
        ? 'EUR'
        : readText(json['currency']);
    final minReward = Money.eurCents(
      readInt(json['minimum_reward_eur_cents']) ?? 0,
    );
    final recReward = Money.eurCents(
      readInt(json['recommended_reward_eur_cents']) ?? 0,
    );
    final chosenRewardCents = readInt(json['chosen_reward_eur_cents']);
    final chosenReward = chosenRewardCents != null
        ? Money.eurCents(chosenRewardCents)
        : null;

    final minEcon = EconomicsBlock.fromJson(
      readObject(json['minimum_economics']) ?? const {},
    );
    final recEcon = EconomicsBlock.fromJson(
      readObject(json['recommended_economics']) ?? const {},
    );
    final chosenEconRaw = readObject(json['chosen_economics']);
    final chosenEcon = chosenEconRaw != null
        ? EconomicsBlock.fromJson(chosenEconRaw)
        : null;

    return RequestPricing(
      deliveryRequestId: readInt(json['delivery_request_id']) ?? 0,
      requestStatus: readText(json['request_status']),
      currency: currency,
      minimumReward: minReward,
      recommendedReward: recReward,
      chosenReward: chosenReward,
      minimumEconomics: minEcon,
      recommendedEconomics: recEcon,
      chosenEconomics: chosenEcon,
      chosenIsBelowMinimum: readBool(json['chosen_is_below_minimum']),
      chosenIsBelowRecommended: readBool(json['chosen_is_below_recommended']),
      deposit: PostingDepositQuote.fromJson(
        readObject(json['deposit']) ?? const {},
      ),
      boost: PricingBoostQuote.fromJson(readObject(json['boost']) ?? const {}),
      chosenTerms: ChosenTerms.fromJson(readObject(json['chosen_terms'])),
      actions: PricingActions.fromJson(readObject(json['actions']) ?? const {}),
    );
  }

  final int deliveryRequestId;
  final String requestStatus;
  final String currency;
  final Money minimumReward;
  final Money recommendedReward;
  final Money? chosenReward;
  final EconomicsBlock minimumEconomics;
  final EconomicsBlock recommendedEconomics;
  final EconomicsBlock? chosenEconomics;
  final bool chosenIsBelowMinimum;
  final bool chosenIsBelowRecommended;
  final PostingDepositQuote deposit;
  final PricingBoostQuote boost;

  /// The Boost-inclusive totals. Read these for "Traveler receives" and "You
  /// pay"; [chosenEconomics] is base-only.
  final ChosenTerms chosenTerms;
  final PricingActions actions;
}
