/// The notification inbox, reached from the header bell.
///
/// **Navigation is decided from structured data, never from prose.** Every row
/// carries a dotted `channel` such as `offer.created` and a `payload` map of
/// ids. [AppNotification.destination] resolves those two into a target the
/// router understands. The human-readable text is a rendering concern and is
/// produced from the channel and the payload, not scraped from a server
/// sentence — which is also what makes the inbox translatable.
///
/// Push and WebSocket delivery mirror this same row; neither is a second
/// notification database.
library;

import 'json.dart';
import 'progress.dart';

/// The channels that actually produce inbox rows today.
enum NotificationChannel {
  parcelCreated,
  parcelCancelled,
  offerCreated,
  offerUpdated,
  offerEconomicsChanged,
  offerAccepted,
  offerResponseReminder,
  matchInTransit,
  matchCompleted,
  paymentCaptured,
  paymentRefunded,
  paymentFailed,
  chatMessage,
  deliveryCodeAvailable,
  deliveryConfirmed,
  kycStatusChanged,
  legProofStatusChanged,
  dealUpdated,
  dealCancelled,
  dealArrivalReported,
  dealArrivalConfirmed,
  dealArrivalDeclined,
  disputeOpened,
  disputeResolved,
  payoutStatusChanged,
  discoveryRouteAlert,
  discoveryTravelerInterested,
  discoveryRequestFitsTrip,
  dealProgressReported,
  journeyLegReminder,
  dealProblemReported,
  journeyScheduleChangeProposed,
  journeyScheduleChangeAnswered,
  journeyScheduleChangeApplied,
  journeyScheduleChangeWithdrawn,
  unknown;

  static NotificationChannel parse(String raw) => switch (raw) {
    'parcel.created' => parcelCreated,
    'parcel.cancelled' => parcelCancelled,
    'offer.created' => offerCreated,
    'offer.updated' => offerUpdated,
    'offer.economics_changed' => offerEconomicsChanged,
    'offer.accepted' => offerAccepted,
    'offer.response_reminder' => offerResponseReminder,
    'match.in_transit' => matchInTransit,
    'match.completed' => matchCompleted,
    'payment.captured' => paymentCaptured,
    'payment.refunded' => paymentRefunded,
    'payment.failed' => paymentFailed,
    'chat.message.new' => chatMessage,
    'handover.delivery_code_available' => deliveryCodeAvailable,
    'handover.delivery_confirmed' => deliveryConfirmed,
    'kyc.status_changed' => kycStatusChanged,
    'leg_proof.status_changed' => legProofStatusChanged,
    'deal.updated' => dealUpdated,
    'deal.cancelled' => dealCancelled,
    'deal.arrival_reported' => dealArrivalReported,
    'deal.arrival_confirmed' => dealArrivalConfirmed,
    'deal.arrival_declined' => dealArrivalDeclined,
    'dispute.opened' => disputeOpened,
    'dispute.resolved' => disputeResolved,
    'payout.status_changed' => payoutStatusChanged,
    'discovery.route_alert' => discoveryRouteAlert,
    'discovery.traveler_interested' => discoveryTravelerInterested,
    'discovery.request_fits_trip' => discoveryRequestFitsTrip,
    'deal.progress_reported' => dealProgressReported,
    'journey.leg_reminder' => journeyLegReminder,
    'deal.problem_reported' => dealProblemReported,
    'journey.schedule_change_proposed' => journeyScheduleChangeProposed,
    'journey.schedule_change_answered' => journeyScheduleChangeAnswered,
    'journey.schedule_change_applied' => journeyScheduleChangeApplied,
    'journey.schedule_change_withdrawn' => journeyScheduleChangeWithdrawn,
    _ => unknown,
  };
}

/// The transport a reviewed ticket belongs to. A drive leg has no ticket.
enum TicketMode { flight, ferry }

/// What staff decided about a ticket. "Ask for a new upload" stores the
/// rejected status, so it is told apart by the payload's `outcome`.
enum TicketDecision { approved, rejected, resubmissionRequested }

/// Where tapping a notification should take the user.
sealed class NotificationDestination {
  const NotificationDestination();
}

class OpenMatch extends NotificationDestination {
  const OpenMatch(this.matchId);
  final int matchId;
}

class OpenDeal extends NotificationDestination {
  const OpenDeal(this.dealId);
  final int dealId;
}

/// A sender is asked about new times: opens the screen that answers.
class OpenScheduleChange extends NotificationDestination {
  const OpenScheduleChange(this.dealId);
  final int dealId;
}

class OpenRequest extends NotificationDestination {
  const OpenRequest(this.requestId);
  final int requestId;
}

class OpenChat extends NotificationDestination {
  const OpenChat(this.matchId);
  final int matchId;
}

class OpenPayments extends NotificationDestination {
  const OpenPayments();
}

class OpenPayoutDetail extends NotificationDestination {
  const OpenPayoutDetail(this.reference);
  final String reference;
}

