import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

import 'app/app.dart';
import 'core/format/locale_formats.dart';
import 'core/push/push_messaging.dart';

Future<void> main() async {
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

  final pushMessaging = await FirebasePushMessaging.initialize();
  if (pushMessaging.available) {
    FirebaseMessaging.onBackgroundMessage(shipTripFirebaseBackgroundHandler);
  }

  runApp(
    ProviderScope(
      overrides: [pushMessagingProvider.overrideWithValue(pushMessaging)],
      child: const ShipTripApp(),
    ),
  );
}
