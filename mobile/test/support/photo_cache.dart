/// A stand-in for the image cache behind profile photos.
///
/// `AppAvatar` draws a photo through `CachedNetworkImage`, whose default cache
/// needs the platform's application directory; a test runner has none, and the
/// missing plugin surfaces as an uncaught error after the test has finished.
/// A test that draws a photo installs one of these first. It also records the
/// key each image was cached under, which is how a test proves the cache key
/// is the photo's version and never its signed address.
library;

import 'dart:async';
import 'dart:io';
import 'dart:typed_data';

import 'package:cached_network_image/cached_network_image.dart';
import 'package:file/local.dart';
import 'package:flutter_cache_manager/flutter_cache_manager.dart';
import 'package:flutter_test/flutter_test.dart';

/// A PNG of [width] by [height] pixels, colour from [rgbAt] as 0xRRGGBB. Built
/// by hand so a test needs no fixture file and the codec still decodes a real
/// picture.
Uint8List makePng(int width, int height, int Function(int x, int y) rgbAt) {
  final raw = BytesBuilder();
  for (var y = 0; y < height; y++) {
    raw.addByte(0); // filter: none
    for (var x = 0; x < width; x++) {
      final rgb = rgbAt(x, y);
      raw
        ..addByte((rgb >> 16) & 0xFF)
        ..addByte((rgb >> 8) & 0xFF)
        ..addByte(rgb & 0xFF);
    }
  }
  final header = ByteData(13)
    ..setUint32(0, width)
    ..setUint32(4, height)
    ..setUint8(8, 8) // bit depth
    ..setUint8(9, 2); // colour type: RGB
  final out = BytesBuilder()
    ..add(const [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]);
  void chunk(String type, List<int> data) {
    final body = [...type.codeUnits, ...data];
    out
      ..add((ByteData(4)..setUint32(0, data.length)).buffer.asUint8List())
      ..add(body)
      ..add((ByteData(4)..setUint32(0, _crc32(body))).buffer.asUint8List());
  }

  chunk('IHDR', header.buffer.asUint8List());
  chunk('IDAT', zlib.encode(raw.toBytes()));
  chunk('IEND', const []);
  return out.toBytes();
}

int _crc32(List<int> bytes) {
  var crc = 0xFFFFFFFF;
  for (final byte in bytes) {
    crc ^= byte;
    for (var bit = 0; bit < 8; bit++) {
      crc = (crc & 1) == 1 ? (crc >> 1) ^ 0xEDB88320 : crc >> 1;
    }
  }
  return crc ^ 0xFFFFFFFF;
}

/// A small solid picture.
final Uint8List tinyPng = makePng(8, 8, (_, _) => 0x2F6F5E);

enum PhotoCacheBehavior {
  /// Serves the given bytes at once.
  serve,

  /// Fails, as an unreachable network does.
  fail,

  /// Never answers: the image is still loading.
  stall,
}

class FakePhotoCache extends Fake implements BaseCacheManager {
  FakePhotoCache(this.behavior, {Uint8List? bytes, this.behaviorFor})
    : _bytes = bytes ?? tinyPng;

  final PhotoCacheBehavior behavior;

  /// What one address answers, when it differs from [behavior].
  final PhotoCacheBehavior? Function(String url)? behaviorFor;

  /// The stalled load of each address, so a test can fail or finish it later.
  final stalled = <String, StreamController<FileResponse>>{};
  final Uint8List _bytes;

  /// The cache key of every image requested, in order.
  final List<String> keys = [];

  /// The address of every image requested, in order.
  final List<String> urls = [];

  late final File _file = () {
    final dir = Directory.systemTemp.createTempSync('shiptrip-photo-cache');
    return File('${dir.path}${Platform.pathSeparator}photo.png')
      ..writeAsBytesSync(_bytes);
  }();

  @override
  Stream<FileResponse> getFileStream(
    String url, {
    String? key,
    Map<String, String>? headers,
    bool withProgress = false,
  }) {
    urls.add(url);
    keys.add(key ?? url);
    return switch (behaviorFor?.call(url) ?? behavior) {
      PhotoCacheBehavior.serve => Stream.value(
        FileInfo(
          const LocalFileSystem().file(_file.path),
          FileSource.Online,
          DateTime.now().add(const Duration(days: 1)),
          url,
        ),
      ),
      PhotoCacheBehavior.fail => Stream.error(const SocketException('offline')),
      PhotoCacheBehavior.stall =>
        (stalled[url] = StreamController<FileResponse>()).stream,
    };
  }
}

/// Installs [behavior] as the cache every `CachedNetworkImage` of this test
/// uses, and returns it.
FakePhotoCache installPhotoCache(
  PhotoCacheBehavior behavior, {
  Uint8List? bytes,
  PhotoCacheBehavior? Function(String url)? behaviorFor,
}) {
  final cache = FakePhotoCache(
    behavior,
    bytes: bytes,
    behaviorFor: behaviorFor,
  );
  CachedNetworkImageProvider.defaultCacheManager = cache;
  return cache;
}

/// Lets a photo load: the file read is real I/O, so fake time alone never gets
/// it done.
Future<void> settlePhotos(WidgetTester tester) async {
  for (var i = 0; i < 5; i++) {
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 20)),
    );
    await tester.pump(const Duration(milliseconds: 200));
  }
}
