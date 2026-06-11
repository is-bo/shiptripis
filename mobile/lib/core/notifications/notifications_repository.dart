import 'package:dio/dio.dart';

class NotificationsFailure implements Exception {
  NotificationsFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class InboxItem {
  const InboxItem({
    required this.id,
    required this.channel,
    required this.eventId,
    required this.payload,
    required this.createdAt,
    required this.readAt,
  });

  factory InboxItem.fromJson(Map<String, dynamic> j) => InboxItem(
        id: j['id'] as int,
        channel: j['channel'] as String,
        eventId: j['event_id'] as String,
        payload: j['payload'] is Map
            ? Map<String, dynamic>.from(j['payload'] as Map)
            : const <String, dynamic>{},
        createdAt: DateTime.parse(j['created_at'] as String),
        readAt: j['read_at'] is String
            ? DateTime.parse(j['read_at'] as String)
            : null,
      );

  final int id;
  final String channel;
  final String eventId;
  final Map<String, dynamic> payload;
  final DateTime createdAt;
  final DateTime? readAt;

  bool get unread => readAt == null;

  InboxItem markedRead(DateTime when) => InboxItem(
        id: id,
        channel: channel,
        eventId: eventId,
        payload: payload,
        createdAt: createdAt,
        readAt: when,
      );
}

class InboxPage {
  const InboxPage({required this.items, required this.hasMore});
  final List<InboxItem> items;
  final bool hasMore;
}

class NotificationsRepository {
  NotificationsRepository(this._dio);
  final Dio _dio;

  Future<InboxPage> list({int page = 1, int pageSize = 30}) async {
    try {
      final r = await _dio.get<Map<String, dynamic>>(
        '/api/notifications',
        queryParameters: {'page': page, 'page_size': pageSize},
      );
      final data = r.data;
      if (r.statusCode == 200 && data != null) {
        final results = (data['results'] as List? ?? const [])
            .map((e) => InboxItem.fromJson(Map<String, dynamic>.from(e as Map)))
            .toList();
        return InboxPage(items: results, hasMore: data['next'] != null);
      }
    } on DioException catch (e) {
      throw NotificationsFailure(_msg(e.response) ?? 'Could not load inbox.');
    }
    throw NotificationsFailure('Could not load inbox.');
  }

  Future<int> unreadCount() async {
    try {
      final r = await _dio
          .get<Map<String, dynamic>>('/api/notifications/unread-count');
      if (r.statusCode == 200 && r.data != null) {
        return (r.data!['unread'] as num?)?.toInt() ?? 0;
      }
    } on DioException catch (_) {
      // Best-effort badge; swallow.
    }
    return 0;
  }

  Future<InboxItem?> markRead(int id) async {
    try {
      final r = await _dio
          .post<Map<String, dynamic>>('/api/notifications/$id/read');
      if (r.statusCode == 200 && r.data != null) {
        return InboxItem.fromJson(r.data!);
      }
    } on DioException catch (_) {
      // Best-effort.
    }
    return null;
  }

  Future<void> markAllRead() async {
    try {
      await _dio.post<void>('/api/notifications/read-all');
    } on DioException catch (_) {
      // Best-effort.
    }
  }

  String? _msg(Response? r) {
    final d = r?.data;
    if (d is Map && d['detail'] is String) return d['detail'] as String;
    return null;
  }
}
