/// Chat.
///
/// Two server rules the client mirrors rather than reimplements:
///
/// * **Reading outlives writing.** A thread stays listed and readable after a
///   delivery closes; only sending stops. The server publishes `can_send` per
///   thread and the composer is gated on that, never inferred from a status.
///
/// * **An unfunded V1 deal cannot chat.** The eligibility pre-flight returns
///   `eligible: false` with `reason: payment_pending`; a rejected send carries
///   the same reason in its structured response. [ChatBlockReason] carries
///   that vocabulary so the UI can explain the block and offer the payment
///   screen instead of showing a dead composer.
library;

import 'json.dart';
import 'person_photo.dart';

/// Why the server refused a send.
enum ChatBlockReason {
  ok,
  notAParty,
  noAcceptedOffer,

  /// The V1 deal exists but has not been funded. The sender can fix this.
  paymentPending,

  matchClosed,
  productRequestRetired,

  /// One of the two members blocks the other. The conversation stays
  /// readable; only sending stops.
  blocked,
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

/// Why a member reports a message. The server's codes.
enum ChatReportReason {
  spam,
  harassment,
  scam,
  inappropriate,
  other;

  String get code => name;
}

/// The server's pre-flight answer for one conversation.
///
/// This is intentionally fetched before history. An unfunded match has no
/// readable thread yet, and asking the history endpoint first turns the
/// expected `payment_pending` state into a generic permission error.
class ChatEligibility {
  const ChatEligibility({
    required this.eligible,
    required this.reason,
    required this.matchId,
    this.blockedByMe = false,
  });

  factory ChatEligibility.fromJson(Map<String, dynamic> json) =>
      ChatEligibility(
        eligible: readBool(json['eligible']),
        reason: ChatBlockReason.parse(json['reason']),
        matchId: readInt(json['match_id']) ?? 0,
        blockedByMe: readBool(json['blocked_by_me']),
      );

  final bool eligible;
  final ChatBlockReason reason;
  final int matchId;

  /// The viewer blocks the other member, so the app offers to unblock.
  final bool blockedByMe;

  /// Closed and blocked conversations remain readable even though they are
  /// not writable. All other refused states have no history before funding.
  bool get canReadHistory =>
      eligible ||
      reason == ChatBlockReason.matchClosed ||
      reason == ChatBlockReason.blocked;
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
    this.lastMessageRemoved = false,
    this.counterpartyPhoto,
    this.counterpartyDeleted = false,
    this.blockedByMe = false,
  });

  factory ChatThread.fromJson(Map<String, dynamic> json) => ChatThread(
    matchId: readInt(json['match_id']) ?? 0,
    // Null on a legacy match that never became a Deal.
    dealId: readInt(json['deal_id']),
    counterpartyId: readInt(json['counterparty_id']) ?? 0,
    counterpartyName: readText(json['counterparty_name']),
    counterpartyPhoto: PersonPhoto.maybe(json['counterparty_photo']),
    route: readText(json['route']),
    statusRaw: readText(json['status']),
    canSend: readBool(json['can_send']),
    lastMessage: readString(json['last_message']),
    lastMessageAt: readDate(json['last_message_at']),
    lastMessageRemoved: readBool(json['last_message_removed']),
    unreadCount: readInt(json['unread_count']) ?? 0,
    counterpartyDeleted: readBool(json['counterparty_deleted']),
    blockedByMe: readBool(json['blocked_by_me']),
  );

  final int matchId;
  final int? dealId;
  final int counterpartyId;
  final String counterpartyName;

  /// Null when they have none, and when the account is gone.
  final PersonPhoto? counterpartyPhoto;

  /// Coarse city pair only — never an address.
  final String route;

  /// The **Match** status, not the Deal status.
  final String statusRaw;

  /// The only thing the composer is enabled from.
  final bool canSend;

  final String? lastMessage;
  final DateTime? lastMessageAt;

  /// Wassla removed the last message; its text is never sent.
  final bool lastMessageRemoved;
  final int unreadCount;

  /// The other member deleted their account; the app names them so.
  final bool counterpartyDeleted;

  /// The viewer blocks the other member.
  final bool blockedByMe;

  bool get hasUnread => unreadCount > 0;
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.matchId,
    required this.senderId,
    required this.body,
    this.removed = false,
    this.createdAt,
    this.readAt,
    this.clientMessageId,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> json) => ChatMessage(
    id: readInt(json['id']) ?? 0,
    matchId: readInt(json['match_id']) ?? 0,
    senderId: readInt(json['sender_id']) ?? 0,
    body: readText(json['body']),
    removed: readBool(json['removed']),
    createdAt: readDate(json['created_at']),
    readAt: readDate(json['read_at']),
    clientMessageId: readString(json['client_message_id']),
  );

  final int id;
  final int matchId;
  final int senderId;
  final String body;

  /// Wassla removed this message after a report; [body] is empty.
  final bool removed;
  final DateTime? createdAt;
  final DateTime? readAt;
  final String? clientMessageId;

  bool isMine(int viewerId) => senderId == viewerId;
}

/// One page of history, oldest first within the page.
class ChatMessagePage {
  const ChatMessagePage({
    required this.count,
    required this.messages,
    required this.hasMore,
    this.oldestId,
    this.latestId,
    this.next,
  });

  factory ChatMessagePage.fromJson(Map<String, dynamic> json) {
    final messages = readObjectList(
      json['results'],
    ).map(ChatMessage.fromJson).toList(growable: false);
    return ChatMessagePage(
      count: readInt(json['count']) ?? messages.length,
      messages: messages,
      // `next` keeps older deployments readable. Cursor-aware deployments
      // publish `has_more`, whose meaning follows the selected direction.
      hasMore:
          (json.containsKey('has_more') && readBool(json['has_more'])) ||
          readString(json['next']) != null,
      oldestId:
          readInt(json['oldest_id']) ??
          (messages.isEmpty ? null : messages.first.id),
      latestId:
          readInt(json['latest_id']) ??
          (messages.isEmpty ? null : messages.last.id),
      next: readString(json['next']),
    );
  }

  final int count;
  final List<ChatMessage> messages;
  final bool hasMore;
  final int? oldestId;
  final int? latestId;
  final String? next;
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

  PendingChatMessage retrying() =>
      PendingChatMessage(localId: localId, body: body, createdAt: createdAt);
}

/// Someone the viewer blocks, as Profile lists them.
class BlockedPerson {
  const BlockedPerson({
    required this.userId,
    required this.name,
    required this.deleted,
    this.blockedAt,
  });

  factory BlockedPerson.fromJson(Map<String, dynamic> json) => BlockedPerson(
    userId: readInt(json['user_id']) ?? 0,
    name: readText(json['name']),
    deleted: readBool(json['deleted']),
    blockedAt: readDate(json['blocked_at']),
  );

  final int userId;
  final String name;

  /// They deleted their account since.
  final bool deleted;
  final DateTime? blockedAt;
}
