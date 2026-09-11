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

/// The channels that actually produce inbox rows today.
enum NotificationChannel {
  parcelCreated,
  parcelCancelled,
  matchCreated,
  offerCreated,
  offerUpdated,
  offerAccepted,
  matchInTransit,
  matchCompleted,
  paymentCaptured,
  paymentRefunded,
  paymentFailed,
  chatMessage,
  tripCreated,
  tripUpdated,
  tripCancelled,
  handoverConfirmed,
  deliveryCodeAvailable,
  deliveryConfirmed,
  kycStatusChanged,
  flightProofStatusChanged,
  dealUpdated,
  dealCancelled,
  disputeOpened,
  disputeResolved,
  payoutStatusChanged,
  unknown;

  static NotificationChannel parse(String raw) => switch (raw) {
    'parcel.created' => parcelCreated,
    'parcel.cancelled' => parcelCancelled,
    'match.created' => matchCreated,
    'offer.created' => offerCreated,
    'offer.updated' => offerUpdated,
    'offer.accepted' => offerAccepted,
    'match.in_transit' => matchInTransit,
    'match.completed' => matchCompleted,
    'payment.captured' => paymentCaptured,
    'payment.refunded' => paymentRefunded,
    'payment.failed' => paymentFailed,
    'chat.message.new' => chatMessage,
    'trip.created' => tripCreated,
    'trip.updated' => tripUpdated,
    'trip.cancelled' => tripCancelled,
    'handover.confirmed' => handoverConfirmed,
    'handover.delivery_code_available' => deliveryCodeAvailable,
    'handover.delivery_confirmed' => deliveryConfirmed,
    'kyc.status_changed' => kycStatusChanged,
    'flight_proof.status_changed' => flightProofStatusChanged,
    'deal.updated' => dealUpdated,
    'deal.cancelled' => dealCancelled,
    'dispute.opened' => disputeOpened,
    'dispute.resolved' => disputeResolved,
    'payout.status_changed' => payoutStatusChanged,
    _ => unknown,
  };
}

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

class OpenDispute extends NotificationDestination {
  const OpenDispute(this.disputeId);
  final int disputeId;
}

class OpenKyc extends NotificationDestination {
  const OpenKyc();
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
  String? get payoutReference => readString(payload['payout_reference']);
  String? get event => readString(payload['event']);

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
    NotificationChannel.matchCreated ||
    NotificationChannel.offerCreated ||
    NotificationChannel.offerUpdated => switch (matchId) {
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
    NotificationChannel.payoutStatusChanged => switch ((payoutReference, dealId, event)) {
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
    NotificationChannel.tripCreated ||
    NotificationChannel.tripUpdated ||
    NotificationChannel.tripCancelled ||
    NotificationChannel.flightProofStatusChanged => switch (journeyId) {
      final int id => OpenJourney(id),
      _ => null,
    },
    NotificationChannel.handoverConfirmed ||
    NotificationChannel.deliveryCodeAvailable ||
    NotificationChannel.deliveryConfirmed ||
    NotificationChannel.dealUpdated ||
    NotificationChannel.dealCancelled => switch (dealId) {
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
