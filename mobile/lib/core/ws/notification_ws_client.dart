/// Long-lived WebSocket client for `/ws/notifications`.
///
/// Reconnect strategy per CLAUDE.md §7: exponential backoff with ±30%
/// jitter, capped at 30s. Algerian mobile networks reconnect thousands
/// of devices simultaneously after tower hiccups — a uniform schedule
/// would dogpile the Go pods.
///
/// Auth: sends the JWT access token as a Bearer header on the upgrade
/// request. This matches `backend/services/pkg/wsproto/wsproto.go` —
/// it parses `Authorization` only, no query-param fallback.
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../auth/auth_storage.dart';
import '../config/api_config.dart';
import 'notification_envelope.dart';

enum WsConnectionState { idle, connecting, connected, reconnecting, closed }

class NotificationWsClient {
  NotificationWsClient(this._storage);

  final AuthStorage _storage;
  final _events = StreamController<NotificationEnvelope>.broadcast();
  final _states =
      StreamController<WsConnectionState>.broadcast(sync: true);

  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _sub;
  Timer? _reconnectTimer;

  WsConnectionState _state = WsConnectionState.idle;
  int _attempt = 0;
  bool _stopped = false;

  Stream<NotificationEnvelope> get events => _events.stream;
  Stream<WsConnectionState> get states => _states.stream;
  WsConnectionState get state => _state;

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
    _setState(WsConnectionState.closed);
  }

  Future<void> _connect() async {
    if (_stopped) return;
    _setState(_attempt == 0
        ? WsConnectionState.connecting
        : WsConnectionState.reconnecting);

    final access = await _storage.readAccess();
    if (access == null || access.isEmpty) {
      // No token yet — caller (auth listener) will retrigger when sign-in
      // completes. Stay idle rather than spinning a reconnect loop.
      _setState(WsConnectionState.idle);
      return;
    }

    final url = '${ApiConfig.wsBaseUrl}/ws/notifications';
    try {
      _channel = IOWebSocketChannel.connect(
        Uri.parse(url),
        headers: {'Authorization': 'Bearer $access'},
        pingInterval: const Duration(seconds: 20),
      );
      // IOWebSocketChannel does not await the handshake; the first
      // frame (or onError) tells us if it worked. Treat first onData
      // or successful sink as "connected" — onError before any data
      // triggers reconnect.
      _attempt = 0;
      _setState(WsConnectionState.connected);

      _sub = _channel!.stream.listen(
        _onData,
        onError: _onError,
        onDone: _onDone,
        cancelOnError: true,
      );
    } catch (e) {
      _scheduleReconnect();
    }
  }

  void _onData(dynamic raw) {
    try {
      final str = raw is String ? raw : utf8.decode(raw as List<int>);
      final json = jsonDecode(str) as Map<String, dynamic>;
      final env = NotificationEnvelope.fromJson(json);
      _events.add(env);
    } catch (_) {
      // Bad frame — log and move on. A misbehaving server shouldn't
      // tear down the socket.
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
    _setState(WsConnectionState.reconnecting);
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

  void _setState(WsConnectionState next) {
    if (_state == next) return;
    _state = next;
    _states.add(next);
  }
}
