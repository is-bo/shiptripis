/// K5: the client reads every page of a bounded collection, in both of the
/// server's paging shapes, and never loops forever on one that keeps saying
/// "next".
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/domain/delivery_request.dart';

import 'support/fake_api.dart';

/// A DRF envelope over [total] numbered rows, [size] to a page.
FakeResponse _envelope(RecordedRequest r, {required int total}) {
  final page = int.tryParse('${r.query['page'] ?? 1}') ?? 1;
  final size = int.tryParse('${r.query['page_size'] ?? 20}') ?? 20;
  final start = (page - 1) * size;
  final rows = [
    for (var i = start; i < total && i < start + size; i++) {'id': i},
  ];
  return FakeResponse(200, {
    'count': total,
    'next': start + size < total ? 'https://api/next' : null,
    'previous': null,
    'results': rows,
  });
}

/// A K4 bare-array page: the rows in the body, the paging in headers.
FakeResponse _bare(RecordedRequest r, {required int total}) {
  final page = int.tryParse('${r.query['page'] ?? 1}') ?? 1;
  final size = int.tryParse('${r.query['page_size'] ?? 100}') ?? 100;
  final start = (page - 1) * size;
  final rows = [
    for (var i = start; i < total && i < start + size; i++) {'id': i},
  ];
  return FakeResponse.withHeaders(200, rows, {
    'x-total-count': ['$total'],
    if (start + size < total) 'x-next-page': ['${page + 1}'],
  });
}

List<Object?> _pages(FakeBackend backend, String path) =>
    backend.to('GET', path).map((r) => r.query['page']).toList();

void main() {
  group('getListPage', () {
    test('reads an envelope page, its next link and its count', () async {
      final backend = FakeBackend()
        ..handle('GET', '/api/deals', (r) => _envelope(r, total: 25));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final first = await api.getListPage('/api/deals');
      expect(first.rows, hasLength(20));
      expect(first.hasNext, isTrue);
      expect(first.total, 25);

      final last = await api.getListPage('/api/deals', query: {'page': 2});
      expect(last.rows, hasLength(5));
      expect(last.hasNext, isFalse);
    });

    test('reads a bare-array page from its X-Next-Page header', () async {
      final backend = FakeBackend()
        ..handle('GET', '/api/parcels', (r) => _bare(r, total: 150));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final first = await api.getListPage('/api/parcels');
      expect(first.rows, hasLength(100));
      expect(first.hasNext, isTrue);
      expect(first.total, 150);

      final last = await api.getListPage('/api/parcels', query: {'page': 2});
      expect(last.rows, hasLength(50));
      expect(last.hasNext, isFalse, reason: 'no X-Next-Page, no next page');
    });

    test('a bare array without paging headers is one complete page', () async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/legacy',
          const FakeResponse(200, [
            {'id': 1},
          ]),
        );
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final page = await api.getListPage('/api/legacy');
      expect(page.rows, hasLength(1));
      expect(page.hasNext, isFalse);
      expect(page.total, isNull);
    });

    test('an object with no results list is malformed, not empty', () async {
      final backend = FakeBackend()
        ..on('GET', '/api/deals', const FakeResponse(200, {'count': 3}));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      await expectLater(
        api.getListPage('/api/deals'),
        throwsA(
          isA<ApiException>().having(
            (e) => e.kind,
            'kind',
            ApiFailureKind.malformed,
          ),
        ),
      );
    });
  });

  group('getAllPages', () {
    test('follows an envelope to its last page and stops there', () async {
      final backend = FakeBackend()
        ..handle('GET', '/api/deals', (r) => _envelope(r, total: 230));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final rows = await api.getAllPages(
        '/api/deals',
        query: {'scope': 'current'},
      );

      expect(rows, hasLength(230));
      expect(rows.map((r) => (r as Map)['id']).toSet(), hasLength(230));
      // The first page is asked for without a page number, then 2 and 3.
      expect(_pages(backend, '/api/deals'), [null, 2, 3]);
      for (final r in backend.to('GET', '/api/deals')) {
        expect(r.query['page_size'], 100);
        expect(r.query['scope'], 'current', reason: 'caller query is kept');
      }
    });

    test('follows the bare-array header to its last page', () async {
      final backend = FakeBackend()
        ..handle('GET', '/api/parcels', (r) => _bare(r, total: 201));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final rows = await api.getAllPages('/api/parcels');

      expect(rows, hasLength(201));
      expect(_pages(backend, '/api/parcels'), [null, 2, 3]);
    });

    test('one short page costs one request', () async {
      final backend = FakeBackend()
        ..handle('GET', '/api/deals', (r) => _envelope(r, total: 3));
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      expect(await api.getAllPages('/api/deals'), hasLength(3));
      expect(backend.to('GET', '/api/deals'), hasLength(1));
    });

    test('a server that never stops saying "next" is bounded', () async {
      final backend = FakeBackend()
        ..handle(
          'GET',
          '/api/deals',
          (_) => const FakeResponse(200, {
            'count': 999999,
            'next': 'https://api/next',
            'results': [
              {'id': 1},
            ],
          }),
        );
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));

      final rows = await api.getAllPages('/api/deals', maxPages: 4);

      expect(rows, hasLength(4));
      expect(backend.to('GET', '/api/deals'), hasLength(4));
    });
  });

  test('isSettled is finished or delivered, and nothing still running', () {
    const settled = {
      RequestStatus.delivered,
      RequestStatus.completed,
      RequestStatus.cancelled,
      RequestStatus.expired,
    };
    for (final status in RequestStatus.values) {
      expect(
        status.isSettled,
        settled.contains(status),
        reason: '$status.isSettled',
      );
    }
  });
}
