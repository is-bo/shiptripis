/// The machine-readable error vocabulary, taken verbatim from the backend.
///
/// Deliberately **not** a Dart `enum`. An enum over 145 server-defined strings
/// would have to be regenerated every time the backend adds one, and an
/// unrecognised value would either crash the parse or need a sentinel member
/// anyway. A value class keeps the raw string, compares as cheaply as an enum,
/// and lets a `switch` cover only the codes a given screen actually reacts to
/// while everything else falls through to a generic recovery.
///
/// Screens branch on these constants. Screens never branch on English text —
/// `serverDetail` is for logs, not for `if`.
library;

import 'package:flutter/foundation.dart';

@immutable
class ApiErrorCode {
  const ApiErrorCode(this.raw);

  /// The wire string, or `''` when the response carried no `code` at all.
  final String raw;

  static const unknown = ApiErrorCode('');

  bool get isKnownToServer => raw.isNotEmpty;

  static ApiErrorCode parse(String? raw) =>
      (raw == null || raw.isEmpty) ? unknown : ApiErrorCode(raw);

  // ---------------------------------------------------------------------------
  // Authorization
  // ---------------------------------------------------------------------------
  static const notAuthorized = ApiErrorCode('not_authorized');

  // ---------------------------------------------------------------------------
  // Retired V1 surfaces. Reaching one of these means the client called
  // something that no longer exists — a bug in the app, not a user problem.
  // ---------------------------------------------------------------------------
  static const legacyDeliveryFlowRetired = ApiErrorCode(
    'legacy_delivery_flow_retired',
  );
  static const legacyDzdQuoteRetired = ApiErrorCode('legacy_dzd_quote_retired');
  static const legacyMatchingFlowRetired = ApiErrorCode(
    'legacy_matching_flow_retired',
  );
  static const legacyPaymentRetired = ApiErrorCode('legacy_payment_retired');
  static const legacyTripFlowRetired = ApiErrorCode('legacy_trip_flow_retired');
  static const legacyTripSearchRetired = ApiErrorCode(
    'legacy_trip_search_retired',
  );
  static const legacyContractNotSupported = ApiErrorCode(
    'legacy_contract_not_supported',
  );
  static const productRequestRetired = ApiErrorCode('product_request_retired');
  static const airportFilterRetired = ApiErrorCode('airport_filter_retired');

  // ---------------------------------------------------------------------------
  // Request / journey lifecycle
  // ---------------------------------------------------------------------------
  static const requestNotOpen = ApiErrorCode('request_not_open');
  static const requestAlreadyMatched = ApiErrorCode('request_already_matched');
  static const requestNotDepositable = ApiErrorCode('request_not_depositable');
  static const requestWeightInvalid = ApiErrorCode('request_weight_invalid');
  static const parcelNotCancellable = ApiErrorCode('parcel_not_cancellable');
  static const parcelPhotoMissing = ApiErrorCode('parcel_photo_missing');
  static const parcelPhotoTooLarge = ApiErrorCode('parcel_photo_too_large');
  static const parcelPhotoMediaTypeUnsupported = ApiErrorCode(
    'parcel_photo_media_type_unsupported',
  );
  static const parcelPhotoStorageUnavailable = ApiErrorCode(
    'parcel_photo_storage_unavailable',
  );
  static const parcelItemPhotoUnavailable = ApiErrorCode(
    'parcel_item_photo_unavailable',
  );
  static const parcelCancellationForbidden = ApiErrorCode(
    'parcel_cancellation_forbidden',
  );
  static const parcelCancellationFailed = ApiErrorCode(
    'parcel_cancellation_failed',
  );
  static const journeyNotActive = ApiErrorCode('journey_not_active');
  static const journeyNotOwned = ApiErrorCode('journey_not_owned');
  static const journeyProofUploadClosed = ApiErrorCode(
    'journey_proof_upload_closed',
  );
  static const proofOnlyForFlight = ApiErrorCode('proof_only_for_flight');
  static const proofFileMissing = ApiErrorCode('proof_file_missing');
  static const proofFileTooLarge = ApiErrorCode('proof_file_too_large');
  static const proofMediaTypeUnsupported = ApiErrorCode(
    'proof_media_type_unsupported',
  );
  static const proofKindUnknown = ApiErrorCode('proof_kind_unknown');
  static const proofStorageUnavailable = ApiErrorCode(
    'proof_storage_unavailable',
  );
  static const journeyNotEditable = ApiErrorCode('journey_not_editable');
  static const journeyHasDependentState = ApiErrorCode(
    'journey_has_dependent_state',
  );
  static const journeyLegNotFound = ApiErrorCode('journey_leg_not_found');
  static const journeyLegModeUnavailable = ApiErrorCode(
    'journey_leg_mode_unavailable',
  );
  static const flightProofNotApproved = ApiErrorCode(
    'flight_proof_not_approved',
  );

