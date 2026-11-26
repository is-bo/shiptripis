/// P3B: getting a picked photo ready is one platform method, and these tests
/// hold the Dart side of it: the call, the answer it checks, the failures it
/// maps, and the type it reads from the bytes.
///
/// What the platform does (decode with a bounded number of pixels, undo all
/// eight EXIF orientations, write an upright JPEG of at most 1024 px with no
/// metadata) is Kotlin in `PhotoPrepare.kt` and Swift in `AppDelegate.swift`.
/// There is no native test setup in the repository and no Android or iOS
/// toolchain on the workstation, so none of it runs here: the device checks it
/// needs are listed in `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`.
library;

import 'dart:io';

import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/media/photo_prepare.dart';

import 'support/photo_rig.dart';

/// What the fake platform is asked, in order.
class _Calls {
  final methods = <String>[];
  final arguments = <Object?>[];
}

_Calls _answerWith(
  WidgetTester tester,
  Future<Object?> Function(MethodCall call) handler,
) {
  final calls = _Calls();
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    photoPrepareChannel,
    (call) {
      calls.methods.add(call.method);
      calls.arguments.add(call.arguments);
      return handler(call);
    },
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      photoPrepareChannel,
      null,
    ),
  );
  return calls;
}

void main() {
  group('the platform method', () {
    testWidgets(
      'is called once, as `prepare` with the path, and its answer is used',
      (tester) async {
        final calls = _answerWith(
          tester,
          (_) async => '/cache/wassla-photo-1.jpg',
        );

        final prepared = await prepareProfilePhoto('/picked/IMG_0001.heic');

        expect(prepared, '/cache/wassla-photo-1.jpg');
        expect(calls.methods, ['prepare']);
        expect(calls.arguments, [
          {'path': '/picked/IMG_0001.heic'},
        ]);
      },
    );

    testWidgets('the channel is the one the native side registers', (
      tester,
    ) async {
      expect(photoPrepareChannel.name, 'wassla/photo_prepare');
    });

    testWidgets('a source that is gone is a file error', (tester) async {
      _answerWith(
        tester,
        (_) async => throw PlatformException(code: 'not_found'),
      );

      await expectLater(
        prepareProfilePhoto('/picked/gone.jpg'),
        throwsA(isA<FileSystemException>()),
      );
    });

    for (final code in ['unsupported', 'failed', 'bad_arguments', 'anything']) {
      testWidgets('"$code" from the platform is an unsupported photo', (
        tester,
      ) async {
        _answerWith(tester, (_) async => throw PlatformException(code: code));

        await expectLater(
          prepareProfilePhoto('/picked/odd.heic'),
          throwsA(isA<UnsupportedPhoto>()),
        );
      });
    }

    testWidgets('a phone with no such method is an unsupported photo', (
      tester,
    ) async {
      _answerWith(tester, (_) async => throw MissingPluginException());

      await expectLater(
        prepareProfilePhoto('/picked/odd.heic'),
        throwsA(isA<UnsupportedPhoto>()),
      );
    });

    for (final answer in [null, '']) {
      testWidgets(
        'an answer of ${answer == null ? 'nothing' : 'an empty path'} is refused',
        (tester) async {
          _answerWith(tester, (_) async => answer);

          await expectLater(
            prepareProfilePhoto('/picked/odd.heic'),
            throwsA(isA<UnsupportedPhoto>()),
          );
        },
      );
    }
  });

  group('a photo is typed by its first bytes', () {
    test('JPEG, PNG and WebP are read from the signature', () {
      expect(sniffImageType(jpegBytes), 'image/jpeg');
      expect(sniffImageType(pngBytes), 'image/png');
      expect(
        sniffImageType([
          ...'RIFF'.codeUnits,
          0,
          0,
          0,
          0,
          ...'WEBP'.codeUnits,
          ...List.filled(8, 0),
        ]),
        'image/webp',
      );
    });

    test('anything else is not an image the server accepts', () {
      expect(sniffImageType(gifBytes), isNull);
      expect(sniffImageType('%PDF-1.7'.codeUnits), isNull);
      expect(sniffImageType(const []), isNull);
      expect(sniffImageType(const [0xFF, 0xD8]), isNull, reason: 'too short');
      // RIFF that is not WebP (a WAV).
      expect(
        sniffImageType([...'RIFF'.codeUnits, 0, 0, 0, 0, ...'WAVE'.codeUnits]),
        isNull,
      );
    });

    test('the extension follows the type', () {
      expect(extensionFor('image/jpeg'), 'jpg');
      expect(extensionFor('image/png'), 'png');
      expect(extensionFor('image/webp'), 'webp');
    });
  });
}
