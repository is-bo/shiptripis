/// K7 mobile certification: a slow network is usable and honestly named.
///
/// J1.2 pinned the read budget and the timeout copy, and K5 covered a slow
/// `/api/me` at launch. What no test drove end to end was the client itself
/// meeting a timeout: a read that stalls once must recover on its own, a read
/// that keeps stalling must end as a retryable timeout rather than a server
/// fault, and a write must never be replayed behind the user's back. This runs
/// the real `ApiClient` over the in-process fake backend.
library;

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';

import 'support/fake_api.dart';

Never _stall(RecordedRequest r) => throw DioException(
  requestOptions: RequestOptions(path: r.path),
  type: DioExceptionType.receiveTimeout,
);

void main() {
  group('a slow network', () {
    test('a read that times out once is retried and succeeds', () async {
      var calls = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (r) {
          calls += 1;
          if (calls == 1) _stall(r);
          return FakeResponse(200, {'id': 7});
        });
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      final body = await api.getObject('/api/me');

      expect(body['id'], 7);
      expect(backend.to('GET', '/api/me'), hasLength(2));
    });

    test('a read that keeps timing out ends as a retryable timeout after '
        'three attempts', () async {
      final backend = FakeBackend()..handle('GET', '/api/deals', _stall);
      final api = apiClientFor(backend);
      addTearDown(() => api.raw.close(force: true));

      final failure = await api
          .getList('/api/deals')
          .then<ApiException?>(
            (_) => null,
            onError: (Object e) => e as ApiException,
          );

      expect(failure, isNotNull);
      expect(failure!.kind, ApiFailureKind.timeout);
      expect(failure.isRetryable, isTrue);
      expect(backend.to('GET', '/api/deals'), hasLength(3));
    });

    test(
      'a write that times out is reported once and never replayed',
      () async {
        final backend = FakeBackend()
          ..handle('POST', '/api/matches/propose', _stall);
        final api = apiClientFor(backend);
        addTearDown(() => api.raw.close(force: true));

        final failure = await api
            .postObject('/api/matches/propose', body: {'parcel_id': 1})
            .then<ApiException?>(
              (_) => null,
              onError: (Object e) => e as ApiException,
            );

        expect(failure?.kind, ApiFailureKind.timeout);
        expect(backend.to('POST', '/api/matches/propose'), hasLength(1));
      },
    );
  });
}
