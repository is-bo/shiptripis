/// A rig for the profile photo section over a fake server.
///
/// The real session, repository, client and screen run; only the camera, the
/// native resizer and the phone's "lost picker" store are replaced, because a
/// test runner has none of them. What the server would receive is whatever
/// the fake backend records.
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/auth/social_sign_in.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/media/pick_guard.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'fake_api.dart';
import 'fake_image_picker.dart';
import 'fake_social_sign_in.dart';
import 'harness.dart';

const photoPut = '/api/me/photo';

Map<String, dynamic> photoActive([String version = 'v1']) => {
  'state': 'active',
  'url': 'https://media.test/profile-photos/abc.jpg?sig=1',
  'version': version,
  'removed_at': null,
  'reason': null,
};

/// An active photo whose address the server could not sign.
Map<String, dynamic> photoActiveUnsigned([String version = 'v1']) => {
  'state': 'active',
  'url': null,
  'version': version,
  'removed_at': null,
  'reason': null,
};

Map<String, dynamic> photoRemoved({String? reason = 'Not a photo of you.'}) => {
  'state': 'removed',
  'url': null,
  'version': 'v0',
  'removed_at': '2026-11-24T10:00:00Z',
  'reason': reason,
};

/// The first bytes of a JPEG, a PNG and a GIF: enough for a type check.
final Uint8List jpegBytes = Uint8List.fromList([
  0xFF, 0xD8, 0xFF, 0xE0, ...List.filled(60, 0), //
]);
final Uint8List pngBytes = Uint8List.fromList([
  0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, ...List.filled(60, 0), //
]);
final Uint8List gifBytes = Uint8List.fromList([
  ...'GIF89a'.codeUnits, ...List.filled(60, 0), //
]);

/// A real file in a temporary folder that goes away with the test.
String sourceFile({String name = 'me.jpg', Uint8List? bytes}) {
  final dir = Directory.systemTemp.createTempSync('shiptrip-profile-photo');
  addTearDown(() {
    try {
      dir.deleteSync(recursive: true);
    } on FileSystemException {
      // The OS reclaims it; the assertions have already run.
    }
  });
  final file = File('${dir.path}${Platform.pathSeparator}$name');
  file.writeAsBytesSync(bytes ?? jpegBytes);
  return file.path;
}

var _prepared = 0;

/// The native resizer, as a test sees it: a new file for every call, holding
/// [bytes], with [name] (the suffix the real one keeps, whatever it writes).
ProfilePhotoPreparer preparerWriting(
  Uint8List bytes, {
  String name = 'prepared.jpg',
  List<String>? calls,
  List<String>? outputs,
}) => (source) async {
  calls?.add(source);
  final dir = Directory.systemTemp.createTempSync('shiptrip-prepared');
  final file = File('${dir.path}${Platform.pathSeparator}${_prepared++}-$name');
  await file.writeAsBytes(bytes);
  outputs?.add(file.path);
  return file.path;
};

ProfilePhotoPicker pickerReturning(String path, {List<ImageSource>? calls}) =>
    (source) async {
      calls?.add(source);
      return XFile(path, name: path.split(Platform.pathSeparator).last);
    };

/// Lets real I/O (the file reads) and fake time both move, until [until]
/// holds.
Future<void> untilReached(
  WidgetTester tester,
  bool Function() until, {
  int maxFrames = 200,
}) async {
  for (var frame = 0; frame < maxFrames; frame++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 10)),
    );
    await tester.pump(const Duration(milliseconds: 16));
    if (until()) return;
  }
  fail('the screen never reached the state the test was waiting for');
}

Finder photoButton(String label) => find.widgetWithText(AppButton, label);

bool photoButtonEnabled(WidgetTester tester, String label) =>
    tester.widget<AppButton>(photoButton(label)).onPressed != null;

class PhotoRig {
  PhotoRig(
    this.backend, {
    this.picker,
    this.preparer,
    this.imagePicker,
    this.tokens,
    this.clock,
    Map<String, dynamic>? photo,
  }) : _photo = photo;

  final FakeBackend backend;
  final ProfilePhotoPicker? picker;
  final ProfilePhotoPreparer? preparer;

  /// The app's one `ImagePicker`, with what a phone that ended the app would
  /// have kept. A fresh one when null.
  final FakeImagePicker? imagePicker;
  final FakeTokenStore? tokens;

  /// The time the pick guard measures its suspicion window by; the real clock
  /// when null.
  final DateTime Function()? clock;
  final Map<String, dynamic>? _photo;

  late final ProviderContainer container;
  late final FakeTokenStore tokenStore;

  /// The words of the screen's language. Read from the scaffold, which is
  /// there even while a lazy list has not built the photo section yet.
  L l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

