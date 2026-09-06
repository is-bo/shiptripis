import 'dart:async';

import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'firebase_options.dart';

enum PushPermission {
  unavailable,
  notDetermined,
  deniedRequestable,
  settingsRequired,
  authorized,
  provisional,
}

enum PushAvailability {
  available,
  configurationIncomplete,
  initializationFailed,
}

class PushMessage {
  const PushMessage({required this.data, this.messageId});

  factory PushMessage.fromRemote(RemoteMessage message) => PushMessage(
    data: Map<String, String>.from(message.data),
    messageId: message.messageId,
  );

  final Map<String, String> data;
  final String? messageId;
}

abstract interface class PushMessaging {
  bool get available;
  PushAvailability get availability;
  Stream<String> get tokenRefresh;
  Stream<PushMessage> get foregroundMessages;
  Stream<PushMessage> get openedMessages;
  Future<String?> token();
  Future<PushMessage?> initialMessage();
  Future<PushPermission> permission();
  Future<PushPermission> requestPermission();
}

class DisabledPushMessaging implements PushMessaging {
  const DisabledPushMessaging({
    this.availability = PushAvailability.configurationIncomplete,
  });

  @override
  final PushAvailability availability;

  @override
  bool get available => false;
  @override
  Stream<PushMessage> get foregroundMessages => const Stream.empty();
  @override
  Stream<PushMessage> get openedMessages => const Stream.empty();
  @override
  Stream<String> get tokenRefresh => const Stream.empty();
  @override
  Future<PushMessage?> initialMessage() async => null;
  @override
  Future<PushPermission> permission() async => PushPermission.unavailable;
  @override
  Future<PushPermission> requestPermission() async =>
      PushPermission.unavailable;
  @override
  Future<String?> token() async => null;
}

class FirebasePushMessaging implements PushMessaging {
  FirebasePushMessaging(this._messaging);

  final FirebaseMessaging _messaging;

  static Future<PushMessaging> initialize() async {
    final options = ShipTripFirebaseOptions.current;
    if (options == null) {
      return const DisabledPushMessaging(
        availability: PushAvailability.configurationIncomplete,
      );
    }
    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp(options: options);
      }
      final messaging = FirebaseMessaging.instance;
      // Foreground delivery updates the in-app source of truth. The app does
      // not ask iOS to display a second banner for the same message.
      await messaging.setForegroundNotificationPresentationOptions(
        alert: false,
        badge: false,
        sound: false,
      );
      return FirebasePushMessaging(messaging);
    } on Object {
      return const DisabledPushMessaging(
        availability: PushAvailability.initializationFailed,
      );
    }
  }

  @override
  bool get available => true;

  @override
  PushAvailability get availability => PushAvailability.available;

  @override
  Stream<PushMessage> get foregroundMessages =>
      FirebaseMessaging.onMessage.map(PushMessage.fromRemote);

  @override
  Stream<PushMessage> get openedMessages =>
      FirebaseMessaging.onMessageOpenedApp.map(PushMessage.fromRemote);

  @override
  Stream<String> get tokenRefresh => _messaging.onTokenRefresh;

  @override
  Future<String?> token() => _messaging.getToken();

  @override
  Future<PushMessage?> initialMessage() async {
    final message = await _messaging.getInitialMessage();
    return message == null ? null : PushMessage.fromRemote(message);
  }

  @override
  Future<PushPermission> permission() async => _permission(
    (await _messaging.getNotificationSettings()).authorizationStatus,
  );

  @override
  Future<PushPermission> requestPermission() async {
    final settings = await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
      provisional: false,
    );
    return _permission(settings.authorizationStatus);
  }

  static Future<PushPermission> _permission(AuthorizationStatus status) async {
    var androidRuntimePermissionSupported = false;
    if (status == AuthorizationStatus.denied &&
        defaultTargetPlatform == TargetPlatform.android) {
      androidRuntimePermissionSupported =
          await _androidRuntimePermissionSupported();
    }
    return classifyPushPermission(
      status,
      platform: defaultTargetPlatform,
      androidRuntimePermissionSupported: androidRuntimePermissionSupported,
    );
  }
}

const _notificationPermissionChannel = MethodChannel(
  'com.shiptrip.shiptrip/notification_permission',
);

Future<bool> _androidRuntimePermissionSupported() async {
  try {
    return await _notificationPermissionChannel.invokeMethod<bool>(
          'runtimePermissionSupported',
        ) ??
        false;
  } on PlatformException {
    return false;
  } on MissingPluginException {
    return false;
  }
}

@visibleForTesting
PushPermission classifyPushPermission(
  AuthorizationStatus status, {
  required TargetPlatform platform,
  required bool androidRuntimePermissionSupported,
}) => switch (status) {
  AuthorizationStatus.authorized => PushPermission.authorized,
  AuthorizationStatus.provisional => PushPermission.provisional,
  AuthorizationStatus.notDetermined => PushPermission.notDetermined,
  AuthorizationStatus.deniedPermanently => PushPermission.settingsRequired,
  AuthorizationStatus.denied =>
    platform == TargetPlatform.android && androidRuntimePermissionSupported
        ? PushPermission.deniedRequestable
        : PushPermission.settingsRequired,
};

final pushMessagingProvider = Provider<PushMessaging>(
  (_) => const DisabledPushMessaging(),
);

@pragma('vm:entry-point')
Future<void> shipTripFirebaseBackgroundHandler(RemoteMessage _) async {
  final options = ShipTripFirebaseOptions.current;
  if (options == null) return;
  if (Firebase.apps.isEmpty) {
    await Firebase.initializeApp(options: options);
  }
  // Notification payloads are rendered by the OS. Authoritative inbox state
  // is reconciled when the app resumes or the user taps the notification.
}
