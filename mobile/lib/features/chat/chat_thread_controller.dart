/// Session-bound state and reconciliation for one chat thread.
library;

import 'dart:async';
import 'dart:math';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_riverpod/legacy.dart' show ChangeNotifierProvider;

import '../../app/app_state.dart';
import '../../core/api/api_exception.dart';
import '../../core/live/live_updates.dart';
import '../../core/session/session.dart';
import '../../data/repositories.dart';
import '../../domain/chat.dart';

typedef ChatLiveRegistrar = VoidCallback Function(VoidCallback callback);

final chatThreadControllerProvider = ChangeNotifierProvider.autoDispose
    .family<ChatThreadController, int>((ref, matchId) {
      final accountId = ref.watch(
        sessionProvider.select(
          (session) => session is SessionSignedIn ? session.account.id : null,
        ),
      );
      return ChatThreadController(
        matchId: matchId,
        accountId: accountId,
        repository: ref.watch(chatRepositoryProvider),
        registerLive: (callback) => ref
            .read(liveUpdatesProvider)
            .register(LiveResource.chat(matchId), callback),
        // Reading a conversation resolves its chat notifications server-side,
        // so the bell has to be re-read with the thread list. Chat is the
        // highest-volume channel; refreshing only the list is what left the
        // badge counting messages the user had already read.
        invalidateThreads: () => ref
          ..invalidate(chatThreadsProvider)
          ..invalidate(unreadNotificationsProvider),
      );
    });

/// Owns both delivered and optimistic messages for one account and match.
///
/// Delivered messages are keyed only by their server id. This makes replayed
/// websocket notifications and HTTP pages harmless while preserving two
/// legitimate messages that happen to have the same sender, body and time.
class ChatThreadController extends ChangeNotifier {
  ChatThreadController({
    required this.matchId,
    required this.accountId,
    required ChatRepository repository,
    required ChatLiveRegistrar registerLive,
    required VoidCallback invalidateThreads,
  }) : _repository = repository,
       _invalidateThreads = invalidateThreads {
    if (accountId == null) {
      _initialLoading = false;
      initialLoad = Future<void>.value();
      return;
    }
    _unsubscribeLive = registerLive(_onLiveChanged);
    initialLoad = _loadInitial();
  }

  static const int latestWindowSize = 50;
  static const int deltaPageSize = 200;

  final int matchId;
  final int? accountId;
  final ChatRepository _repository;
  final VoidCallback _invalidateThreads;

  final Map<int, ChatMessage> _delivered = <int, ChatMessage>{};
  final List<PendingChatMessage> _pending = <PendingChatMessage>[];
  final List<ChatMessagePage> _deferredPages = <ChatMessagePage>[];
  final Set<CancelToken> _readTokens = <CancelToken>{};
  final Set<CancelToken> _sendTokens = <CancelToken>{};

  VoidCallback? _unsubscribeLive;
  late final Future<void> initialLoad;
  Future<void>? _reconcileFuture;
  bool _reconcileQueued = false;
  bool _active = true;
  bool _initialLoading = true;
  bool _loadingOlder = false;
  bool _hasMoreOlder = false;
  int _unresolvedSends = 0;
  int _reconcileCursor = 0;
  Object? _initialError;
  Object? _backgroundError;
  ChatEligibility? _eligibility;
  ChatBlockReason _sendBlock = ChatBlockReason.ok;

  ChatEligibility? get eligibility => _eligibility;
  Object? get initialError => _initialError;
  Object? get backgroundError => _backgroundError;
  bool get isInitialLoading => _initialLoading;
  bool get isLoadingOlder => _loadingOlder;
  bool get hasMoreOlder => _hasMoreOlder;
  bool get isSending => _unresolvedSends > 0;
  ChatBlockReason get sendBlock => _sendBlock;
  bool get canSend =>
      _eligibility?.eligible == true && _sendBlock == ChatBlockReason.ok;
  int get latestMessageId => _highestId;

  List<ChatMessage> get messages {
    final result = _delivered.values.toList(growable: false);
    result.sort((a, b) => a.id.compareTo(b.id));
    return result;
  }

  List<PendingChatMessage> get pendingMessages =>
      List<PendingChatMessage>.unmodifiable(_pending);

  int get _highestId =>
      _delivered.isEmpty ? 0 : _delivered.keys.reduce((a, b) => a > b ? a : b);

  int? get _lowestId => _delivered.isEmpty
      ? null
      : _delivered.keys.reduce((a, b) => a < b ? a : b);

  Future<void> reload() async {
    if (!_active || accountId == null) return;
    for (final token in _readTokens.toList(growable: false)) {
      token.cancel('chat reload');
    }
    _readTokens.clear();
    _initialError = null;
    _initialLoading = true;
    notifyListeners();
    await _loadInitial();
  }