  /// A container over the fake server; the session is signed in. With
  /// [restore] false the session is left to start itself (a launch whose
  /// `/api/me` a test may hold back).
  Future<void> start(WidgetTester tester, {bool restore = true}) async {
    backend.on('GET', '/api/me', FakeResponse(200, meFixture(photo: _photo)));
    tokenStore = tokens ?? FakeTokenStore();
    container = ProviderContainer(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokenStore),
        apiClientProvider.overrideWithValue(apiClientFor(backend, tokenStore)),
        if (picker != null)
          profilePhotoPickerProvider.overrideWithValue(picker!),
        profilePhotoPreparerProvider.overrideWithValue(
          preparer ?? preparerWriting(jpegBytes),
        ),
        imagePickerProvider.overrideWithValue(imagePicker ?? FakeImagePicker()),
        if (clock != null)
          pickGuardProvider.overrideWith((ref) => PickGuard(ref, now: clock)),
      ],
    );
    addTearDown(container.dispose);
    if (restore) {
      await tester.runAsync(
        () => container.read(sessionProvider.notifier).restore(),
      );
    }
  }

  Future<void> pump(
    WidgetTester tester, {
    Locale locale = const Locale('en'),
    DeviceProfile device = DeviceProfile.android,
    List<Widget> below = const [],
  }) async {
    await start(tester);
    // A screen left from an earlier pump would keep its state (and so skip its
    // start-up work) under the new container: begin from nothing.
    await tester.pumpWidget(const SizedBox.shrink());
    await pumpApp(
      tester,
      Scaffold(
        body: Consumer(
          builder: (context, ref, _) => ListView(
            padding: const EdgeInsets.all(20),
            children: [
              ProfilePhotoSection(account: ref.watch(accountProvider)!),
              ...below,
            ],
          ),
        ),
      ),
      container: container,
      locale: locale,
      device: device,
    );
  }

  Account get account => container.read(accountProvider)!;

  /// The whole app, on its real router and its real tab shell with the bottom
  /// navigation, opened on Profile. [locale] is the language the app was last
  /// set to; [device] sets the window, its insets and its text size.
  Future<void> pumpRealApp(
    WidgetTester tester, {
    Locale locale = const Locale('en'),
    DeviceProfile device = DeviceProfile.android,
  }) async {
    // A screen left from an earlier pump would keep its state: begin from
    // nothing.
    await tester.pumpWidget(const SizedBox.shrink());
    backend
      ..on('GET', '/api/me', FakeResponse(200, meFixture(photo: _photo)))
      ..emptyDiscovery()
      ..fallback ??= _memberRead;
    tokenStore = tokens ?? _AppStore(locale: locale.languageCode);
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = device.size;
    tester.view.padding = FakeViewPadding(
      top: device.viewPadding.top,
      bottom: device.viewPadding.bottom,
      left: device.viewPadding.left,
      right: device.viewPadding.right,
    );
    tester.view.viewPadding = tester.view.padding;
    tester.platformDispatcher.textScaleFactorTestValue = device.textScale;
    addTearDown(() {
      tester.view.reset();
      tester.platformDispatcher.clearTextScaleFactorTestValue();
    });
    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokenStore),
          apiClientProvider.overrideWithValue(
            apiClientFor(backend, tokenStore),
          ),
          notificationSocketProvider.overrideWithValue(
            NotificationSocket(connector: (_, _) async => _IdleConnection()),
          ),
          socialSignInProvider.overrideWithValue(FakeSocialSignIn()),
          if (picker != null)
            profilePhotoPickerProvider.overrideWithValue(picker!),
          profilePhotoPreparerProvider.overrideWithValue(
            preparer ?? preparerWriting(jpegBytes),
          ),
          imagePickerProvider.overrideWithValue(
            imagePicker ?? FakeImagePicker(),
          ),
        ],
        child: const ShipTripApp(),
      ),
    );
    await _settle(tester);
    container = ProviderScope.containerOf(
      tester.element(find.byType(ShipTripApp)),
    );
    container.read(routerProvider).goNamed(Routes.profile);
    await _settle(tester);
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox.shrink());
      await tester.pump(const Duration(seconds: 10));
    });
  }

  static Future<void> _settle(WidgetTester tester) async {
    for (var i = 0; i < 30; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }
  }

  static FakeResponse _memberRead(RecordedRequest r) {
    if (r.path == '/api/notifications' || r.path == '/api/deals') {
      return const FakeResponse(200, {
        'count': 0,
        'next': null,
        'previous': null,
        'results': <Object>[],
      });
    }
    if (r.path == '/api/notifications/unread-count') {
      return const FakeResponse(200, {'unread': 0});
    }
    if (r.path.contains('count')) return const FakeResponse(200, {'count': 0});
    return const FakeResponse(200, <Object>[]);
  }
}

/// A keystore for the whole app: what the shell asks of it at start-up.
class _AppStore extends FakeTokenStore {
  _AppStore({super.locale});

  @override
  Future<String?> readAccess() async => 'access-token';

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
}

class _IdleConnection implements NotificationSocketConnection {
  final _controller = StreamController<dynamic>();

  @override
  Stream<dynamic> get stream => _controller.stream;

  @override
  Future<void> close() async {
    if (!_controller.isClosed) await _controller.close();
  }
}

/// The press of a pick, as a screen makes it: the member is captured first
/// (`SessionNotifier.beginAction`), then the controller is asked. Nothing is
/// asked when nobody can begin an action (not signed in, or a sign-in is
/// replacing the published member).
Future<bool> pickPhoto(ProviderContainer container, ImageSource source) async {
  final scope = container.read(sessionProvider.notifier).beginAction();
  if (scope == null) return false;
  return container.read(profilePhotoProvider.notifier).pick(source, scope);
}

/// The press of a removal; see [pickPhoto]. Null when nothing could begin.
Future<ProfilePhotoRemoval?> removeOwnPhoto(
  ProviderContainer container, {
  String shownVersion = 'v1',
}) async {
  final scope = container.read(sessionProvider.notifier).beginAction();
  if (scope == null) return null;
  return container
      .read(profilePhotoProvider.notifier)
      .remove(scope, shownVersion: shownVersion);
}