  // ---------------------------------------------------------------------------
  // Matching, capacity and negotiation
  // ---------------------------------------------------------------------------
  static const capacityExceeded = ApiErrorCode('capacity_exceeded');
  static const incompatibleCandidate = ApiErrorCode('incompatible_candidate');
  static const candidateNotFound = ApiErrorCode('candidate_not_found');
  static const invalidLegRange = ApiErrorCode('invalid_leg_range');
  static const matchNotPending = ApiErrorCode('match_not_pending');
  static const matchLegRangeMissing = ApiErrorCode('match_leg_range_missing');
  static const offerNotPending = ApiErrorCode('offer_not_pending');
  static const offerEconomicsMissing = ApiErrorCode('offer_economics_missing');

  /// J6.1. The offer's Boost-inclusive totals moved after the user read them,
  /// or a Boost is included and no total was confirmed. Nothing committed.
  static const offerEconomicsChanged = ApiErrorCode('offer_economics_changed');
  static const offerEconomicsConfirmationRequired = ApiErrorCode(
    'offer_economics_confirmation_required',
  );
  static const rewardBelowMinimum = ApiErrorCode('reward_below_minimum');
  static const routeInputsChanged = ApiErrorCode('route_inputs_changed');
  static const routePreflightMissing = ApiErrorCode('route_preflight_missing');
  static const routeProviderUnavailable = ApiErrorCode(
    'route_provider_unavailable',
  );
  static const routeProviderError = ApiErrorCode('route_provider_error');
  static const invalidReservationGrace = ApiErrorCode(
    'invalid_reservation_grace',
  );
  static const constraintConflict = ApiErrorCode('constraint_conflict');

  // ---------------------------------------------------------------------------
  // Deal lifecycle
  // ---------------------------------------------------------------------------
  static const dealNotFunded = ApiErrorCode('deal_not_funded');
  static const dealNotPickupReady = ApiErrorCode('deal_not_pickup_ready');
  static const dealNotInTransit = ApiErrorCode('deal_not_in_transit');
  static const dealNotInCarriage = ApiErrorCode('deal_not_in_carriage');
  static const dealNotDeliveryReady = ApiErrorCode('deal_not_delivery_ready');
  static const dealNotCancellable = ApiErrorCode('deal_not_cancellable');
  static const dealClosed = ApiErrorCode('deal_closed');
  static const dealTermsMissing = ApiErrorCode('deal_terms_missing');
  static const dealCancellationNotAvailable = ApiErrorCode(
    'deal_cancellation_not_available',
  );
  static const cancellationNotAvailableAfterPickup = ApiErrorCode(
    'cancellation_not_available_after_pickup',
  );
  static const recipientNotSet = ApiErrorCode('recipient_not_set');

  // ---------------------------------------------------------------------------
  // Handover
  // ---------------------------------------------------------------------------
  static const handoverCodeInvalid = ApiErrorCode('handover_code_invalid');
  static const handoverCodeLocked = ApiErrorCode('handover_code_locked');
  static const handoverRateLimited = ApiErrorCode('handover_rate_limited');
  static const handoverSealInvalid = ApiErrorCode('handover_seal_invalid');
  static const codeNotAvailable = ApiErrorCode('code_not_available');
  static const deliveryCodeBufferOpen = ApiErrorCode(
    'delivery_code_buffer_open',
  );
  static const deliveryCodeNotArmed = ApiErrorCode('delivery_code_not_armed');
  static const pickupAlreadyConfirmed = ApiErrorCode(
    'pickup_already_confirmed',
  );
  static const pickupNotConfirmed = ApiErrorCode('pickup_not_confirmed');
  static const deliveryAlreadyConfirmed = ApiErrorCode(
    'delivery_already_confirmed',
  );
  static const deliveryNotConfirmed = ApiErrorCode('delivery_not_confirmed');

