/// One place where a server status becomes a word, a tone and an icon.
///
/// Two reasons this is centralised rather than switched on per screen:
///
/// 1. **Consistency.** A deal that reads "Waiting for payment" on the home
///    screen and "Payment required" in Deliveries teaches the user that those
///    are two different things. They are not.
///
/// 2. **Tone discipline.** The tone vocabulary is deliberately small — is the
///    platform working, is it *you*, is it them, did it end well, did it end
///    badly. Deciding that per screen produces six shades of amber and no
///    meaning. Deciding it here means a user learns the colour language once.
///
/// Every mapping is exhaustive over the enum, including `unknown`, which
/// renders as a neutral, honest "we do not recognise this state" rather than
/// being silently folded into a state it is not.
library;

import 'package:flutter/material.dart';

import '../../design/components/status.dart';
import '../../domain/deal.dart';
import '../../domain/delivery_request.dart';
import '../../domain/dispute.dart';
import '../../domain/journey.dart';
import '../../domain/offer.dart';
import '../../domain/payment.dart';
import '../../l10n/app_localizations.dart';

@immutable
class StatusCopy {
  const StatusCopy({
    required this.label,
    required this.tone,
    required this.icon,
  });

  final String label;
  final StatusTone tone;
  final IconData icon;
}

/// A deal's status, from the point of view of a specific party.
///
/// The viewer matters: `payment_required` is an instruction to the sender and
/// a wait for the traveller, and telling both of them the same thing would
/// leave one of them either idle or anxious.
StatusCopy dealStatusCopy(
  BuildContext context,
  DealStatus status, {
  required bool viewerIsSender,
}) {
  final l = L.of(context);
  return switch (status) {
    DealStatus.offerAccepted => StatusCopy(
      label: l.dealStatusOfferAccepted,
      tone: StatusTone.progress,
      icon: Icons.handshake_rounded,
    ),
    DealStatus.paymentRequired => StatusCopy(
      label: l.dealStatusPaymentRequired,
      tone: viewerIsSender ? StatusTone.action : StatusTone.waiting,
      icon: Icons.credit_card_rounded,
    ),
    DealStatus.paymentFailed => StatusCopy(
      label: l.dealStatusPaymentFailed,
      tone: StatusTone.bad,
      icon: Icons.credit_card_off_rounded,
    ),
    DealStatus.funded => StatusCopy(
      label: l.dealStatusFunded,
      tone: StatusTone.progress,
      icon: Icons.verified_rounded,
    ),
    DealStatus.pickupReady => StatusCopy(
      label: l.dealStatusPickupReady,
      tone: StatusTone.action,
      icon: Icons.inventory_rounded,
    ),
    DealStatus.pickedUp => StatusCopy(
      label: l.dealStatusPickedUp,
      tone: StatusTone.progress,
      icon: Icons.local_shipping_rounded,
    ),
    DealStatus.inTransit => StatusCopy(
      label: l.dealStatusInTransit,
      tone: StatusTone.progress,
      icon: Icons.local_shipping_rounded,
    ),
    DealStatus.deliveryReady => StatusCopy(
      label: l.dealStatusDeliveryReady,
      tone: StatusTone.action,
      icon: Icons.where_to_vote_rounded,
    ),
    DealStatus.deliveryConfirmed => StatusCopy(
      label: l.dealStatusDeliveryConfirmed,
      tone: StatusTone.good,
      icon: Icons.check_circle_rounded,
    ),
    DealStatus.protectionWindow => StatusCopy(
      label: l.dealStatusProtection,
      tone: StatusTone.waiting,
      icon: Icons.shield_rounded,
    ),
    DealStatus.completed => StatusCopy(
      label: l.dealStatusCompleted,
      tone: StatusTone.good,
      icon: Icons.task_alt_rounded,
    ),
    DealStatus.disputed => StatusCopy(
      label: l.dealStatusDisputed,
      tone: StatusTone.bad,
      icon: Icons.gavel_rounded,
    ),
    DealStatus.cancelled => StatusCopy(
      label: l.dealStatusCancelled,
      tone: StatusTone.neutral,
      icon: Icons.cancel_rounded,
    ),
    DealStatus.expired => StatusCopy(
      label: l.dealStatusExpired,
      tone: StatusTone.neutral,
      icon: Icons.timer_off_rounded,
    ),
    DealStatus.refunded => StatusCopy(
      label: l.dealStatusRefunded,
      tone: StatusTone.neutral,
      icon: Icons.undo_rounded,
    ),
    DealStatus.partiallyRefunded => StatusCopy(
      label: l.dealStatusPartiallyRefunded,
      tone: StatusTone.neutral,
      icon: Icons.undo_rounded,
    ),
    DealStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

StatusCopy requestStatusCopy(BuildContext context, RequestStatus status) {
  final l = L.of(context);
  return switch (status) {
    RequestStatus.awaitingDeposit => StatusCopy(
      label: l.requestStatusAwaitingDeposit,
      tone: StatusTone.action,
      icon: Icons.account_balance_wallet_rounded,
    ),
    RequestStatus.open => StatusCopy(
      label: l.requestStatusOpen,
      tone: StatusTone.progress,
      icon: Icons.travel_explore_rounded,
    ),
    RequestStatus.matched => StatusCopy(
      label: l.requestStatusMatched,
      tone: StatusTone.progress,
      icon: Icons.handshake_rounded,
    ),
    RequestStatus.inTransit => StatusCopy(
      label: l.requestStatusInTransit,
      tone: StatusTone.progress,
      icon: Icons.local_shipping_rounded,
    ),
    RequestStatus.delivered => StatusCopy(
      label: l.requestStatusDelivered,
      tone: StatusTone.good,
      icon: Icons.check_circle_rounded,
    ),
    RequestStatus.completed => StatusCopy(
      label: l.requestStatusCompleted,
      tone: StatusTone.good,
      icon: Icons.task_alt_rounded,
    ),
    RequestStatus.cancelled => StatusCopy(
      label: l.requestStatusCancelled,
      tone: StatusTone.neutral,
      icon: Icons.cancel_rounded,
    ),
    RequestStatus.expired => StatusCopy(
      label: l.requestStatusExpired,
      tone: StatusTone.neutral,
      icon: Icons.timer_off_rounded,
    ),
    RequestStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

StatusCopy journeyStatusCopy(BuildContext context, JourneyStatus status) {
  final l = L.of(context);
  return switch (status) {
    JourneyStatus.draft => StatusCopy(
      label: l.journeyStatusDraft,
      tone: StatusTone.neutral,
      icon: Icons.edit_note_rounded,
    ),
    JourneyStatus.pendingVerification => StatusCopy(
      label: l.journeyStatusPendingVerification,
      tone: StatusTone.waiting,
      icon: Icons.pending_rounded,
    ),
    JourneyStatus.active => StatusCopy(
      label: l.journeyStatusActive,
      tone: StatusTone.progress,
      icon: Icons.public_rounded,
    ),
    JourneyStatus.inProgress => StatusCopy(
      label: l.journeyStatusInProgress,
      tone: StatusTone.progress,
      icon: Icons.flight_takeoff_rounded,
    ),
    JourneyStatus.completed => StatusCopy(
      label: l.journeyStatusCompleted,
      tone: StatusTone.good,
      icon: Icons.task_alt_rounded,
    ),
    JourneyStatus.cancelled => StatusCopy(
      label: l.journeyStatusCancelled,
      tone: StatusTone.neutral,
      icon: Icons.cancel_rounded,
    ),
    JourneyStatus.expired => StatusCopy(
      label: l.journeyStatusExpired,
      tone: StatusTone.neutral,
      icon: Icons.timer_off_rounded,
    ),
    JourneyStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

StatusCopy offerStatusCopy(BuildContext context, OfferStatus status) {
  final l = L.of(context);
  return switch (status) {
    OfferStatus.pending => StatusCopy(
      label: l.offerStatusPending,
      tone: StatusTone.waiting,
      icon: Icons.schedule_rounded,
    ),
    OfferStatus.countered => StatusCopy(
      label: l.offerCounter,
      tone: StatusTone.progress,
      icon: Icons.swap_horiz_rounded,
    ),
    OfferStatus.accepted => StatusCopy(
      label: l.offerStatusAccepted,
      tone: StatusTone.good,
      icon: Icons.check_circle_rounded,
    ),
    OfferStatus.declined => StatusCopy(
      label: l.offerStatusDeclined,
      tone: StatusTone.neutral,
      icon: Icons.do_not_disturb_on_rounded,
    ),
    OfferStatus.withdrawn => StatusCopy(
      label: l.offerStatusWithdrawn,
      tone: StatusTone.neutral,
      icon: Icons.undo_rounded,
    ),
    OfferStatus.expired => StatusCopy(
      label: l.offerStatusExpired,
      tone: StatusTone.neutral,
      icon: Icons.timer_off_rounded,
    ),
    OfferStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

/// Payout status, always from the traveller's point of view — they are the
/// only party who sees one.
StatusCopy payoutStatusCopy(BuildContext context, PayoutStatus status) {
  final l = L.of(context);
  return switch (status) {
    PayoutStatus.notEligible => StatusCopy(
      label: l.payoutStatusNotEligible,
      tone: StatusTone.waiting,
      icon: Icons.shield_rounded,
    ),
    PayoutStatus.eligible => StatusCopy(
      label: l.payoutStatusEligible,
      tone: StatusTone.progress,
      icon: Icons.check_circle_outline_rounded,
    ),
    PayoutStatus.scheduled => StatusCopy(
      label: l.payoutStatusScheduled,
      tone: StatusTone.progress,
      icon: Icons.event_rounded,
    ),
    PayoutStatus.processing => StatusCopy(
      label: l.payoutStatusProcessing,
      tone: StatusTone.progress,
      icon: Icons.sync_rounded,
    ),
    PayoutStatus.paid => StatusCopy(
      label: l.payoutStatusPaid,
      tone: StatusTone.good,
      icon: Icons.payments_rounded,
    ),
    PayoutStatus.failed => StatusCopy(
      label: l.payoutStatusFailed,
      tone: StatusTone.bad,
      icon: Icons.error_outline_rounded,
    ),
    PayoutStatus.cancelled => StatusCopy(
      label: l.payoutStatusCancelled,
      tone: StatusTone.neutral,
      icon: Icons.cancel_rounded,
    ),
    // Frozen is its own thing: the money exists, a dispute is holding it. It
    // must never read as "failed", which suggests the traveller did wrong.
    PayoutStatus.frozen => StatusCopy(
      label: l.payoutStatusFrozen,
      tone: StatusTone.waiting,
      icon: Icons.ac_unit_rounded,
    ),
    PayoutStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

StatusCopy disputeStatusCopy(BuildContext context, DisputeStatus status) {
  final l = L.of(context);
  return switch (status) {
    DisputeStatus.open => StatusCopy(
      label: l.disputeStatusOpen,
      tone: StatusTone.waiting,
      icon: Icons.gavel_rounded,
    ),
    DisputeStatus.awaitingEvidence => StatusCopy(
      label: l.disputeStatusAwaitingEvidence,
      tone: StatusTone.action,
      icon: Icons.attach_file_rounded,
    ),
    DisputeStatus.underReview => StatusCopy(
      label: l.disputeStatusUnderReview,
      tone: StatusTone.waiting,
      icon: Icons.search_rounded,
    ),
    DisputeStatus.resolved => StatusCopy(
      label: l.disputeStatusResolved,
      tone: StatusTone.good,
      icon: Icons.check_circle_rounded,
    ),
    DisputeStatus.closed => StatusCopy(
      label: l.disputeStatusClosed,
      tone: StatusTone.neutral,
      icon: Icons.lock_rounded,
    ),
    DisputeStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

String disputeCategoryLabel(BuildContext context, DisputeCategory category) {
  final l = L.of(context);
  return switch (category) {
    DisputeCategory.notDelivered => l.disputeCategoryNotDelivered,
    DisputeCategory.damaged => l.disputeCategoryDamaged,
    DisputeCategory.wrongItem => l.disputeCategoryWrongItem,
    DisputeCategory.late => l.disputeCategoryLate,
    DisputeCategory.noShow => l.disputeCategoryNoShow,
    DisputeCategory.payment => l.disputeCategoryPayment,
    DisputeCategory.other => l.disputeCategoryOther,
    DisputeCategory.unknown => l.stateUnexpectedTitle,
  };
}

/// Payment order status. Note there is no "processing" here because the server
/// has none — a payment in flight is a property of the newest attempt, and the
/// screens that care read `PaymentOrder.isSettling` instead.
StatusCopy paymentOrderStatusCopy(
  BuildContext context,
  PaymentOrderStatus status,
) {
  final l = L.of(context);
  return switch (status) {
    PaymentOrderStatus.pending => StatusCopy(
      label: l.paymentStatusRequired,
      tone: StatusTone.action,
      icon: Icons.credit_card_rounded,
    ),
    PaymentOrderStatus.partiallyPaid => StatusCopy(
      label: l.moneyRemainingToPay,
      tone: StatusTone.action,
      icon: Icons.credit_card_rounded,
    ),
    PaymentOrderStatus.paid => StatusCopy(
      label: l.paymentStatusPaid,
      tone: StatusTone.good,
      icon: Icons.check_circle_rounded,
    ),
    PaymentOrderStatus.refundPending => StatusCopy(
      label: l.paymentStatusRefundPending,
      tone: StatusTone.waiting,
      icon: Icons.sync_rounded,
    ),
    PaymentOrderStatus.partiallyRefunded => StatusCopy(
      label: l.paymentStatusPartiallyRefunded,
      tone: StatusTone.neutral,
      icon: Icons.undo_rounded,
    ),
    PaymentOrderStatus.refunded => StatusCopy(
      label: l.paymentStatusRefunded,
      tone: StatusTone.neutral,
      icon: Icons.undo_rounded,
    ),
    PaymentOrderStatus.cancelled => StatusCopy(
      label: l.dealStatusCancelled,
      tone: StatusTone.neutral,
      icon: Icons.cancel_rounded,
    ),
    PaymentOrderStatus.unknown => StatusCopy(
      label: l.stateUnexpectedTitle,
      tone: StatusTone.neutral,
      icon: Icons.help_outline_rounded,
    ),
  };
}

/// The transport-mode word, so no screen writes "Flight" as a literal.
String transportModeLabel(BuildContext context, TransportMode mode) {
  final l = L.of(context);
  return switch (mode) {
    TransportMode.flight => l.journeyModeFlight,
    TransportMode.drive => l.journeyModeDrive,
    TransportMode.unknown => l.stateUnexpectedTitle,
  };
}
