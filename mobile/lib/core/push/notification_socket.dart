import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:web_socket_channel/io.dart';
import 'package:web_socket_channel/web_socket_channel.dart';

import '../env/app_config.dart';

typedef NotificationSocketEvent =
    void Function(Map<String, dynamic> event, String path);
typedef NotificationSocketConnected = void Function(String path);
typedef NotificationSocketToken =
    Future<String?> Function({required bool refresh});
typedef NotificationSocketConnector =
    Future<NotificationSocketConnection> Function(
      Uri uri,
      Map<String, String> headers,
    );

abstract interface class NotificationSocketConnection {
  Stream<dynamic> get stream;
  Future<void> close();
}

class NotificationSocket {
  NotificationSocket({
    NotificationSocketConnector? connector,
    Random? random,
    Duration retryBase = const Duration(seconds: 1),
  }) : _connector = connector ?? _connectIO,
       _random = random ?? Random(),
       _retryBase = retryBase;

  static const paths = <String>['/ws/notifications', '/ws/chat'];

  final NotificationSocketConnector _connector;
  final Random _random;
  final Duration _retryBase;
  final Map<String, _EndpointState> _endpoints = {
    for (final path in paths) path: _EndpointState(),
  };

  bool _running = false;
  int _generation = 0;
  NotificationSocketToken? _accessToken;
  NotificationSocketEvent? _onEvent;
  NotificationSocketConnected? _onConnected;

  Future<void> start({
    required NotificationSocketToken accessToken,
    required NotificationSocketEvent onEvent,
    required NotificationSocketConnected onConnected,
  }) async {
    final generation = ++_generation;
    _running = true;
    _accessToken = accessToken;
    _onEvent = onEvent;
    _onConnected = onConnected;
    await _closeEndpoints();
    if (!_isCurrent(generation)) return;
    await Future.wait([for (final path in paths) _connect(path, generation)]);
  }

  Future<void> stop() async {
    _running = false;
    _generation++;
    _accessToken = null;
    _onEvent = null;
    _onConnected = null;
    await _closeEndpoints();
  }

  Future<void> _closeEndpoints() async {
    final subscriptions = <StreamSubscription<dynamic>>[];
    final connections = <NotificationSocketConnection>[];
    for (final endpoint in _endpoints.values) {
      endpoint.retry?.cancel();
      endpoint.retry = null;
      final subscription = endpoint.subscription;
      if (subscription != null) subscriptions.add(subscription);
      endpoint.subscription = null;
      final connection = endpoint.connection;
      if (connection != null) connections.add(connection);
      endpoint.connection = null;
      endpoint.attempt = 0;
      endpoint.refreshBeforeConnect = false;
      endpoint.refreshedSinceConnected = false;
    }
    await Future.wait([
      for (final subscription in subscriptions) subscription.cancel(),
      for (final connection in connections) connection.close(),
    ]);
  }

  Future<void> _connect(String path, int generation) async {
    final endpoint = _endpoints[path]!;
    if (!_isCurrent(generation) || endpoint.connection != null) return;

    final shouldRefresh = endpoint.refreshBeforeConnect;
    final String? token;
    try {
      token = await _accessToken?.call(refresh: shouldRefresh);
    } on Object {
      if (_isCurrent(generation)) _scheduleRetry(path, generation);
      return;
    }
    if (!_isCurrent(generation)) return;
    if (token == null || token.isEmpty) {
      if (shouldRefresh) endpoint.refreshBeforeConnect = true;
      _scheduleRetry(path, generation);
      return;
    }
    if (shouldRefresh) {
      endpoint.refreshBeforeConnect = false;
      endpoint.refreshedSinceConnected = true;
    }

    NotificationSocketConnection? connection;
    try {
      connection = await _connector(Uri.parse('${AppConfig.wsBaseUrl}$path'), {
        'Authorization': 'Bearer $token',
      });
      if (!_isCurrent(generation)) {
        await connection.close();
        return;
      }
      endpoint.connection = connection;
      endpoint.attempt = 0;
      endpoint.refreshBeforeConnect = false;
      endpoint.refreshedSinceConnected = false;
      endpoint.subscription = connection.stream.listen(
        (raw) => _handle(raw, path, generation),
        onDone: () => _disconnected(path, generation, connection!),
        onError: (_) => _disconnected(path, generation, connection!),
        cancelOnError: true,
      );
      _onConnected?.call(path);
    } on Object {
      if (connection != null) await connection.close();
      if (!_isCurrent(generation)) return;
      if (!endpoint.refreshedSinceConnected) {
        endpoint.refreshBeforeConnect = true;
      } else if (endpoint.attempt >= 2) {
        endpoint.refreshBeforeConnect = true;
        endpoint.refreshedSinceConnected = false;
      }
      _scheduleRetry(path, generation);
    }
  }

  void _handle(dynamic raw, String path, int generation) {
    if (!_isCurrent(generation) || raw is! String) return;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is Map) {
        _onEvent?.call(Map<String, dynamic>.from(decoded), path);
      }
    } on FormatException {
      // A malformed frame is ignored; every resource is reconciled over HTTP.
    }
  }

  void _disconnected(
    String path,
    int generation,
    NotificationSocketConnection connection,
  ) {
    final endpoint = _endpoints[path]!;
    if (!_isCurrent(generation) ||
        !identical(endpoint.connection, connection)) {
      return;
    }
    endpoint.subscription = null;
    endpoint.connection = null;
    unawaited(connection.close());
    _scheduleRetry(path, generation);
  }

  void _scheduleRetry(String path, int generation) {
    final endpoint = _endpoints[path]!;
    if (!_isCurrent(generation) || endpoint.retry != null) return;
    final exponent = endpoint.attempt > 5 ? 5 : endpoint.attempt;
    final ceiling = _retryBase.inMilliseconds * (1 << exponent);
    final floor = ceiling ~/ 2;
    final jitter = ceiling <= floor ? 0 : _random.nextInt(ceiling - floor + 1);
    endpoint.attempt++;
    endpoint.retry = Timer(Duration(milliseconds: floor + jitter), () {
      endpoint.retry = null;
      unawaited(_connect(path, generation));
    });
  }

  bool _isCurrent(int generation) => _running && generation == _generation;

  static Future<NotificationSocketConnection> _connectIO(
    Uri uri,
    Map<String, String> headers,
  ) async {
    final channel = IOWebSocketChannel.connect(
      uri,
      headers: headers,
      connectTimeout: AppConfig.connectTimeout,
    );
    try {
      await channel.ready;
    } on Object {
      unawaited(channel.stream.drain<void>().catchError((Object _) {}));
      try {
        await channel.sink.close();
      } on Object {
        // Preserve the handshake failure; reconnect owns recovery.
      }
      rethrow;
    }
    return _WebSocketConnection(channel);
  }
}

class _EndpointState {
  NotificationSocketConnection? connection;
  StreamSubscription<dynamic>? subscription;
  Timer? retry;
  int attempt = 0;
  bool refreshBeforeConnect = false;
  bool refreshedSinceConnected = false;
}

class _WebSocketConnection implements NotificationSocketConnection {
  _WebSocketConnection(this.channel);

  final WebSocketChannel channel;

  @override
  Stream<dynamic> get stream => channel.stream;

  @override
  Future<void> close() async => channel.sink.close();
}
