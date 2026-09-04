import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';

/// Public Firebase client identifiers supplied by the release build.
///
/// No checked-in placeholder project is used. A build without the complete
/// platform tuple keeps push disabled while the rest of ShipTrip works.
abstract final class ShipTripFirebaseOptions {
  static const apiKey = String.fromEnvironment('FIREBASE_API_KEY');
  static const projectId = String.fromEnvironment('FIREBASE_PROJECT_ID');
  static const messagingSenderId = String.fromEnvironment(
    'FIREBASE_MESSAGING_SENDER_ID',
  );
  static const androidAppId = String.fromEnvironment('FIREBASE_ANDROID_APP_ID');
  static const iosAppId = String.fromEnvironment('FIREBASE_IOS_APP_ID');
  static const iosBundleId = String.fromEnvironment(
    'FIREBASE_IOS_BUNDLE_ID',
    defaultValue: 'com.shiptrip.shiptrip',
  );

  static FirebaseOptions? get current {
    if (apiKey.isEmpty || projectId.isEmpty || messagingSenderId.isEmpty) {
      return null;
    }
    if (!kIsWeb &&
        defaultTargetPlatform == TargetPlatform.android &&
        androidAppId.isNotEmpty) {
      return const FirebaseOptions(
        apiKey: apiKey,
        appId: androidAppId,
        messagingSenderId: messagingSenderId,
        projectId: projectId,
      );
    }
    if (!kIsWeb &&
        defaultTargetPlatform == TargetPlatform.iOS &&
        iosAppId.isNotEmpty) {
      return const FirebaseOptions(
        apiKey: apiKey,
        appId: iosAppId,
        messagingSenderId: messagingSenderId,
        projectId: projectId,
        iosBundleId: iosBundleId,
      );
    }
    return null;
  }
}