  // ---------------------------------------------------------------------------
  // Payments
  // ---------------------------------------------------------------------------
  static const providerUnavailable = ApiErrorCode('provider_unavailable');
  static const providerDisabled = ApiErrorCode('provider_disabled');
  static const providerNotConfigured = ApiErrorCode('provider_not_configured');
  static const providerNewCheckoutsDisabled = ApiErrorCode(
    'provider_new_checkouts_disabled',
  );

  /// Credentials exist but describe an environment the server will not
  /// transact in — a rail switched on before its configuration agreed with
  /// itself. Distinct from "not configured": the fix is an operator's, not the
  /// payer's, and no amount of retrying changes it.
  static const providerConfigurationInvalid = ApiErrorCode(
    'provider_configuration_invalid',
  );

  /// The provider understood the request and refused to open a checkout.
  /// Definite, so the copy must not promise that trying again will work.
  static const providerCheckoutFailed = ApiErrorCode(
    'provider_checkout_failed',
  );
  static const clientSuppliedAmountRejected = ApiErrorCode(
    'client_supplied_amount_rejected',
  );
  static const nothingOutstanding = ApiErrorCode('nothing_outstanding');
  static const orderNotCollectable = ApiErrorCode('order_not_collectable');
  static const dealBalanceOrderMissing = ApiErrorCode(
    'deal_balance_order_missing',
  );
  static const depositNotRequired = ApiErrorCode('deposit_not_required');
  static const guestLinkInvalid = ApiErrorCode('guest_link_invalid');

  /// Someone is paying with the sender's live guest link right now, so it can
  /// be neither replaced nor revoked until their checkout ends.
  static const guestCheckoutInProgress = ApiErrorCode(
    'guest_checkout_in_progress',
  );
  static const v1DealPaymentNotAvailable = ApiErrorCode(
    'v1_deal_payment_not_available',
  );
  static const refundNotPermitted = ApiErrorCode('refund_not_permitted');
  static const invalidMoney = ApiErrorCode('invalid_money');
  static const payoutProfileInvalid = ApiErrorCode('payout_profile_invalid');
  static const payoutCountryUnsupported = ApiErrorCode(
    'payout_country_unsupported',
  );
  static const stripeConnectUnavailable = ApiErrorCode(
    'stripe_connect_unavailable',
  );
  static const stripeConnectProviderError = ApiErrorCode(
    'stripe_connect_provider_error',
  );
  static const payoutSetupInvalid = ApiErrorCode('payout_setup_invalid');
  static const payoutEvidenceUnavailable = ApiErrorCode(
    'payout_evidence_unavailable',
  );

  // ---------------------------------------------------------------------------
  // Disputes
  // ---------------------------------------------------------------------------
  static const disputeNotAvailable = ApiErrorCode('dispute_not_available');
  static const disputeNotActive = ApiErrorCode('dispute_not_active');
  static const disputeNotFound = ApiErrorCode('dispute_not_found');
  static const disputeWindowClosed = ApiErrorCode('dispute_window_closed');
  static const disputeAlreadyResolved = ApiErrorCode(
    'dispute_already_resolved',
  );
  static const disputeAlreadyFinished = ApiErrorCode(
    'dispute_already_finished',
  );
  static const disputeReasonRequired = ApiErrorCode('dispute_reason_required');
  static const disputeCategoryInvalid = ApiErrorCode(
    'dispute_category_invalid',
  );
  static const disputeEvidenceLimitReached = ApiErrorCode(
    'dispute_evidence_limit_reached',
  );
  static const disputeEvidenceTooLarge = ApiErrorCode(
    'dispute_evidence_too_large',
  );
  static const disputeEvidenceTypeNotAllowed = ApiErrorCode(
    'dispute_evidence_type_not_allowed',
  );
  static const disputeEvidenceTypeMismatch = ApiErrorCode(
    'dispute_evidence_type_mismatch',
  );
  static const disputeEvidenceContentMismatch = ApiErrorCode(
    'dispute_evidence_content_mismatch',
  );
  static const disputeEvidenceFileRequired = ApiErrorCode(
    'dispute_evidence_file_required',
  );
  static const disputeEvidenceTextRequired = ApiErrorCode(
    'dispute_evidence_text_required',
  );
  static const disputeEvidenceKindInvalid = ApiErrorCode(
    'dispute_evidence_kind_invalid',
  );

