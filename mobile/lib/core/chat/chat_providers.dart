/// Chat thread state for a single Match: seeds from GET history, stays live
/// via the `/ws/chat` socket, and sends through the Django write endpoint.
///
/// One [ChatWsClient] is shared across threads (it's a single socket for all
/// of a user's conversations); each [ChatThreadNotifier] filters incoming
/// envelopes by its own `matchId`. The socket is started on first thread open
/// and torn down when the last listener disposes.
library;

import 'dart:async';
import 'dart:collection';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';
import '../ws/notification_envelope.dart';
import 'chat_repository.dart';
import 'chat_ws_client.dart';

final chatRepositoryProvider = Provider<ChatRepository>((ref) {
  return ChatRepository(ref.read(dioProvider));
});

/// Single shared chat socket, lifecycle-tied to auth (like the notification
/// client). Started when the first thread screen watches it; stopped on
/// sign-out and on dispose.
final chatWsClientProvider = Provider<ChatWsClient>((ref) {
  final client = ChatWsClient(ref.read(authStorageProvider));

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

class ChatThreadState {
  ChatThreadState({
    required List<ChatMessage> messages,
    required this.loading,
    required this.sending,
    this.error,
  }) : messages = UnmodifiableListView(messages);

  final UnmodifiableListView<ChatMessage> messages;
  final bool loading;
  final bool sending;
  final String? error;

  static ChatThreadState initial() =>
      ChatThreadState(messages: const [], loading: true, sending: false);

  ChatThreadState copy({
    List<ChatMessage>? messages,
    bool? loading,
    bool? sending,
    Object? error = _sentinel,
  }) {
    return ChatThreadState(
      messages: messages ?? this.messages,
      loading: loading ?? this.loading,
      sending: sending ?? this.sending,
      error: identical(error, _sentinel) ? this.error : error as String?,
    );
  }
}

const _sentinel = Object();

class ChatThreadNotifier extends Notifier<ChatThreadState> {
  ChatThreadNotifier(this.matchId);
  final int matchId;

  StreamSubscription<NotificationEnvelope>? _sub;

  @override
  ChatThreadState build() {
    final client = ref.watch(chatWsClientProvider);
    _sub?.cancel();
    _sub = client.events.listen((env) => _onEnvelope(matchId, env));
    ref.onDispose(() => _sub?.cancel());

    Future.microtask(_load);
    return ChatThreadState.initial();
  }

  Future<void> _load() async {
    state = state.copy(loading: true, error: null);
    try {
      final msgs = await ref.read(chatRepositoryProvider).listMessages(matchId);
      state = state.copy(messages: msgs, loading: false, error: null);
    } on ChatFailure catch (e) {
      state = state.copy(loading: false, error: e.message);
    } catch (_) {
      state = state.copy(loading: false, error: 'Could not load messages.');
    }
  }

  Future<void> refresh() => _load();

  /// Send a message. Optimism is deliberately avoided: the send returns the
  /// persisted row (with a real id + server timestamp) which we append, and
  /// the WS echo for the OTHER party is deduped by id.
  Future<bool> send(String body) async {
    final trimmed = body.trim();
    if (trimmed.isEmpty || state.sending) return false;
    state = state.copy(sending: true, error: null);
    try {
      final msg = await ref.read(chatRepositoryProvider).sendMessage(matchId, trimmed);
      _appendIfNew(msg);
      state = state.copy(sending: false, error: null);
      return true;
    } on ChatFailure catch (e) {
      state = state.copy(sending: false, error: e.message);
      return false;
    } catch (_) {
      state = state.copy(sending: false, error: 'Message could not be sent.');
      return false;
    }
  }

  void _onEnvelope(int matchId, NotificationEnvelope env) {
    if (env.type != 'chat.message.new') return;
    final p = env.payload;
    if (p == null) return;
    if (p['match_id'] != matchId) return;
    try {
      _appendIfNew(ChatMessage.fromJson(Map<String, dynamic>.from(p)));
    } catch (_) {
      // Malformed payload — ignore.
    }
  }

  void _appendIfNew(ChatMessage msg) {
    if (state.messages.any((m) => m.id == msg.id)) return;
    state = state.copy(messages: [...state.messages, msg]);
  }
}

final chatThreadProvider =
    NotifierProvider.family<ChatThreadNotifier, ChatThreadState, int>(
  ChatThreadNotifier.new,
);

