import 'package:dio/dio.dart';

class ChatFailure implements Exception {
  ChatFailure(this.message, {this.reason});
  final String message;

  /// Stable reason code from the backend when send is gated
  /// (e.g. `payment_pending`, `match_closed`, `not_a_party`). Null for
  /// generic/network failures.
  final String? reason;

  @override
  String toString() => message;
}

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.matchId,
    required this.senderId,
    required this.body,
    required this.createdAt,
    this.readAt,
  });

  factory ChatMessage.fromJson(Map<String, dynamic> j) => ChatMessage(
        id: j['id'] as int,
        matchId: j['match_id'] as int,
        senderId: j['sender_id'] as int,
        body: j['body'] as String,
        createdAt: DateTime.parse(j['created_at'] as String),
        readAt: j['read_at'] == null
            ? null
            : DateTime.tryParse(j['read_at'] as String),
      );

  final int id;
  final int matchId;
  final int senderId;
  final String body;
  final DateTime createdAt;
  final DateTime? readAt;
}

/// One row in the Mailroom inbox — a paid match the viewer can chat on.
class ChatThread {
  const ChatThread({
    required this.matchId,
    required this.counterpartyId,
    required this.counterpartyName,
    required this.route,
    required this.status,
    required this.unreadCount,
    this.lastMessage,
    this.lastMessageAt,
  });

  factory ChatThread.fromJson(Map<String, dynamic> j) => ChatThread(
        matchId: j['match_id'] as int,
        counterpartyId: j['counterparty_id'] as int,
        counterpartyName: (j['counterparty_name'] as String?) ?? '',
        route: (j['route'] as String?) ?? '',
        status: (j['status'] as String?) ?? '',
        unreadCount: (j['unread_count'] as num?)?.toInt() ?? 0,
        lastMessage: j['last_message'] as String?,
        lastMessageAt: j['last_message_at'] == null
            ? null
            : DateTime.tryParse(j['last_message_at'] as String),
      );

  final int matchId;
  final int counterpartyId;
  final String counterpartyName;
  final String route;
  final String status;
  final int unreadCount;
  final String? lastMessage;
  final DateTime? lastMessageAt;

  /// Two-letter monogram for the avatar tile, from the counterparty name.
  String get initials {
    final parts = counterpartyName
        .trim()
        .split(RegExp(r'\s+'))
        .where((p) => p.isNotEmpty)
        .toList();
    if (parts.isEmpty) return '?';
    if (parts.length == 1) {
      final p = parts.first;
      return (p.length >= 2 ? p.substring(0, 2) : p).toUpperCase();
    }
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

class ChatRepository {
  ChatRepository(this._dio);
  final Dio _dio;

  /// Fetch the thread history for a match, oldest-first.
  ///
  /// The endpoint is paginated (DRF PageNumberPagination); V1 loads the
  /// first page (50 messages) which covers the vast majority of threads.
  /// Older history is deferred to a "load earlier" affordance (not V1).
  Future<List<ChatMessage>> listMessages(int matchId,
      {int page = 1, int pageSize = 50}) async {
    final r = await _dio.get<Map<String, dynamic>>(
      '/api/matches/$matchId/chat/messages',
      queryParameters: {'page': page, 'page_size': pageSize},
    );
    if (r.statusCode == 200 && r.data != null) {
      final results = (r.data!['results'] as List?) ?? const [];
      return results
          .map((e) => ChatMessage.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw ChatFailure(_extractMessage(r) ?? 'Could not load messages.');
  }

  /// Fetch the viewer's Mailroom inbox: paid matches they can chat on,
  /// newest activity first, with counterparty + last-message snippet + unread.
  Future<List<ChatThread>> listThreads() async {
    final r = await _dio.get<Map<String, dynamic>>('/api/chat/threads');
    if (r.statusCode == 200 && r.data != null) {
      final results = (r.data!['results'] as List?) ?? const [];
      return results
          .map((e) => ChatThread.fromJson(Map<String, dynamic>.from(e as Map)))
          .toList();
    }
    throw ChatFailure(_extractMessage(r) ?? 'Could not load conversations.');
  }

  /// Send a message. Returns the persisted [ChatMessage] on success.
  ///
  /// On a 402 (deal not ready — payment pending / match closed / no accepted
  /// offer) or 403 (not a party) the thrown [ChatFailure] carries the stable
  /// `reason` code so the UI can render the right copy.
  Future<ChatMessage> sendMessage(int matchId, String body) async {
    try {
      final r = await _dio.post<Map<String, dynamic>>(
        '/api/matches/$matchId/chat/messages',
        data: {'body': body},
      );
      if ((r.statusCode == 200 || r.statusCode == 201) && r.data != null) {
        return ChatMessage.fromJson(r.data!);
      }
      throw ChatFailure(_extractMessage(r) ?? 'Message could not be sent.');
    } on DioException catch (e) {
      final data = e.response?.data;
      final reason = data is Map ? data['reason'] as String? : null;
      throw ChatFailure(
        _reasonMessage(reason) ?? _extractMessage(e.response) ?? 'Message could not be sent.',
        reason: reason,
      );
    }
  }

  String? _reasonMessage(String? reason) {
    switch (reason) {
      case 'payment_pending':
        return 'Chat opens once the sender completes payment.';
      case 'no_accepted_offer':
        return 'Chat opens once an offer is accepted and paid.';
      case 'match_closed':
        return 'This match is closed — chat is no longer available.';
      case 'not_a_party':
        return 'You are not part of this conversation.';
      default:
        return null;
    }
  }

  String? _extractMessage(Response? r) {
    final d = r?.data;
    if (d is Map) {
      if (d['detail'] is String) return d['detail'] as String;
      for (final v in d.values) {
        if (v is List && v.isNotEmpty && v.first is String) {
          return v.first as String;
        }
        if (v is String) return v;
      }
    }
    return null;
  }
}
