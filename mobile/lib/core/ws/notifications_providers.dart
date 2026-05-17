/// Riverpod glue around [NotificationWsClient].
///
/// - [notificationWsClientProvider] — singleton client, lifecycle tied
///   to the auth state. Starts on sign-in, stops on sign-out, no
///   spinning when signed out.
/// - [notificationsNotifierProvider] — holds the rolling list of
///   received envelopes plus the current connection state, for UI.
library;

import 'dart:async';
import 'dart:collection';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import 'notification_envelope.dart';
import 'notification_ws_client.dart';

const _maxRetained = 100;

final notificationWsClientProvider = Provider<NotificationWsClient>((ref) {
  final storage = ref.read(authStorageProvider);
  final client = NotificationWsClient(storage);

  // Tie the socket lifecycle to auth state: connect when signed in,
  // tear down on sign-out. ref.listen fires for every transition.
  ref.listen<AuthState>(
    authNotifierProvider,
    (prev, next) {
      if (next is AuthSignedIn) {
        client.start();
      } else if (next is AuthSignedOut || next is AuthInitial) {
        client.stop();
      }
    },
    fireImmediately: true,
  );

  ref.onDispose(client.stop);
  return client;
});

class NotificationsState {
  NotificationsState({
    required this.connection,
    required List<NotificationEnvelope> events,
  }) : events = UnmodifiableListView(events);

  final WsConnectionState connection;
  final UnmodifiableListView<NotificationEnvelope> events;

  static NotificationsState initial() =>
      NotificationsState(connection: WsConnectionState.idle, events: const []);

  NotificationsState copy({
    WsConnectionState? connection,
    List<NotificationEnvelope>? events,
  }) {
    return NotificationsState(
      connection: connection ?? this.connection,
      events: events ?? this.events,
    );
  }
}

class NotificationsNotifier extends Notifier<NotificationsState> {
  StreamSubscription<NotificationEnvelope>? _eventSub;
  StreamSubscription<WsConnectionState>? _stateSub;

  @override
  NotificationsState build() {
    final client = ref.watch(notificationWsClientProvider);

    _eventSub?.cancel();
    _stateSub?.cancel();

    _eventSub = client.events.listen(_onEnvelope);
    _stateSub = client.states.listen(_onConnState);

    ref.onDispose(() {
      _eventSub?.cancel();
      _stateSub?.cancel();
    });

    return NotificationsState.initial().copy(connection: client.state);
  }

  void _onEnvelope(NotificationEnvelope env) {
    // Newest first, capped retention so an idle-but-noisy backend
    // can't unbounded-grow the in-memory list.
    final next = <NotificationEnvelope>[env, ...state.events];
    if (next.length > _maxRetained) next.removeRange(_maxRetained, next.length);
    state = state.copy(events: next);
  }

  void _onConnState(WsConnectionState s) {
    state = state.copy(connection: s);
  }

  void clear() {
    state = state.copy(events: const []);
  }
}

final notificationsNotifierProvider =
    NotifierProvider<NotificationsNotifier, NotificationsState>(
  NotificationsNotifier.new,
);
