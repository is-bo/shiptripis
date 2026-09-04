import 'dart:async';
import 'dart:convert';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../env/app_config.dart';

typedef NotificationSocketEvent = void Function(Map<String, dynamic> event);

class NotificationSocket {
  WebSocketChannel? _channel;
  StreamSubscription<dynamic>? _subscription;
  Timer? _retry;
  bool _running = false;
  int _attempt = 0;
  Future<String?> Function()? _accessToken;
  NotificationSocketEvent? _onEvent;

  Future<void> start({
    required Future<String?> Function() accessToken,
    required NotificationSocketEvent onEvent,
  }) async {
    _running = true;
    _accessToken = accessToken;
    _onEvent = onEvent;
    await _connect();
  }

  Future<void> stop() async {
    _running = false;
    _retry?.cancel();
    _retry = null;
    final subscription = _subscription;
    _subscription = null;
    await subscription?.cancel();
    final channel = _channel;
    _channel = null;
    await channel?.sink.close();
  }

  Future<void> _connect() async {
    if (!_running || _channel != null) return;
    final token = await _accessToken?.call();
    if (!_running || token == null || token.isEmpty) return;
    try {
      final channel = IOWebSocketChannel.connect(
        Uri.parse('${AppConfig.wsBaseUrl}/ws/notifications'),
        headers: {'Authorization': 'Bearer $token'},
        connectTimeout: AppConfig.connectTimeout,
      );
      _channel = channel;
      await channel.ready;
      _attempt = 0;
      _subscription = channel.stream.listen(
        _handle,
        onDone: _disconnected,
        onError: (_) => _disconnected(),
        cancelOnError: true,
      );
    } on Object {
      _channel = null;
      _scheduleRetry();
    }
  }

  void _handle(dynamic raw) {
    if (raw is! String) return;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        _onEvent?.call(Map<String, dynamic>.from(decoded));
      }
    } on FormatException {
      // A malformed frame is ignored; the authoritative inbox remains HTTP.
    }
  }

  void _disconnected() {
    _subscription = null;
    _channel = null;
    _scheduleRetry();
  }

  void _scheduleRetry() {
    if (!_running || _retry != null) return;
    final exponent = _attempt > 5 ? 5 : _attempt;
    final seconds = 1 << exponent;
    _attempt++;
    _retry = Timer(Duration(seconds: seconds), () {
      _retry = null;
      unawaited(_connect());
    });
  }
}