class OpenPayoutMethods extends NotificationDestination {
  const OpenPayoutMethods();
}

class OpenJourney extends NotificationDestination {
  const OpenJourney(this.journeyId);
  final int journeyId;
}

/// A reminder: opens the journey with the question for one leg as a sheet.
class OpenProgressQuestion extends NotificationDestination {
  const OpenProgressQuestion({
    required this.journeyId,
    required this.legId,
    required this.kind,
  });
  final int journeyId;
  final int legId;
  final ProgressKind kind;
}

class OpenDispute extends NotificationDestination {
  const OpenDispute(this.disputeId);
  final int disputeId;
}

class OpenKyc extends NotificationDestination {
  const OpenKyc();
}

/// A route alert fired. Opens Browse on the alert's own route with the trip
/// or request that triggered it; with neither id, the member's alert list.
class OpenRouteAlert extends NotificationDestination {
  const OpenRouteAlert({this.alertId, this.journeyId, this.requestId});
  final int? alertId;
  final int? journeyId;
  final int? requestId;
}

/// A traveler said "I can carry this". Opens Find Travelers for that request
/// with that traveler's trip in focus.
class OpenTravelerInterest extends NotificationDestination {
  const OpenTravelerInterest({
    required this.requestId,
    required this.journeyId,
  });
  final int requestId;
  final int journeyId;
}

/// "A parcel fits your trip": opens that parcel's preview, with the trip the
/// server named in focus. Both ids are the traveler's to read: the request is
/// public and the journey is their own.
class OpenRequestFit extends NotificationDestination {
  const OpenRequestFit({required this.requestId, required this.journeyId});
  final int requestId;
  final int journeyId;
}

class AppNotification {
  const AppNotification({
    required this.id,
    required this.channelRaw,
    required this.channel,
    required this.payload,
    this.eventId,
    this.readAt,
    this.createdAt,
  });

  factory AppNotification.fromJson(Map<String, dynamic> json) {
    final channelRaw = readText(json['channel']);
    return AppNotification(
      id: readInt(json['id']) ?? 0,
      channelRaw: channelRaw,
      channel: NotificationChannel.parse(channelRaw),
      eventId: readString(json['event_id']),
      payload: readObject(json['payload']) ?? const {},
      readAt: readDate(json['read_at']),
      createdAt: readDate(json['created_at']),
    );
  }

  final int id;

  /// The raw dotted string. Kept so an unrecognised channel can still be
  /// listed rather than silently dropped.
  final String channelRaw;

  final NotificationChannel channel;

  /// Correlation id, matching the published event.
  final String? eventId;

  /// The published payload: ids, statuses, amounts. The deep-link source.
  final Map<String, dynamic> payload;

  final DateTime? readAt;
  final DateTime? createdAt;

  bool get isUnread => readAt == null;

  int? get matchId => readInt(payload['match_id']);
  int? get dealId => readInt(payload['deal_id']);
  int? get parcelId => readInt(payload['parcel_id']);
  int? get offerId => readInt(payload['offer_id']);
  int? get journeyId =>
      readInt(payload['journey_id']) ?? readInt(payload['trip_id']);
  int? get disputeId => readInt(payload['dispute_id']);
  int? get alertId => readInt(payload['alert_id']);
  int? get legId => readInt(payload['leg_id']);
  ProgressKind? get progressKind =>
      ProgressKind.parse(payload['progress_kind']);

  /// The discovery payloads name a request as `request_id`; the older parcel
  /// channels call the same thing `parcel_id`.
  int? get requestId => readInt(payload['request_id']);
  String? get payoutReference => readString(payload['payout_reference']);
  String? get event => readString(payload['event']);

  /// The ticket a `leg_proof.status_changed` row is about; null for any other
  /// channel or a mode the app does not name.
  TicketMode? get ticketMode => switch (channel) {
    NotificationChannel.legProofStatusChanged => switch (readString(
      payload['mode'],
    )?.toUpperCase()) {
      'FLIGHT' => TicketMode.flight,
      'SEA' => TicketMode.ferry,
      _ => null,
    },
    _ => null,
  };

  /// The decision, from `outcome` when the server sent it and from the stored
  /// `status` otherwise. An unknown value is null, never a guess.
  TicketDecision? get ticketDecision => switch (channel) {
    NotificationChannel.legProofStatusChanged =>
      switch ((readString(payload['outcome']) ?? readString(payload['status']))
          ?.toLowerCase()) {
        'approved' => TicketDecision.approved,
        'rejected' => TicketDecision.rejected,
        'resubmission_requested' => TicketDecision.resubmissionRequested,
        _ => null,
      },
    _ => null,
  };

