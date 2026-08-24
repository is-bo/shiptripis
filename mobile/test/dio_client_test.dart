import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/dio_client.dart';
import 'package:shiptrip/core/auth/auth_storage.dart';
import 'package:shiptrip/core/media/media_repository.dart';

class _AuthAdapter implements HttpClientAdapter {
  int refreshCalls = 0;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    if (options.path.endsWith('/api/auth/refresh')) {
      refreshCalls++;
      await Future<void>.delayed(const Duration(milliseconds: 20));
      return _jsonResponse(200, {
        'access': 'new-access',
        'refresh': 'new-refresh',
      });
    }

    if (options.headers['Authorization'] == 'Bearer new-access') {
      return _jsonResponse(200, {'ok': true});
    }
    return _jsonResponse(401, {'detail': 'expired'});
  }

  @override
  void close({bool force = false}) {}
}

class _UploadFailureAdapter implements HttpClientAdapter {
  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) async {
    return _jsonResponse(400, {'detail': 'Rejected upload.'});
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody _jsonResponse(int status, Map<String, dynamic> body) {
  return ResponseBody.fromString(
    jsonEncode(body),
    status,
    headers: {
      Headers.contentTypeHeader: [Headers.jsonContentType],
    },
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('concurrent 401 responses share one rotating refresh', () async {
    FlutterSecureStorage.setMockInitialValues({});
    final storage = AuthStorage();
    await storage.save(access: 'old-access', refresh: 'old-refresh');
    final adapter = _AuthAdapter();
    final dio = buildDioClient(storage)..httpClientAdapter = adapter;

    final responses = await Future.wait([
      dio.get<Map<String, dynamic>>('/api/one'),
      dio.get<Map<String, dynamic>>('/api/two'),
    ]);

    expect(responses.map((response) => response.statusCode), everyElement(200));
    expect(adapter.refreshCalls, 1);
    expect(await storage.readAccess(), 'new-access');
    expect(await storage.readRefresh(), 'new-refresh');
  });

  test('media repository turns an HTTP 4xx into MediaFailure', () async {
    final temp = await File(
      '${Directory.systemTemp.path}${Platform.pathSeparator}shiptrip-upload.jpg',
    ).writeAsBytes([0xff, 0xd8, 0xff, 0xd9]);
    addTearDown(() => temp.delete());
    final dio = Dio(
      BaseOptions(validateStatus: (status) => status != null && status < 500),
    )
      ..httpClientAdapter = _UploadFailureAdapter();
    final repository = MediaRepository(dio);

    await expectLater(
      repository.uploadParcelPhoto(parcelId: 1, filePath: temp.path),
      throwsA(
        isA<MediaFailure>().having(
          (failure) => failure.message,
          'message',
          'Rejected upload.',
        ),
      ),
    );
  });
}