  Future<void> _loadInitial() async {
    final token = CancelToken();
    _readTokens.add(token);
    try {
      final eligibility = await _repository.eligibility(
        matchId: matchId,
        cancelToken: token,
      );
      if (!_accepts(token)) return;

      _eligibility = eligibility;
      _sendBlock = eligibility.eligible
          ? ChatBlockReason.ok
          : eligibility.reason;
      if (!eligibility.canReadHistory) {
        _delivered.clear();
        _reconcileCursor = 0;
        _hasMoreOlder = false;
        return;
      }

      final page = await _repository.messages(
        matchId: matchId,
        latest: true,
        pageSize: latestWindowSize,
        cancelToken: token,
      );
      if (!_accepts(token)) return;
      _merge(page.messages);
      _reconcileCursor = page.latestId ?? _highestId;
      _hasMoreOlder = page.hasMore;
      _backgroundError = null;
      _invalidateThreads();
    } on Object catch (error) {
      if (!_accepts(token)) return;
      _initialError = error;
    } finally {
      if (_accepts(token)) {
        _initialLoading = false;
        _readTokens.remove(token);
        notifyListeners();
        if (_reconcileQueued) unawaited(reconcile());
      }
    }
  }

  /// Fetches every message after the last id observed through HTTP history.
  ///
  /// Calls coalesce while a fetch is active. A live event arriving during the
  /// fetch schedules exactly one additional pass, closing the event/fetch
  /// race without running concurrent page walks.
  Future<void> reconcile() {
    if (!_active || accountId == null) return Future<void>.value();
    if (_unresolvedSends > 0 || _initialLoading) {
      _reconcileQueued = true;
      return _reconcileFuture ?? Future<void>.value();
    }
    final active = _reconcileFuture;
    if (active != null) {
      _reconcileQueued = true;
      return active;
    }

    _reconcileQueued = false;
    final run = _runReconcile();
    _reconcileFuture = run;
    return run;
  }

  Future<void> _runReconcile() async {
    CancelToken? currentToken;
    try {
      final eligibilityToken = CancelToken();
      currentToken = eligibilityToken;
      _readTokens.add(eligibilityToken);
      final eligibility = await _repository.eligibility(
        matchId: matchId,
        cancelToken: eligibilityToken,
      );
      if (!_accepts(eligibilityToken)) return;
      _readTokens.remove(eligibilityToken);
      currentToken = null;
      _eligibility = eligibility;
      _sendBlock = eligibility.eligible
          ? ChatBlockReason.ok
          : eligibility.reason;
      if (!eligibility.canReadHistory) {
        _delivered.clear();
        _reconcileCursor = 0;
        _hasMoreOlder = false;
        _initialError = null;
        _backgroundError = null;
        notifyListeners();
        return;
      }

      var cursor = _reconcileCursor;
      while (_active) {
        final token = CancelToken();
        currentToken = token;
        _readTokens.add(token);
        final page = await _repository.messages(
          matchId: matchId,
          afterId: cursor,
          pageSize: deltaPageSize,
          cancelToken: token,
        );
        if (!_accepts(token)) return;
        _readTokens.remove(token);
        currentToken = null;
        _invalidateThreads();
        _initialError = null;
        _backgroundError = null;

        if (_unresolvedSends > 0) {
          _deferredPages.add(page);
          _reconcileQueued = true;
        } else {
          _merge(page.messages);
          notifyListeners();
        }

        final next =
            page.latestId ??
            (page.messages.isEmpty ? null : page.messages.last.id);
        if (next == null || next <= cursor) {
          if (page.hasMore) {
            throw StateError(
              'chat delta page did not advance after id $cursor',
            );
          }
        } else {
          cursor = next;
          _reconcileCursor = cursor;
        }
        if (!page.hasMore) break;
        await Future<void>.delayed(Duration.zero);
      }
      _initialError = null;
      _backgroundError = null;
    } on Object catch (error) {
      if (_active && (currentToken == null || _accepts(currentToken))) {
        _backgroundError = error;
      }
    } finally {
      if (currentToken != null) _readTokens.remove(currentToken);
      if (_active) {
        _reconcileFuture = null;
        final repeat = _reconcileQueued && _unresolvedSends == 0;
        if (_unresolvedSends == 0) _reconcileQueued = false;
        if (repeat) unawaited(reconcile());
      }
    }
  }

  Future<void> loadOlder() async {
    final beforeId = _lowestId;
    if (!_active ||
        accountId == null ||
        beforeId == null ||
        !_hasMoreOlder ||
        _loadingOlder) {
      return;
    }

    _loadingOlder = true;
    notifyListeners();
    final token = CancelToken();
    _readTokens.add(token);
    try {
      final page = await _repository.messages(
        matchId: matchId,
        beforeId: beforeId,
        pageSize: latestWindowSize,
        cancelToken: token,
      );
      if (!_accepts(token)) return;
      _merge(page.messages);
      _hasMoreOlder = page.hasMore;
      _backgroundError = null;
      _invalidateThreads();
    } on Object catch (error) {
      if (_accepts(token)) _backgroundError = error;
    } finally {
      if (_accepts(token)) {
        _readTokens.remove(token);
        _loadingOlder = false;
        notifyListeners();
      }
    }
  }

