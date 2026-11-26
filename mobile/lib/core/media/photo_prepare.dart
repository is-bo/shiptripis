/// Getting a picked photo ready to upload as a profile photo.
///
/// The picker hands over the original: a 48 megapixel camera file decodes to
/// about 183 MiB, a 32000 x 1500 panorama to about the same, and a HEIC file
/// cannot be probed by Flutter's own codec without decoding it. So the work is
/// done by one small method on each platform, `wassla/photo_prepare`:
///
///     prepare(path) -> path of a new JPEG
///
/// The new file is upright (all eight EXIF orientations, mirrored ones
/// included), at most 1024 px on its long edge, has no metadata, and sits at a
/// path made for this call in the app's cache. The native side samples while it
/// decodes so that the pixels held in memory are bounded whatever the
/// picture's shape:
///
/// * Android (`PhotoPrepare.kt`) reads the bounds without decoding, picks a
///   power-of-two sample that keeps the decode near 6 megapixels, applies the
///   orientation and the scale in one matrix, and writes the JPEG; HEIF that
///   `BitmapFactory` cannot read goes through `ImageDecoder` on API 28 and up.
/// * iOS (`AppDelegate.swift`) asks ImageIO for a 1024 px thumbnail with the
///   transform applied, which decodes at the reduced size, handles HEIC and
///   orientation in one step, and writes the JPEG.
///
/// Dart only calls it, maps its failures, and checks the answer.
library;

import 'dart:io';

import 'package:flutter/services.dart';

/// The platform method that prepares a profile photo.
const photoPrepareChannel = MethodChannel('wassla/photo_prepare');

/// The native decoder cannot read this file.
class UnsupportedPhoto implements Exception {
  const UnsupportedPhoto([this.cause]);

  final Object? cause;

  @override
  String toString() => 'UnsupportedPhoto($cause)';
}

/// Asks the platform for an upright JPEG of about 1024 px made from
/// [sourcePath], and returns its path.
///
/// Throws [FileSystemException] when the source is gone (`not_found`) and
/// [UnsupportedPhoto] for anything else the platform reports: a picture it
/// cannot decode, or one it ran out of memory on.
Future<String> prepareProfilePhoto(
  String sourcePath, {
  MethodChannel channel = photoPrepareChannel,
}) async {
  final String? prepared;
  try {
    prepared = await channel.invokeMethod<String>('prepare', {
      'path': sourcePath,
    });
  } on PlatformException catch (error) {
    if (error.code == 'not_found') {
      throw FileSystemException('The picked photo is gone', sourcePath);
    }
    throw UnsupportedPhoto(error);
  } on MissingPluginException catch (error) {
    throw UnsupportedPhoto(error);
  }
  if (prepared == null || prepared.isEmpty) throw const UnsupportedPhoto();
  return prepared;
}

/// The content type the first bytes of an image declare, or null when they
/// are not a JPEG, PNG or WebP. The upload is declared by what the file is,
/// never by what its name says.
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
