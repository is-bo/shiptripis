import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/widgets.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../app/app_state.dart';
import '../../app/router.dart';
import '../../data/repositories.dart';
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

class PushCoordinator extends Notifier<PushRuntimeState>
    with WidgetsBindingObserver {
  late final PushMessaging _messaging;
  final NotificationSocket _socket = NotificationSocket();
  final List<StreamSubscription<dynamic>> _subscriptions = [];
  final Set<String> _seenEventIds = {};
  String? _pendingLocation;
  int? _pendingNotificationId;
  bool _resumed = true;

  @override
  PushRuntimeState build() {
    _messaging = ref.read(pushMessagingProvider);
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
      unawaited(_sessionChanged(next));
    }, fireImmediately: true);
    unawaited(_restoreMessagingState());
    return PushRuntimeState(available: _messaging.available);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _resumed = state == AppLifecycleState.resumed;
    if (_resumed) {
      unawaited(refreshPermission());
      unawaited(_sessionChanged(ref.read(sessionProvider)));
      ref
        ..invalidate(unreadNotificationsProvider)
        ..invalidate(chatThreadsProvider);
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

  Future<void> _sessionChanged(SessionState session) async {
    if (session is SessionSignedIn) {
      if (_resumed) {
        await _socket.start(
          accessToken: ref.read(tokenStoreProvider).readAccess,
          onEvent: _socketEvent,
        );
      }
      await _syncRegistration();
      _openPendingIfReady();
    } else if (session is SessionSignedOut) {
      await _socket.stop();
      _openPendingIfReady();
    }
  }

  Future<void> _syncRegistration() async {
    if (!_messaging.available ||
        ref.read(sessionProvider) is! SessionSignedIn) {
      return;
    }
    try {
      final store = ref.read(tokenStoreProvider);
      final current = await _messaging.token();
      final token = current ?? await store.readPendingPushToken();
      if (token == null || token.isEmpty) return;
      await ref
          .read(pushRepositoryProvider)
          .registerDevice(
            token: token,
            installationId: await store.readOrCreateInstallationId(),
            platform: defaultTargetPlatform == TargetPlatform.iOS
                ? 'ios'
                : 'android',
            appVersion: '',
          );
      await store.writePendingPushToken(null);
      state = state.copyWith(syncFailed: false);
    } on Object {
      state = state.copyWith(syncFailed: true);
    }
  }

  Future<void> _tokenRefreshed(String token) async {
    final store = ref.read(tokenStoreProvider);
    await store.writePendingPushToken(token);
    if (ref.read(sessionProvider) is SessionSignedIn) {
      await _syncRegistration();
    }
  }

  void _foregroundMessage(PushMessage message) {
    _reconcile(message.data);
  }

  void _socketEvent(Map<String, dynamic> event) {
    final data = <String, String>{};
    final eventId = event['event_id'];
    final type = event['type'];
    if (eventId is String) data['event_id'] = eventId;
    if (type is String) data['channel'] = type;
    final payload = event['payload'];
    if (payload is Map) {
      for (final entry in payload.entries) {
        if (entry.value is String || entry.value is num) {
          data['${entry.key}'] = '${entry.value}';
        }
      }
    }
    _reconcile(data);
  }

  void _reconcile(Map<String, String> data) {
    final eventId = data['event_id'];
    if (eventId != null && !_seenEventIds.add(eventId)) return;
    if (_seenEventIds.length > 64) _seenEventIds.remove(_seenEventIds.first);
    ref.invalidate(unreadNotificationsProvider);
    if (data['channel'] == 'chat.message.new') {
      ref.invalidate(chatThreadsProvider);
    }
  }

  void _openMessage(PushMessage message) {
    _reconcile(message.data);
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
