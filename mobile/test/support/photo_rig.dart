/// A rig for the profile photo section over a fake server.
///
/// The real session, repository, client and screen run; only the camera, the
/// native resizer and the phone's "lost picker" store are replaced, because a
/// test runner has none of them. What the server would receive is whatever
/// the fake backend records.
library;

import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker/image_picker.dart';
import 'package:shiptrip/app/profile_photo_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/profile/profile_photo_section.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'fake_api.dart';
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
    this.lostData,
    this.tokens,
    Map<String, dynamic>? photo,
  }) : _photo = photo;

  final FakeBackend backend;
  final ProfilePhotoPicker? picker;
  final ProfilePhotoPreparer? preparer;
  final ProfilePhotoLostData? lostData;
  final FakeTokenStore? tokens;
  final Map<String, dynamic>? _photo;

  late final ProviderContainer container;
  late final FakeTokenStore tokenStore;

  /// The words of the screen's language. Read from the scaffold, which is
  /// there even while a lazy list has not built the photo section yet.
  L l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

  /// A container over the fake server; the session is signed in.
  Future<void> start(WidgetTester tester) async {
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
        profilePhotoLostDataProvider.overrideWithValue(
          lostData ?? () async => null,
        ),
      ],
    );
    addTearDown(container.dispose);
    await tester.runAsync(
      () => container.read(sessionProvider.notifier).restore(),
    );
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
}
