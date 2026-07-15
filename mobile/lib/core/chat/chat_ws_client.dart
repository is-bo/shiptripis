/// Long-lived WebSocket client for `/ws/chat`.
///
/// Mirrors [NotificationWsClient] — same reconnect strategy (exponential
/// backoff with ±30% jitter, capped at 30s, per CLAUDE.md §7) and the same
/// Bearer-header auth the Go `pkg/wsproto` expects. Kept as a separate client
/// (not merged with notifications) because the two sockets have independent
/// lifecycles: chat is only live while a thread screen is open, whereas the
/// notification socket runs for the whole session.
///
/// The Go chat-service relays `chat.message.new` envelopes whose `payload`
/// carries {message_id, match_id, sender_id, body, created_at} — the same
/// dict Django published. Consumers filter by `match_id`.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../auth/auth_storage.dart';
import '../config/api_config.dart';
import '../ws/notification_envelope.dart';

enum ChatWsState { idle, connecting, connected, reconnecting, closed }

class ChatWsClient {
  ChatWsClient(this._storage);

  final AuthStorage _storage;
  final _events = StreamController<NotificationEnvelope>.broadcast();
  final _states = StreamController<ChatWsState>.broadcast(sync: true);

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _reconnectTimer;

  ChatWsState _state = ChatWsState.idle;
  int _attempt = 0;
  bool _stopped = false;

  Stream<NotificationEnvelope> get events => _events.stream;
  Stream<ChatWsState> get states => _states.stream;
  ChatWsState get state => _state;

  Future<void> start() async {
    _stopped = false;
    await _connect();
  }

  Future<void> stop() async {
    _stopped = true;
    _reconnectTimer?.cancel();
    _reconnectTimer = null;
    await _sub?.cancel();
    _sub = null;
    await _channel?.sink.close();
    _channel = null;
    _setState(ChatWsState.closed);
  }

  Future<void> _connect() async {
    if (_stopped) return;
    _setState(
        _attempt == 0 ? ChatWsState.connecting : ChatWsState.reconnecting);

    final access = await _storage.readAccess();
    if (access == null || access.isEmpty) {
      _setState(ChatWsState.idle);
      return;
    }

    final url = '${ApiConfig.wsBaseUrl}/ws/chat';
    try {
      _channel = IOWebSocketChannel.connect(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $access'},
        pingInterval: const Duration(seconds: 20),
      );
      _attempt = 0;
      _setState(ChatWsState.connected);

      _sub = _channel!.stream.listen(
        _onData,
        onError: _onError,
        onDone: _onDone,
        cancelOnError: true,
      );
    } catch (_) {
      _scheduleReconnect();
    }
  }

  void _onData(dynamic raw) {
    try {
      final str = raw is String ? raw : utf8.decode(raw as List<int>);
      final json = jsonDecode(str) as Map<String, dynamic>;
      _events.add(NotificationEnvelope.fromJson(json));
    } catch (_) {
      // Bad frame — ignore; a misbehaving server shouldn't tear the socket.
    }
  }

  void _onError(Object _) => _scheduleReconnect();
  void _onDone() => _scheduleReconnect();

  void _scheduleReconnect() {
    _sub?.cancel();
    _sub = null;
    _channel?.sink.close();
    _channel = null;

    if (_stopped) return;

    _attempt++;
    final delay = _backoffDelay(_attempt);
    _setState(ChatWsState.reconnecting);
    _reconnectTimer?.cancel();
    _reconnectTimer = Timer(delay, _connect);
  }

  /// Exponential backoff with ±30% jitter. Base 1s, cap 30s.
  Duration _backoffDelay(int attempt) {
    final base = min(30, 1 << min(attempt, 5)); // 2,4,8,16,30,30…
    final rng = Random();
    final jitter = 1.0 + (rng.nextDouble() * 0.6 - 0.3); // ±30%
    final ms = (base * 1000 * jitter).clamp(500, 30000).toInt();
    return Duration(milliseconds: ms);
  }

  void _setState(ChatWsState next) {
    if (_state == next) return;
    _state = next;
    _states.add(next);
  }
}
