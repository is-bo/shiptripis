import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../auth/auth_notifier.dart';

class MediaUploadResult {
  const MediaUploadResult({
    required this.id,
    required this.objectKey,
    required this.bytes,
  });
  final int id;
  final String objectKey;
  final int bytes;
}

class MediaFailure implements Exception {
  MediaFailure(this.message);
  final String message;
  @override
  String toString() => message;
}

class MediaRepository {
  MediaRepository(this._dio);
  final Dio _dio;

  Future<MediaUploadResult> uploadParcelPhoto({
    required int parcelId,
    required String filePath,
    String filename = 'photo.jpg',
  }) async {
    return _upload(
      path: '/api/parcels/$parcelId/media',
      filePath: filePath,
      filename: filename,
    );
  }

  Future<MediaUploadResult> uploadTripPhoto({
    required int tripId,
    required String filePath,
    String filename = 'ticket.jpg',
    String kind = 'ticket',
  }) async {
    return _upload(
      path: '/api/trips/$tripId/media',
      filePath: filePath,
      filename: filename,
      extra: {'kind': kind},
    );
  }

  Future<MediaUploadResult> _upload({
    required String path,
    required String filePath,
    required String filename,
    Map<String, String>? extra,
  }) async {
    final form = FormData.fromMap({
      'photo': await MultipartFile.fromFile(filePath, filename: filename),
      if (extra != null) ...extra,
    });
    try {
      final r = await _dio.post<Map<String, dynamic>>(path, data: form);
      if (r.statusCode == null || r.statusCode! < 200 || r.statusCode! >= 300) {
        throw MediaFailure(_extractMessage(r) ?? 'Upload failed.');
      }
      final data = r.data ?? const {};
      if (data['id'] is! int) {
        throw MediaFailure('Upload returned an invalid response.');
      }
      return MediaUploadResult(
        id: data['id'] as int,
        objectKey: data['object_key'] as String? ?? '',
        bytes: (data['bytes'] as num?)?.toInt() ?? 0,
      );
    } on DioException catch (e) {
      final msg = _extractMessage(e.response) ?? 'Upload failed.';
      throw MediaFailure(msg);
    } on MediaFailure {
      rethrow;
    }
  }

  String? _extractMessage(Response<dynamic>? r) {
    if (r?.data is Map && (r!.data as Map)['detail'] is String) {
      return (r.data as Map)['detail'] as String;
    }
    return null;
  }
}

final mediaRepositoryProvider = Provider<MediaRepository>((ref) {
  return MediaRepository(ref.read(dioProvider));
});
