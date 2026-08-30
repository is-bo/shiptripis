/// Chat.
///
/// Two server rules the client mirrors rather than reimplements:
///
/// * **Reading outlives writing.** A thread stays listed and readable after a
///   delivery closes; only sending stops. The server publishes `can_send` per
///   thread and the composer is gated on that, never inferred from a status.
///
/// * **An unfunded V1 deal cannot chat.** The server answers `402` with
///   `{"reason": "payment_pending"}` — note the field is `reason`, not the
///   `code` used elsewhere, and there is no human string in the body at all.
///   [ChatBlockReason] carries that vocabulary so the UI can explain the block
///   and offer the payment screen instead of showing a dead composer.
library;

import 'json.dart';

/// Why the server refused a send.
enum ChatBlockReason {
  ok,
  notAParty,
  noAcceptedOffer,

  /// The V1 deal exists but has not been funded. The sender can fix this.
  paymentPending,

  matchClosed,
  productRequestRetired,
  unknown;

  static ChatBlockReason parse(Object? raw) => readEnum(
    raw,
    ChatBlockReason.values,
    fallback: ChatBlockReason.unknown,
    aliases: const {'v1_payment_unavailable': ChatBlockReason.paymentPending},
  );

  /// The one block a sender can act on themselves.
  bool get isFixableByFunding => this == paymentPending;
}

class ChatThread {
  const ChatThread({
    required this.matchId,
    required this.counterpartyId,
    required this.counterpartyName,
    required this.route,
    required this.statusRaw,
    required this.canSend,
    required this.unreadCount,
    this.dealId,
    this.lastMessage,
    this.lastMessageAt,
  });

  factory ChatThread.fromJson(Map<String, dynamic> json) => ChatThread(
    matchId: readInt(json['match_id']) ?? 0,
    // Null on a legacy match that never became a Deal.
    dealId: readInt(json['deal_id']),
    counterpartyId: readInt(json['counterparty_id']) ?? 0,
    counterpartyName: readText(json['counterparty_name']),
    route: readText(json['route']),
    statusRaw: readText(json['status']),
    canSend: readBool(json['can_send']),
    lastMessage: readString(json['last_message']),
    lastMessageAt: readDate(json['last_message_at']),
    unreadCount: readInt(json['unread_count']) ?? 0,
  );

  final int matchId;
  final int? dealId;
  final int counterpartyId;
  final String counterpartyName;

  /// Coarse city pair only — never an address.
  final String route;

  /// The **Match** status, not the Deal status.
  final String statusRaw;

  /// The only thing the composer is enabled from.
  final bool canSend;

  final String? lastMessage;
  final DateTime? lastMessageAt;
  final int unreadCount;

  bool get hasUnread => unreadCount > 0;
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.matchId,
    required this.senderId,
    required this.body,
    this.createdAt,
    this.readAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
    id: readInt(json['id']) ?? 0,
    matchId: readInt(json['match_id']) ?? 0,
    senderId: readInt(json['sender_id']) ?? 0,
    body: readText(json['body']),
    createdAt: readDate(json['created_at']),
    readAt: readDate(json['read_at']),
  );

  final int id;
  final int matchId;
  final int senderId;
  final String body;
  final DateTime? createdAt;
  final DateTime? readAt;

  bool isMine(int viewerId) => senderId == viewerId;
}

/// One page of history, oldest first within the page.
class ChatMessagePage {
  const ChatMessagePage({
    required this.count,
    required this.messages,
    required this.hasMore,
  });

  factory ChatMessagePage.fromJson(Map<String, dynamic> json) =>
      ChatMessagePage(
        count: readInt(json['count']) ?? 0,
        messages: readObjectList(
          json['results'],
        ).map(ChatMessage.fromJson).toList(growable: false),
        hasMore: readString(json['next']) != null,
      );

  final int count;
  final List<ChatMessage> messages;
  final bool hasMore;
}

/// A message the user wrote that has not been acknowledged by the server yet.
///
/// Kept separate from [ChatMessage] so an optimistic bubble can never be
/// mistaken for a delivered one — it has no server id and renders with its own
/// pending or failed affordance.
class PendingChatMessage {
  const PendingChatMessage({
    required this.localId,
    required this.body,
    required this.createdAt,
    this.hasFailed = false,
  });

  final String localId;
  final String body;
  final DateTime createdAt;
  final bool hasFailed;

  PendingChatMessage failed() => PendingChatMessage(
    localId: localId,
    body: body,
    createdAt: createdAt,
    hasFailed: true,
  );
}
