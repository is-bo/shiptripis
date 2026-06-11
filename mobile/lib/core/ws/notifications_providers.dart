/// Inbox state: persisted server-side, mirrored locally, kept fresh via WS.
///
/// The Notifications screen reads [notificationsNotifierProvider], which:
///   1. seeds from GET /api/notifications on sign-in / refresh,
///   2. listens to the WS client and prepends each live envelope as a
///      synthetic [InboxItem] (so the UI feels alive without a re-fetch),
///   3. dedupes by `event_id` once the server-confirmed row arrives,
///   4. exposes mark-read / mark-all-read for the screen and badge.
///
/// The WS client lifecycle is still tied to auth: on sign-in we start the
/// socket AND seed the inbox; on sign-out we tear both down.
library;

import 'dart:async';
import 'dart:collection';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import '../notifications/notifications_repository.dart';
import 'notification_envelope.dart';
import 'notification_ws_client.dart';

const _maxRetained = 200;

final notificationsRepositoryProvider =
    Provider<NotificationsRepository>((ref) {
  return NotificationsRepository(ref.read(dioProvider));
});

final notificationWsClientProvider = Provider<NotificationWsClient>((ref) {
  final storage = ref.read(authStorageProvider);
  final client = NotificationWsClient(storage);

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
    required List<InboxItem> items,
    required this.loading,
    required this.unreadCount,
    this.error,
  }) : items = UnmodifiableListView(items);

  final WsConnectionState connection;
  final UnmodifiableListView<InboxItem> items;
  final bool loading;
  final int unreadCount;
  final String? error;

  static NotificationsState initial() => NotificationsState(
        connection: WsConnectionState.idle,
        items: const [],
        loading: false,
        unreadCount: 0,
      );

  NotificationsState copy({
    WsConnectionState? connection,
    List<InboxItem>? items,
    bool? loading,
    int? unreadCount,
    Object? error = _sentinel,
  }) {
    return NotificationsState(
      connection: connection ?? this.connection,
      items: items ?? this.items,
      loading: loading ?? this.loading,
      unreadCount: unreadCount ?? this.unreadCount,
      error: identical(error, _sentinel) ? this.error : error as String?,
    );
  }
}

const _sentinel = Object();

class NotificationsNotifier extends Notifier<NotificationsState> {
  StreamSubscription<NotificationEnvelope>? _eventSub;
  StreamSubscription<WsConnectionState>? _stateSub;
  bool _seeded = false;

  @override
  NotificationsState build() {
    final client = ref.watch(notificationWsClientProvider);

    _eventSub?.cancel();
    _stateSub?.cancel();

    _eventSub = client.events.listen(_onEnvelope);
    _stateSub = client.states.listen(_onConnState);

    // Auto-seed once on sign-in. We can't await inside build, so we kick the
    // load asynchronously and let the UI render the loading state.
    ref.listen<AuthState>(
      authNotifierProvider,
      (prev, next) {
        if (next is AuthSignedIn) {
          if (!_seeded) {
            _seeded = true;
            Future.microtask(refresh);
          }
        } else if (next is AuthSignedOut) {
          _seeded = false;
          state = NotificationsState.initial();
        }
      },
      fireImmediately: true,
    );

    ref.onDispose(() {
      _eventSub?.cancel();
      _stateSub?.cancel();
    });

    return NotificationsState.initial().copy(connection: client.state);
  }

  Future<void> refresh() async {
    state = state.copy(loading: true, error: null);
    try {
      final repo = ref.read(notificationsRepositoryProvider);
      final page = await repo.list(page: 1, pageSize: 50);
      final unread = await repo.unreadCount();
      state = state.copy(
        items: page.items,
        loading: false,
        unreadCount: unread,
        error: null,
      );
    } on NotificationsFailure catch (e) {
      state = state.copy(loading: false, error: e.message);
    } catch (e) {
      state = state.copy(loading: false, error: 'Network error.');
    }
  }

  void _onEnvelope(NotificationEnvelope env) {
    final id = env.eventId;
    if (id == null) return;
    // Skip if we already have this event (server row arrived first, or this
    // is the second copy of the same WS event).
    if (state.items.any((i) => i.eventId == id)) return;
    final synthetic = InboxItem(
      id: -DateTime.now().millisecondsSinceEpoch, // negative = client-only
      channel: env.type,
      eventId: id,
      payload: env.payload ?? const {},
      createdAt: env.ts != null
          ? (DateTime.tryParse(env.ts!) ?? DateTime.now())
          : DateTime.now(),
      readAt: null,
    );
    final next = <InboxItem>[synthetic, ...state.items];
    if (next.length > _maxRetained) next.removeRange(_maxRetained, next.length);
    state = state.copy(
      items: next,
      unreadCount: state.unreadCount + 1,
    );
  }

  void _onConnState(WsConnectionState s) {
    state = state.copy(connection: s);
    // When we reconnect after a drop, re-fetch the server inbox so any events
    // we missed offline land in the list.
    if (s == WsConnectionState.connected && _seeded) {
      Future.microtask(refresh);
    }
  }

  Future<void> markRead(int id) async {
    final idx = state.items.indexWhere((i) => i.id == id);
    if (idx == -1) return;
    final item = state.items[idx];
    if (!item.unread) return;
    // Optimistic.
    final now = DateTime.now();
    final patched = [...state.items];
    patched[idx] = item.markedRead(now);
    state = state.copy(
      items: patched,
      unreadCount: (state.unreadCount - 1).clamp(0, _maxRetained),
    );
    if (id > 0) {
      // Only persisted rows have a real server id.
      await ref.read(notificationsRepositoryProvider).markRead(id);
    }
  }

  Future<void> markAllRead() async {
    final patched = [
      for (final i in state.items) i.unread ? i.markedRead(DateTime.now()) : i,
    ];
    state = state.copy(items: patched, unreadCount: 0);
    await ref.read(notificationsRepositoryProvider).markAllRead();
  }

  void clear() {
    state = state.copy(items: const [], unreadCount: 0);
  }
}

final notificationsNotifierProvider =
    NotifierProvider<NotificationsNotifier, NotificationsState>(
  NotificationsNotifier.new,
);
