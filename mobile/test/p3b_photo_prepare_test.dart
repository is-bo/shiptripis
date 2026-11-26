/// P3B: getting a picked photo ready is one platform method, and these tests
/// hold the Dart side of it: the call, the answer it checks, the failures it
/// maps (a decoder's refusal is not a failed preparation), and the type it
/// reads from the bytes.
///
/// What the platform does (decode with a bounded number of pixels, undo all
/// eight EXIF orientations, write an upright JPEG of at most 1024 px with no
/// metadata) is Kotlin in `PhotoPrepare.kt` and Swift in `AppDelegate.swift`.
/// There is no native test setup in the repository, and no Android or iOS
/// toolchain on the workstation (no JDK 17, Android SDK or Xcode, so Gradle
/// cannot run a Kotlin unit test here), so none of it runs here. The numbers it
/// computes are pure functions in Kotlin (`PhotoGeometry`), and the last group
/// of this file is their **executable specification**: the same arithmetic
/// written in Dart, with the cases the review named. It proves the arithmetic is
/// right, not that the Kotlin matches it; the device checks that do are listed
/// in `docs/PHASE_P3B_PROFILE_PHOTOS_APP.md`.
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

    testWidgets('only a decoder\'s refusal is an unsupported photo', (
      tester,
    ) async {
      _answerWith(
        tester,
        (_) async => throw PlatformException(code: 'unsupported'),
      );

      await expectLater(
        prepareProfilePhoto('/picked/odd.heic'),
        throwsA(isA<UnsupportedPhoto>()),
      );
    });

    for (final code in ['failed', 'bad_arguments', 'anything']) {
      testWidgets('"$code" from the platform is a failed preparation', (
        tester,
      ) async {
        _answerWith(tester, (_) async => throw PlatformException(code: code));

        await expectLater(
          prepareProfilePhoto('/picked/odd.heic'),
          throwsA(isA<PhotoPrepareFailed>()),
        );
      });
    }

    testWidgets('a phone with no such method is a failed preparation', (
      tester,
    ) async {
      _answerWith(tester, (_) async => throw MissingPluginException());

      await expectLater(
        prepareProfilePhoto('/picked/odd.heic'),
        throwsA(isA<PhotoPrepareFailed>()),
      );
    });

    for (final answer in [null, '']) {
      testWidgets(
        'an answer of ${answer == null ? 'nothing' : 'an empty path'} is a failed preparation',
        (tester) async {
          _answerWith(tester, (_) async => answer);

          await expectLater(
            prepareProfilePhoto('/picked/odd.heic'),
            throwsA(isA<PhotoPrepareFailed>()),
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

  group(
    'the arithmetic of PhotoPrepare.kt, as an executable specification',
    () {
      // The same functions as `PhotoGeometry` in Kotlin, written over doubles.
      // `Math.round(float)` rounds half up, which is floor(x + 0.5).
      const maxEdge = 1024;
      const maxDecodedPixels = 6000000;
      const maxSample = 1024;

      int sampleSize(int width, int height) {
        var sample = 1;
        while (sample < maxSample &&
            (width ~/ sample) * (height ~/ sample) > maxDecodedPixels) {
          sample *= 2;
        }
        return sample;
      }

      int? nextSample(int sample) => sample >= maxSample ? null : sample * 2;

      double fitScale(int width, int height) {
        final longEdge = width > height ? width : height;
        return longEdge <= maxEdge ? 1 : maxEdge / longEdge;
      }

      bool swapsAxes(int orientation) => orientation >= 5 && orientation <= 8;

      (int, int) outputSize(int width, int height, int orientation) {
        final upright = swapsAxes(orientation)
            ? (height, width)
            : (width, height);
        final scale = fitScale(upright.$1, upright.$2);
        int rounded(int side) =>
            ((side * scale) + 0.5).floor().clamp(1, maxEdge);
        return (rounded(upright.$1), rounded(upright.$2));
      }

      test(
        'the sample keeps a decode near 6 megapixels, whatever the shape',
        () {
          expect(sampleSize(1000, 1000), 1);
          expect(sampleSize(2448, 2448), 1, reason: '6 MP is allowed whole');
          expect(sampleSize(4000, 3000), 2, reason: '12 MP -> 3 MP');
          expect(sampleSize(8000, 6000), 4, reason: '48 MP -> 3 MP');
          expect(
            sampleSize(32000, 1500),
            4,
            reason: 'a panorama, 48 MP -> 3 MP',
          );
          expect(sampleSize(1000000, 1), 1, reason: 'a thin strip is cheap');
          expect(
            sampleSize(1000000000, 1000000000),
            maxSample,
            reason: 'capped',
          );
          for (final size in [(4000, 3000), (8000, 6000), (32000, 1500)]) {
            final sample = sampleSize(size.$1, size.$2);
            final longEdge = size.$1 > size.$2 ? size.$1 : size.$2;
            expect(
              longEdge ~/ sample,
              greaterThan(1200),
              reason: 'never enlarges',
            );
            expect(
              (size.$1 ~/ sample) * (size.$2 ~/ sample),
              lessThanOrEqualTo(maxDecodedPixels),
            );
          }
        },
      );

      test(
        'a decode that fails for memory is tried larger, a bounded number of '
        'times',
        () {
          expect(nextSample(1), 2);
          expect(nextSample(4), 8);
          expect(
            nextSample(maxSample),
            isNull,
            reason: 'nothing larger remains',
          );
          // Three retries from the first sample of a 48 MP photo: 4, 8, 16, 32.
          var sample = sampleSize(8000, 6000);
          final tried = [sample];
          for (var retry = 0; retry < 3; retry++) {
            sample = nextSample(sample)!;
            tried.add(sample);
          }
          expect(tried, [4, 8, 16, 32]);
        },
      );

      test('a picture of at most 1024 px is never enlarged', () {
        expect(fitScale(1024, 700), 1);
        expect(fitScale(200, 100), 1);
        expect(fitScale(4096, 100), 0.25);
        expect(outputSize(1000, 700, 1), (1000, 700));
      });

      test('all eight orientations give the upright size', () {
        // 4000 x 3000 on its side or not: 1024 x 768 or 768 x 1024.
        const upright = {
          1: (1024, 768),
          2: (1024, 768),
          3: (1024, 768),
          4: (1024, 768),
          5: (768, 1024),
          6: (768, 1024),
          7: (768, 1024),
          8: (768, 1024),
        };
        for (final entry in upright.entries) {
          expect(
            outputSize(4000, 3000, entry.key),
            entry.value,
            reason: 'EXIF orientation ${entry.key}',
          );
        }
        // An unknown value is read as upright.
        expect(outputSize(4000, 3000, 0), (1024, 768));
        expect(outputSize(4000, 3000, 9), (1024, 768));
      });

      test('a 4096 x 1 strip is 1024 x 1, never 1024 x 0', () {
        expect(outputSize(4096, 1, 1), (1024, 1));
        expect(outputSize(1, 4096, 1), (1, 1024));
        expect(outputSize(4096, 1, 6), (1, 1024), reason: 'turned a quarter');
        expect(outputSize(1, 1, 1), (1, 1));
        expect(outputSize(32000, 1, 1), (1024, 1));
      });

      test('no side is ever below one pixel or above 1024', () {
        for (final width in [
          1,
          2,
          7,
          100,
          1023,
          1024,
          1025,
          3000,
          9999,
          32000,
        ]) {
          for (final height in [1, 3, 640, 1024, 1500, 4096, 32000]) {
            for (var orientation = 1; orientation <= 8; orientation++) {
              final (w, h) = outputSize(width, height, orientation);
              expect(
                w,
                inInclusiveRange(1, maxEdge),
                reason: '$width x $height',
              );
              expect(
                h,
                inInclusiveRange(1, maxEdge),
                reason: '$width x $height',
              );
            }
          }
        }
      });
    },
  );
}
