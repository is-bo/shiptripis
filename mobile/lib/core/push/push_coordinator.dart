import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/router.dart';
import '../../data/repositories.dart';
import '../live/live_updates.dart';
import '../session/session.dart';
import 'notification_socket.dart';
import 'push_messaging.dart';

@immutable
class PushRuntimeState {
  const PushRuntimeState({
    required this.available,
    this.permission = PushPermission.unavailable,
    this.syncFailed = false,
  });

  final bool available;
  final PushPermission permission;
  final bool syncFailed;

  PushRuntimeState copyWith({PushPermission? permission, bool? syncFailed}) =>
      PushRuntimeState(
        available: available,
        permission: permission ?? this.permission,
        syncFailed: syncFailed ?? this.syncFailed,
      );
}

final pushCoordinatorProvider =
    NotifierProvider<PushCoordinator, PushRuntimeState>(PushCoordinator.new);

final notificationSocketProvider = Provider<NotificationSocket>(
  (ref) => NotificationSocket(),
);

class PushCoordinator extends Notifier<PushRuntimeState>
    with WidgetsBindingObserver {
  late final PushMessaging _messaging;
  late final NotificationSocket _socket;
  late final LiveUpdates _live;
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  String? _pendingLocation;
  int? _pendingNotificationId;
  int? _accountId;
  int _sessionGeneration = 0;
  bool _resumed = true;

  @override
  PushRuntimeState build() {
    _messaging = ref.read(pushMessagingProvider);
    _socket = ref.read(notificationSocketProvider);
    _live = ref.read(liveUpdatesProvider);
    _resumed =
        WidgetsBinding.instance.lifecycleState == null ||
        WidgetsBinding.instance.lifecycleState == AppLifecycleState.resumed;
    WidgetsBinding.instance.addObserver(this);
    ref.onDispose(() {
      WidgetsBinding.instance.removeObserver(this);
      for (final subscription in _subscriptions) {
        unawaited(subscription.cancel());
      }
      unawaited(_socket.stop());
    });

    _subscriptions
      ..add(_messaging.tokenRefresh.listen(_tokenRefreshed))
      ..add(_messaging.foregroundMessages.listen(_foregroundMessage))
      ..add(_messaging.openedMessages.listen(_openMessage));
    ref.listen<SessionState>(sessionProvider, (_, next) {
      _sessionChanged(next);
    }, fireImmediately: true);
    final removeAccountRefresh = _live.register(
      const LiveResource.account(),
      () => unawaited(ref.read(sessionProvider.notifier).refreshAccount()),
    );
    ref.onDispose(removeAccountRefresh);
    unawaited(_restoreMessagingState());
    return PushRuntimeState(available: _messaging.available);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _resumed = state == AppLifecycleState.resumed;
    if (_resumed) {
      unawaited(refreshPermission());
      _reconcileCurrentScope();
      _startSocketsIfSignedIn();
    } else {
      unawaited(_socket.stop());
    }
  }

  Future<PushPermission> requestPermission() async {
    final permission = await _messaging.requestPermission();
    state = state.copyWith(permission: permission);
    if (permission == PushPermission.authorized ||
        permission == PushPermission.provisional) {
      await _syncRegistration();
    }
    return permission;
  }

  Future<void> refreshPermission() async {
    state = state.copyWith(permission: await _messaging.permission());
  }

  Future<void> _restoreMessagingState() async {
    if (!_messaging.available) return;
    state = state.copyWith(permission: await _messaging.permission());
    final initial = await _messaging.initialMessage();
    if (initial != null) _openMessage(initial);
  }

  void _sessionChanged(SessionState session) {
    final nextAccountId = switch (session) {
      SessionSignedIn(:final account) => account.id,
      _ => null,
    };
    if (nextAccountId == _accountId) {
      if (session is! SessionRestoring) _openPendingIfReady();
      return;
    }

    _accountId = nextAccountId;
    _sessionGeneration++;
    _live.bindAccount(nextAccountId);
    unawaited(_socket.stop());
    if (session is SessionSignedIn) {
      _startSocketsIfSignedIn();
      unawaited(_syncRegistration(expectedGeneration: _sessionGeneration));
      _openPendingIfReady();
    } else if (session is SessionSignedOut) {
      _openPendingIfReady();
    }
  }

  void _startSocketsIfSignedIn() {
    if (!_resumed || ref.read(sessionProvider) is! SessionSignedIn) return;
    final generation = _sessionGeneration;
    unawaited(
      _socket.start(
        accessToken: _socketAccessToken,
        onEvent: (event, _) {
          if (generation != _sessionGeneration) return;
          _live.ingest(event, source: LiveEventSource.websocket);
        },
        onConnected: (_) {
          if (generation != _sessionGeneration) return;
          _reconcileCurrentScope();
        },
      ),
    );
  }

  Future<String?> _socketAccessToken({required bool refresh}) async {
    if (ref.read(sessionProvider) is! SessionSignedIn) return null;
    if (refresh) {
      try {
        // A normal authenticated read enters the same 401/single-flight
        // interceptor as every screen. It refreshes an expired access token
        // and ends a terminally expired session instead of looping a rejected
        // WS bearer forever.
        await ref.read(authRepositoryProvider).me();
      } on Object {
        return null;
      }
      if (ref.read(sessionProvider) is! SessionSignedIn) return null;
    }
    return ref.read(tokenStoreProvider).readAccess();
  }

  void _reconcileCurrentScope() {
    final router = ref.read(routerProvider);
    _live.reconcileScope(
      liveResourcesForLocation(
        router.routerDelegate.currentConfiguration.uri.toString(),
      ),
    );
  }

  Future<void> _syncRegistration({int? expectedGeneration}) async {
    final generation = expectedGeneration ?? _sessionGeneration;
    if (!_messaging.available ||
        ref.read(sessionProvider) is! SessionSignedIn) {
      return;
    }
    try {
      final store = ref.read(tokenStoreProvider);
      final current = await _messaging.token();
      if (generation != _sessionGeneration ||
          ref.read(sessionProvider) is! SessionSignedIn) {
        return;
      }
      final token = current ?? await store.readPendingPushToken();
      if (generation != _sessionGeneration ||
          ref.read(sessionProvider) is! SessionSignedIn) {
        return;
      }
      if (token == null || token.isEmpty) return;
      final installationId = await store.readOrCreateInstallationId();
      if (generation != _sessionGeneration ||
          ref.read(sessionProvider) is! SessionSignedIn) {
        return;
      }
      await ref
          .read(pushRepositoryProvider)
          .registerDevice(
            token: token,
            installationId: installationId,
            platform: defaultTargetPlatform == TargetPlatform.iOS
                ? 'ios'
                : 'android',
            appVersion: '',
          );
      if (generation != _sessionGeneration ||
          ref.read(sessionProvider) is! SessionSignedIn) {
        return;
      }
      await store.writePendingPushToken(null);
      if (generation != _sessionGeneration ||
          ref.read(sessionProvider) is! SessionSignedIn) {
        return;
      }
      state = state.copyWith(syncFailed: false);
    } on Object {
      if (generation != _sessionGeneration) {
        return;
      }
      state = state.copyWith(syncFailed: true);
    }
  }

  Future<void> _tokenRefreshed(String token) async {
    final generation = _sessionGeneration;
    final store = ref.read(tokenStoreProvider);
    await store.writePendingPushToken(token);
    if (generation == _sessionGeneration &&
        ref.read(sessionProvider) is SessionSignedIn) {
      await _syncRegistration(expectedGeneration: generation);
    }
  }

  void _foregroundMessage(PushMessage message) {
    _live.ingest(message.data, source: LiveEventSource.firebase);
  }

  void _openMessage(PushMessage message) {
    _live.ingest(message.data, source: LiveEventSource.firebase);
    final location = pushLocation(message.data);
    if (location == null) return;
    _pendingLocation = location;
    final notificationId = int.tryParse(message.data['notification_id'] ?? '');
    if (notificationId != null && notificationId > 0) {
      _pendingNotificationId = notificationId;
    }
    _openPendingIfReady();
  }

  void _openPendingIfReady() {
    final location = _pendingLocation;
    if (location == null) return;
    final session = ref.read(sessionProvider);
    if (session is SessionRestoring) return;
    final router = ref.read(routerProvider);
    if (session is SessionSignedOut) {
      router.go(
        Uri(
          path: '/auth/sign-in',
          queryParameters: {'next': location},
        ).toString(),
      );
      return;
    }
    if (session is SessionSignedIn) {
      _pendingLocation = null;
      final notificationId = _pendingNotificationId;
      _pendingNotificationId = null;
      router.go(location);
      if (notificationId != null) {
        unawaited(
          ref
              .read(notificationRepositoryProvider)
              .markRead(notificationId)
              .catchError((Object _) {}),
        );
      }
    }
  }
}

String? pushLocation(Map<String, String> data) {
  int? positive(String key) {
    final value = int.tryParse(data[key] ?? '');
    return value != null && value > 0 ? value : null;
  }

  final channel = data['channel'] ?? '';
  final matchId = positive('match_id');
  if (channel == 'chat.message.new' && matchId != null) {
    return '/chat/thread/$matchId';
  }
  final disputeId = positive('dispute_id');
  if (disputeId != null) return '/disputes/$disputeId';
  final dealId = positive('deal_id');
  if (dealId != null) return '/deals/$dealId';
  final journeyId = positive('journey_id') ?? positive('trip_id');
  if (journeyId != null) return '/journeys/$journeyId';
  final requestId = positive('request_id') ?? positive('parcel_id');
  if (requestId != null) return '/requests/$requestId';
  if (matchId != null) return '/matches/$matchId';
  if (channel == 'kyc.status_changed') return '/kyc';
  if (channel.startsWith('payment.') || channel.startsWith('payout.')) {
    return '/profile/payouts';
  }
  return channel.isEmpty ? null : '/notifications';
}
