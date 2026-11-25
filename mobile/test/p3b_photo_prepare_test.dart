/// P3B second pass: getting a picked photo ready, without decoding the whole
/// original.
///
/// The picker's own resize decodes the full file first (about 183 MiB for a
/// 48 megapixel photo), so the app picks the original and asks the native
/// compressor to sample while it decodes. These tests hold the arithmetic and
/// the contract with the compressor; whether the phone's memory holds is a
/// device check (see the phase document).
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/media/photo_prepare.dart';

import 'support/photo_cache.dart';
import 'support/photo_rig.dart';

class _Call {
  _Call(this.source, this.target, this.sampleSize);

  final String source;
  final String target;
  final int sampleSize;
}

/// What [body] throws, run on real time so the file reads can finish.
Future<Object?> _thrown(
  WidgetTester tester,
  Future<Object?> Function() body,
) async {
  Object? error;
  await tester.runAsync(() async {
    try {
      await body();
    } on Object catch (caught) {
      error = caught;
    }
  });
  return error;
}

void main() {
  group('the sample size', () {
    test('divides a big photo while its shorter side stays at 1024 px', () {
      // 48 MP: decoded in full it is 183 MiB; sampled by 4 it is about 11.
      expect(sampleSizeFor(8000, 6000), 4);
      expect(sampleSizeFor(6000, 8000), 4, reason: 'portrait, same photo');
      expect(sampleSizeFor(4000, 3000), 2, reason: '12 MP');
      expect(sampleSizeFor(4096, 4096), 4);
    });

    test('leaves a small photo alone', () {
      expect(sampleSizeFor(1500, 1000), 1);
      expect(sampleSizeFor(1024, 1024), 1);
      expect(sampleSizeFor(640, 480), 1);
      expect(sampleSizeFor(2047, 2047), 1, reason: '2047 / 2 is under 1024');
    });

    test('goes by the shorter side, so a panorama is not over-divided', () {
      expect(sampleSizeFor(12000, 1100), 1);
      expect(sampleSizeFor(12000, 2300), 2);
    });
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

  group('downscaling', () {
    testWidgets(
      'a large source is read by header and sampled by the compressor',
      (tester) async {
        // 2400 x 2400: too big to leave alone (sample 2), small enough to build.
        final source = sourceFile(
          name: 'big.png',
          bytes: makePng(2400, 2400, (x, y) => (x * 7 + y * 3) & 0xFFFFFF),
        );
        final calls = <_Call>[];

        final out = await tester.runAsync(
          () => downscaleProfilePhoto(
            source,
            compress: (src, target, {required sampleSize}) async {
              calls.add(_Call(src, target, sampleSize));
              return target;
            },
          ),
        );

        expect(calls, hasLength(1));
        expect(calls.single.source, source);
        expect(
          calls.single.sampleSize,
          2,
          reason: 'the size came from the header, not from decoding the photo',
        );
        expect(calls.single.target, endsWith('.jpg'));
        expect(out, calls.single.target);
      },
    );

    testWidgets(
      'a photo the engine cannot size is sampled by the safe default',
      (tester) async {
        final source = sourceFile(name: 'odd.heic', bytes: gifBytes);
        final calls = <_Call>[];

        await tester.runAsync(
          () => downscaleProfilePhoto(
            source,
            compress: (src, target, {required sampleSize}) async {
              calls.add(_Call(src, target, sampleSize));
              return target;
            },
          ),
        );

        expect(calls.single.sampleSize, 4);
      },
    );

    testWidgets('every call writes to a path of its own', (tester) async {
      // Two picks with the same base name must not share a preview.
      final source = sourceFile(name: 'IMG_0001.jpg');
      final targets = <String>[];

      await tester.runAsync(() async {
        for (var i = 0; i < 3; i++) {
          await downscaleProfilePhoto(
            source,
            compress: (src, target, {required sampleSize}) async {
              targets.add(target);
              return target;
            },
          );
        }
      });

      expect(targets.toSet(), hasLength(3));
      expect(targets.every((t) => t != source), isTrue);
    });

    testWidgets('a source that is gone is a file error', (tester) async {
      final error = await _thrown(
        tester,
        () => downscaleProfilePhoto(
          '${Directory.systemTemp.path}${Platform.pathSeparator}gone.jpg',
          compress: (_, target, {required sampleSize}) async => target,
        ),
      );
      expect(error, isA<FileSystemException>());
    });

    testWidgets('a compressor that fails or answers nothing is unsupported', (
      tester,
    ) async {
      final source = sourceFile();
      expect(
        await _thrown(
          tester,
          () => downscaleProfilePhoto(
            source,
            compress: (_, _, {required sampleSize}) async =>
                throw StateError('cannot decode'),
          ),
        ),
        isA<UnsupportedPhoto>(),
      );
      expect(
        await _thrown(
          tester,
          () => downscaleProfilePhoto(
            source,
            compress: (_, _, {required sampleSize}) async => null,
          ),
        ),
        isA<UnsupportedPhoto>(),
      );
    });
  });
}