  // ---------------------------------------------------------------------------
  // Ratings and boosts
  // ---------------------------------------------------------------------------
  static const ratingAlreadySubmitted = ApiErrorCode(
    'rating_already_submitted',
  );
  static const ratingNotAvailable = ApiErrorCode('rating_not_available');
  static const ratingWindowClosed = ApiErrorCode('rating_window_closed');
  static const ratingScoreInvalid = ApiErrorCode('rating_score_invalid');
  static const ratingTagInvalid = ApiErrorCode('rating_tag_invalid');
  static const boostDisabled = ApiErrorCode('boost_disabled');
  static const boostLimitReached = ApiErrorCode('boost_limit_reached');
  static const boostPackageUnknown = ApiErrorCode('boost_package_unknown');
  static const boostRequestExpired = ApiErrorCode('boost_request_expired');
  static const boostRequestNotActive = ApiErrorCode('boost_request_not_active');
  static const boostRequestNotEligible = ApiErrorCode(
    'boost_request_not_eligible',
  );

  // ---------------------------------------------------------------------------
  // Platform
  // ---------------------------------------------------------------------------
  static const businessSettingsUnavailable = ApiErrorCode(
    'business_settings_unavailable',
  );
  static const phase4PolicyUnavailable = ApiErrorCode(
    'phase4_policy_unavailable',
  );
  static const invalidPaymentPolicy = ApiErrorCode('invalid_payment_policy');
  static const invalidPhase2Policy = ApiErrorCode('invalid_phase2_policy');
  static const internalError = ApiErrorCode('internal_error');

  // ---------------------------------------------------------------------------
  // Classification
  // ---------------------------------------------------------------------------

  /// Codes that mean the screen is showing a world that no longer exists.
  ///
  /// The recovery for every one of these is the same shape: say plainly what
  /// changed, re-fetch authoritative state, and offer whatever action is still
  /// valid. Never a dead-end alert.
  static const _staleStateCodes = <String>{
    'request_not_open',
    'request_already_matched',
    'journey_not_active',
    'offer_not_pending',
    'offer_economics_changed',
    'offer_economics_confirmation_required',
    'match_not_pending',
    'capacity_exceeded',
    'flight_proof_not_approved',
    'reward_below_minimum',
    'route_inputs_changed',
    'route_preflight_missing',
    'incompatible_candidate',
    'deal_not_funded',
    'deal_not_pickup_ready',
    'deal_not_in_transit',
    'deal_not_in_carriage',
    'deal_not_delivery_ready',
    'deal_not_cancellable',
    'deal_closed',
    'pickup_already_confirmed',
    'pickup_not_confirmed',
    'delivery_already_confirmed',
    'delivery_not_confirmed',
    'delivery_code_buffer_open',
    'delivery_code_not_armed',
    'code_not_available',
    'recipient_not_set',
    'nothing_outstanding',
    'order_not_collectable',
    'dispute_window_closed',
    'dispute_already_resolved',
    'dispute_already_finished',
    'dispute_not_active',
    'rating_already_submitted',
    'rating_window_closed',
    'rating_not_available',
    'boost_request_expired',
    'boost_request_not_active',
    'boost_request_not_eligible',
    'cancellation_not_available_after_pickup',
    'deal_cancellation_not_available',
    'parcel_not_cancellable',
    'guest_link_invalid',
  };

  bool get impliesStaleClientState => _staleStateCodes.contains(raw);

  /// Codes that mean the *client* called something that no longer exists.
  /// These are never the user's fault and must never be shown as though they
  /// were; they are a release bug and should be reported, not retried.
  static const _retiredCodes = <String>{
    'legacy_delivery_flow_retired',
    'legacy_dzd_quote_retired',
    'legacy_matching_flow_retired',
    'legacy_payment_retired',
    'legacy_trip_flow_retired',
    'legacy_trip_search_retired',
    'legacy_contract_not_supported',
    'product_request_retired',
    'airport_filter_retired',
  };

  bool get isRetiredSurface => _retiredCodes.contains(raw);

  /// Codes about a payment provider being unusable right now. The recovery is
  /// to offer the other provider, or to explain that payment is temporarily
  /// unavailable — never to retry the same rail in a loop.
  static const _providerCodes = <String>{
    'provider_unavailable',
    'provider_disabled',
    'provider_not_configured',
    'provider_new_checkouts_disabled',
    'provider_configuration_invalid',
  };

  bool get isProviderUnavailable => _providerCodes.contains(raw);

  @override
  bool operator ==(Object other) => other is ApiErrorCode && other.raw == raw;

  @override
  int get hashCode => raw.hashCode;

  @override
  String toString() => raw.isEmpty ? '<no code>' : raw;
}
