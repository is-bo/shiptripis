import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'app/app.dart';
import 'core/format/locale_formats.dart';
import 'core/env/app_config.dart';
import 'core/push/push_messaging.dart';
import 'core/session/session.dart';
import 'core/session/session_core.dart';

Future<void> main() async {
  AppConfig.validate();
  WidgetsFlutterBinding.ensureInitialized();

  // Edge-to-edge, per Material 3 and the iOS safe-area contract. The bars are
  // transparent and every screen lays out inside the real insets rather than
  // guessing at their height — see design/layout/app_scaffold.dart.
  await SystemChrome.setEnabledSystemUIMode(
    SystemUiMode.edgeToEdge,
    overlays: SystemUiOverlay.values,
  );
  SystemChrome.setSystemUIOverlayStyle(
    const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      systemNavigationBarColor: Colors.transparent,
      systemNavigationBarDividerColor: Colors.transparent,
    ),
  );

  // Month names and number patterns for fr and ar_DZ. Must land before the
  // first DateFormat call, so it is awaited rather than fired and forgotten.
  await LocaleFormats.ensureInitialized();

  // Push is not needed to paint anything, so Firebase starts after the first
  // frame instead of in front of it (K5). The coordinator waits on it and
  // treats a failed start as "push unavailable", as it always has.
  final pushMessaging = DeferredPushMessaging();

  // The one session core: created here, outside every provider container.
  final session = SessionCore(
    deletePushToken: () async {
      if ((await pushMessaging.ready).available) {
        await FirebaseMessaging.instance.deleteToken();
      }
    },
  );
  AppLifecycleListener(onResume: session.resumed);

  runApp(
    ProviderScope(
      retry: appRetry,
      overrides: [
        pushMessagingProvider.overrideWithValue(pushMessaging),
        sessionCoreProvider.overrideWithValue(session),
      ],
      child: const ShipTripApp(),
    ),
  );

  pushMessaging.startAfterFirstFrame(() async {
    final messaging = await FirebasePushMessaging.initialize();
    // Registered in the same turn as the successful start, as before. It
    // needs only the method channel, and the handle it stores is what a
    // terminated app is woken with, so a later registration loses nothing: a
    // fresh install has no FCM token for anyone to send to until this start.
    if (messaging.available) {
      FirebaseMessaging.onBackgroundMessage(shipTripFirebaseBackgroundHandler);
    }
    return messaging;
  });
}