  /// Resolved from the channel and the payload ids only.
  ///
  /// Returns null when the row carries nothing navigable — an unknown channel
  /// or a payload without an id. The inbox then renders it as read-only text
  /// rather than a dead tap target.
  NotificationDestination? get destination => switch (channel) {
    NotificationChannel.chatMessage => switch (matchId) {
      final int id => OpenChat(id),
      _ => null,
    },
    NotificationChannel.offerCreated ||
    NotificationChannel.offerUpdated ||
    NotificationChannel.offerResponseReminder ||
    NotificationChannel.offerEconomicsChanged => switch (matchId) {
      final int id => OpenMatch(id),
      _ => null,
    },
    NotificationChannel.offerAccepted ||
    NotificationChannel.matchInTransit ||
    NotificationChannel.matchCompleted => switch ((dealId, matchId)) {
      (final int id, _) => OpenDeal(id),
      (_, final int id) => OpenMatch(id),
      _ => null,
    },
    NotificationChannel.paymentCaptured ||
    NotificationChannel.paymentFailed => switch (dealId) {
      final int id => OpenDeal(id),
      _ => const OpenPayments(),
    },
    NotificationChannel.paymentRefunded => const OpenPayments(),
    NotificationChannel.payoutStatusChanged => switch ((
      payoutReference,
      dealId,
      event,
    )) {
      (final String ref, _, _) => OpenPayoutDetail(ref),
      (_, _, 'profile_ready' || 'profile_needs_attention') =>
        const OpenPayoutMethods(),
      (_, final int id, _) => OpenDeal(id),
      _ => const OpenPayoutMethods(),
    },
    NotificationChannel.parcelCreated ||
    NotificationChannel.parcelCancelled => switch (parcelId) {
      final int id => OpenRequest(id),
      _ => null,
    },
    NotificationChannel.legProofStatusChanged => switch (journeyId) {
      final int id => OpenJourney(id),
      _ => null,
    },
    NotificationChannel.deliveryCodeAvailable ||
    NotificationChannel.deliveryConfirmed ||
    NotificationChannel.dealUpdated ||
    NotificationChannel.dealCancelled ||
    NotificationChannel.dealArrivalReported ||
    NotificationChannel.dealArrivalConfirmed ||
    NotificationChannel.dealArrivalDeclined ||
    NotificationChannel.dealProblemReported ||
    NotificationChannel.dealProgressReported => switch (dealId) {
      final int id => OpenDeal(id),
      _ => null,
    },
    NotificationChannel.disputeOpened ||
    NotificationChannel.disputeResolved => switch ((disputeId, dealId)) {
      (final int id, _) => OpenDispute(id),
      (_, final int id) => OpenDeal(id),
      _ => null,
    },
    NotificationChannel.kycStatusChanged => const OpenKyc(),
    NotificationChannel.discoveryRouteAlert => OpenRouteAlert(
      alertId: alertId,
      journeyId: journeyId,
      requestId: requestId,
    ),
    NotificationChannel.discoveryTravelerInterested => switch ((
      requestId,
      journeyId,
    )) {
      (final int request, final int journey) => OpenTravelerInterest(
        requestId: request,
        journeyId: journey,
      ),
      (final int request, _) => OpenRequest(request),
      _ => null,
    },
    NotificationChannel.discoveryRequestFitsTrip => switch ((
      requestId,
      journeyId,
    )) {
      (final int request, final int journey) => OpenRequestFit(
        requestId: request,
        journeyId: journey,
      ),
      _ => null,
    },
    // Asked: the answer screen. Told, or the outcome of an answer: the
    // delivery. The traveler's side has no deal: their journey.
    NotificationChannel.journeyScheduleChangeProposed => switch ((
      dealId,
      journeyId,
    )) {
      (final int deal, _) => OpenScheduleChange(deal),
      (_, final int journey) => OpenJourney(journey),
      _ => null,
    },
    NotificationChannel.journeyScheduleChangeAnswered ||
    NotificationChannel.journeyScheduleChangeApplied ||
    NotificationChannel.journeyScheduleChangeWithdrawn => switch ((
      dealId,
      journeyId,
    )) {
      (final int deal, _) => OpenDeal(deal),
      (_, final int journey) => OpenJourney(journey),
      _ => null,
    },
    NotificationChannel.journeyLegReminder => switch ((
      journeyId,
      legId,
      progressKind,
    )) {
      (final int journey, final int leg, final ProgressKind kind) =>
        OpenProgressQuestion(journeyId: journey, legId: leg, kind: kind),
      (final int journey, _, _) => OpenJourney(journey),
      _ => null,
    },
    NotificationChannel.unknown => null,
  };
}

/// One page of the inbox.
class NotificationPage {
  const NotificationPage({
    required this.count,
    required this.items,
    this.hasMore = false,
  });

  factory NotificationPage.fromJson(Map<String, dynamic> json) =>
      NotificationPage(
        count: readInt(json['count']) ?? 0,
        items: readObjectList(
          json['results'],
        ).map(AppNotification.fromJson).toList(growable: false),
        hasMore: readString(json['next']) != null,
      );

  final int count;
  final List<AppNotification> items;
  final bool hasMore;
}