  /// Whether [send] would take this message rather than silently drop it.
  ///
  /// Synchronous and side-effect free, so a caller can check it in the same
  /// turn it sends and only then clear its composer. [send] refuses when the
  /// conversation is not sendable, and a caller that clears regardless
  /// destroys the user's typed text with nothing on screen to explain it.
  bool canAcceptSend(String rawBody) =>
      _active &&
      accountId != null &&
      rawBody.trim().isNotEmpty &&
      !isSending &&
      canSend;

  /// Inserts the pending bubble synchronously, before the returned future can
  /// yield to HTTP. The result is the error to present, or null on success.
  Future<Object?> send(String rawBody) {
    final body = rawBody.trim();
    if (!canAcceptSend(rawBody)) {
      return Future<Object?>.value(null);
    }
    final pending = PendingChatMessage(
      localId: _newMessageId(),
      body: body,
      createdAt: DateTime.now(),
    );
    _pending.add(pending);
    notifyListeners();
    return _deliver(pending);
  }

  Future<Object?> retry(PendingChatMessage failed) {
    if (!_active ||
        accountId == null ||
        isSending ||
        !canSend ||
        !failed.hasFailed) {
      return Future<Object?>.value(null);
    }
    final index = _pending.indexWhere((m) => m.localId == failed.localId);
    if (index < 0) return Future<Object?>.value(null);
    final retrying = failed.retrying();
    _pending[index] = retrying;
    notifyListeners();
    return _deliver(retrying);
  }

  Future<Object?> _deliver(PendingChatMessage pending) async {
    final token = CancelToken();
    _sendTokens.add(token);
    _unresolvedSends++;
    notifyListeners();
    try {
      final acknowledged = await _repository.send(
        matchId: matchId,
        body: pending.body,
        clientMessageId: pending.localId,
        cancelToken: token,
      );
      if (!_active || token.isCancelled) return null;
      if (acknowledged.id <= 0 || acknowledged.matchId != matchId) {
        throw StateError('chat send returned an invalid message identity');
      }

      _pending.removeWhere((m) => m.localId == pending.localId);
      _finishSend();
      _merge(<ChatMessage>[acknowledged]);
      _flushDeferredPages();
      _sendBlock = ChatBlockReason.ok;
      _backgroundError = null;
      // The ACK may have a higher id than an inbound message that this
      // controller has not fetched yet. Reconcile from the independent HTTP
      // cursor after every successful write; the ACK itself never advances it.
      _reconcileQueued = true;
      _invalidateThreads();
      notifyListeners();
      return null;
    } on Object catch (error) {
      if (!_active || token.isCancelled) return null;
      final index = _pending.indexWhere((m) => m.localId == pending.localId);
      if (index >= 0) _pending[index] = _pending[index].failed();
      _finishSend();
      _flushDeferredPages();
      if (error is ApiException && error.statusCode == 402) {
        _sendBlock = ChatBlockReason.parse(error.extras['reason']);
      }
      notifyListeners();
      return error;
    } finally {
      _sendTokens.remove(token);
      if (_active && _unresolvedSends == 0 && _reconcileQueued) {
        unawaited(reconcile());
      }
    }
  }

  void _finishSend() {
    if (_unresolvedSends > 0) _unresolvedSends--;
  }

  static String _newMessageId() {
    final random = Random.secure();
    final bytes = List<int>.generate(16, (_) => random.nextInt(256));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    final hex = bytes.map((b) => b.toRadixString(16).padLeft(2, '0')).join();
    return '${hex.substring(0, 8)}-${hex.substring(8, 12)}-${hex.substring(12, 16)}-${hex.substring(16, 20)}-${hex.substring(20)}';
  }

  void _flushDeferredPages() {
    for (final page in _deferredPages) {
      _merge(page.messages);
    }
    _deferredPages.clear();
  }

  void _merge(Iterable<ChatMessage> incoming) {
    for (final message in incoming) {
      if (message.id > 0 && message.matchId == matchId) {
        _delivered[message.id] = message;
        if (message.senderId == accountId && message.clientMessageId != null) {
          _pending.removeWhere(
            (pending) => pending.localId == message.clientMessageId,
          );
        }
      }
    }
  }

  bool _accepts(CancelToken token) =>
      _active && !token.isCancelled && _readTokens.contains(token);

  void _onLiveChanged() {
    if (_active) unawaited(reconcile());
  }

  @override
  void dispose() {
    if (!_active) return;
    _active = false;
    _unsubscribeLive?.call();
    for (final token in _readTokens) {
      token.cancel('chat controller disposed');
    }
    _readTokens.clear();
    for (final token in _sendTokens) {
      token.cancel('chat controller disposed');
    }
    _sendTokens.clear();
    _deferredPages.clear();
    _pending.clear();
    super.dispose();
  }
}
