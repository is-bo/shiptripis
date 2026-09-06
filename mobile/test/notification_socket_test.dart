import 'dart:async';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/push/notification_socket.dart';

void main() {
  test('opens notification and chat sockets with the latest token', () async {
    final paths = <String>[];
    final connections = <_FakeConnection>[];
    final socket = NotificationSocket(
      connector: (uri, headers) async {
        expect(headers['Authorization'], 'Bearer current-access');
        paths.add(uri.path);
        final connection = _FakeConnection();
        connections.add(connection);
        return connection;
      },
    );
    addTearDown(socket.stop);

    await socket.start(
      accessToken: ({required refresh}) async => 'current-access',
      onEvent: (_, _) {},
      onConnected: (_) {},
    );

    expect(paths.toSet(), NotificationSocket.paths.toSet());
    expect(connections, hasLength(2));
  });

  test('a delayed connect is closed and ignored after stop', () async {
    final pending = <Completer<NotificationSocketConnection>>[];
    final connected = <String>[];
    final socket = NotificationSocket(
      connector: (_, _) {
        final completer = Completer<NotificationSocketConnection>();
        pending.add(completer);
        return completer.future;
      },
    );

    final starting = socket.start(
      accessToken: ({required refresh}) async => 'old-account-token',
      onEvent: (_, _) {},
      onConnected: connected.add,
    );
    await Future<void>.delayed(Duration.zero);
    final stopping = socket.stop();
    final stale = [_FakeConnection(), _FakeConnection()];
    for (var index = 0; index < pending.length; index++) {
      pending[index].complete(stale[index]);
    }
    await Future.wait([starting, stopping]);

    expect(connected, isEmpty);
    expect(stale.every((connection) => connection.closed), isTrue);
  });

  test('failed handshakes refresh once before reconnecting', () async {
    final attempts = <String, int>{};
    final refreshFlags = <bool>[];
    final connected = <String>[];
    final socket = NotificationSocket(
      retryBase: Duration.zero,
      connector: (uri, _) async {
        final attempt = (attempts[uri.path] ?? 0) + 1;
        attempts[uri.path] = attempt;
        if (attempt == 1) throw StateError('rejected handshake');
        return _FakeConnection();
      },
    );
    addTearDown(socket.stop);

    await socket.start(
      accessToken: ({required refresh}) async {
        refreshFlags.add(refresh);
        return refresh ? 'rotated-access' : 'expired-access';
      },
      onEvent: (_, _) {},
      onConnected: connected.add,
    );
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(attempts.values, everyElement(2));
    expect(refreshFlags.where((value) => value), hasLength(2));
    expect(connected.toSet(), NotificationSocket.paths.toSet());
  });

  test(
    'token storage errors enter bounded reconnect instead of escaping',
    () async {
      var tokenReads = 0;
      var connects = 0;
      final socket = NotificationSocket(
        retryBase: Duration.zero,
        connector: (_, _) async {
          connects++;
          return _FakeConnection();
        },
      );
      addTearDown(socket.stop);

      await socket.start(
        accessToken: ({required refresh}) async {
          tokenReads++;
          if (tokenReads <= 2) throw StateError('keystore unavailable');
          return 'access';
        },
        onEvent: (_, _) {},
        onConnected: (_) {},
      );
      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(tokenReads, greaterThanOrEqualTo(4));
      expect(connects, 2);
    },
  );
}

class _FakeConnection implements NotificationSocketConnection {
  final _events = StreamController<dynamic>();
  bool closed = false;

  @override
  Stream<dynamic> get stream => _events.stream;

  @override
  Future<void> close() async {
    if (closed) return;
    closed = true;
    unawaited(_events.close());
  }
}
