/// Getting a picked photo ready to upload as a profile photo.
///
/// The picker hands over the original: a 48 megapixel camera file decodes to
/// about 183 MiB, so the picker's own resize (which decodes the whole file
/// first on Android) is not used. Instead the file's size is read from its
/// header, without decoding it, and the native compressor is told to sample
/// while it decodes, so the full picture never sits in memory. What comes out
/// is a JPEG of about 1024 px on its shorter side, written to a path used
/// once, with no metadata.
library;

import 'dart:io';
import 'dart:math';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_image_compress/flutter_image_compress.dart';

/// The shorter side the server needs room for (it keeps a 512 px square).
const profilePhotoEdge = 1024;

const _profilePhotoQuality = 88;

/// Sample size when the engine cannot read the file's size: 4 keeps even a
/// 48 megapixel decode near 12 MiB and still leaves more than the 512 px the
/// server keeps.
const _unknownSizeSample = 4;

/// The native decoder cannot read this file.
class UnsupportedPhoto implements Exception {
  const UnsupportedPhoto([this.cause]);

  final Object? cause;

  @override
  String toString() => 'UnsupportedPhoto($cause)';
}

/// How the native compressor is asked to write [target] from [source].
typedef PhotoCompressor =
    Future<String?> Function(
      String source,
      String target, {
      required int sampleSize,
    });

Future<String?> _nativeCompress(
  String source,
  String target, {
  required int sampleSize,
}) async {
  final out = await FlutterImageCompress.compressAndGetFile(
    source,
    target,
    minWidth: profilePhotoEdge,
    minHeight: profilePhotoEdge,
    quality: _profilePhotoQuality,
    inSampleSize: sampleSize,
    format: CompressFormat.jpeg,
  );
  return out?.path;
}

/// The largest power of two the decoder may divide the picture by while its
/// shorter side stays at least [edge]. 8000 x 6000 is sampled by 4, 4000 x 3000
/// by 2, a 1500 x 1000 photo not at all.
int sampleSizeFor(int width, int height, {int edge = profilePhotoEdge}) {
  final shorter = min(width, height);
  var sample = 1;
  while (shorter ~/ (sample * 2) >= edge) {
    sample *= 2;
  }
  return sample;
}

/// The picture's width and height, read from its header and not decoded, or
/// null when the engine does not know the format.
Future<({int width, int height})?> readImageSize(String path) async {
  ui.ImmutableBuffer? buffer;
  ui.ImageDescriptor? descriptor;
  try {
    buffer = await ui.ImmutableBuffer.fromFilePath(path);
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    return (width: descriptor.width, height: descriptor.height);
  } on Object {
    return null;
  } finally {
    descriptor?.dispose();
    buffer?.dispose();
  }
}

final _random = Random.secure();

/// A temporary path used for one picked photo only, so a preview never shows
/// an earlier photo cached under the same name.
String uniquePhotoPath() =>
    '${Directory.systemTemp.path}${Platform.pathSeparator}'
    'wassla-profile-photo-${DateTime.now().microsecondsSinceEpoch}-'
    '${_random.nextInt(1 << 32).toRadixString(36)}.jpg';

/// Downscales [sourcePath] to a JPEG at a new temporary path and returns it.
///
/// Throws [FileSystemException] when the source is gone and
/// [UnsupportedPhoto] when it cannot be decoded.
Future<String> downscaleProfilePhoto(
  String sourcePath, {
  PhotoCompressor compress = _nativeCompress,
}) async {
  if (!await File(sourcePath).exists()) {
    throw FileSystemException('The picked photo is gone', sourcePath);
  }
  final size = await readImageSize(sourcePath);
  final sample = size == null
      ? _unknownSizeSample
      : sampleSizeFor(size.width, size.height);
  final target = uniquePhotoPath();
  final String? written;
  try {
    written = await compress(sourcePath, target, sampleSize: sample);
  } on FileSystemException {
    rethrow;
  } on Object catch (error) {
    throw UnsupportedPhoto(error);
  }
  if (written == null) throw const UnsupportedPhoto();
  return written;
}

/// The content type the first bytes of an image declare, or null when they
/// are not a JPEG, PNG or WebP. The upload is declared by what the file is,
/// never by what its name says: a native resizer can keep a `.webp` name on
/// JPEG bytes.
String? sniffImageType(List<int> head) {
  bool starts(List<int> signature, [int at = 0]) {
    if (head.length < at + signature.length) return false;
    for (var i = 0; i < signature.length; i++) {
      if (head[at + i] != signature[i]) return false;
    }
    return true;
  }

  if (starts(const [0xFF, 0xD8, 0xFF])) return 'image/jpeg';
  if (starts(const [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])) {
    return 'image/png';
  }
  if (starts(const [0x52, 0x49, 0x46, 0x46]) &&
      starts(const [0x57, 0x45, 0x42, 0x50], 8)) {
    return 'image/webp';
  }
  return null;
}

String extensionFor(String contentType) => switch (contentType) {
  'image/png' => 'png',
  'image/webp' => 'webp',
  _ => 'jpg',
};

/// The first bytes of [path], for [sniffImageType].
Future<Uint8List> readHead(String path, {int length = 16}) async {
  final file = await File(path).open();
  try {
    return await file.read(length);
  } finally {
    await file.close();
  }
}

/// Removes a temporary photo; a file that is already gone is fine.
Future<void> deleteQuietly(String path) async {
  try {
    await File(path).delete();
  } on FileSystemException {
    // Nothing to remove.
  }
}
