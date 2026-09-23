/// K6: the marketplace discovery feeds (journey search, open requests) are
/// read 20 rows a page, never at the server's 100-row default, in the
/// server's order, with the server's total.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';

import 'support/fake_api.dart';

/// A K4 bare-array page over [total] rows whose ids are their server rank.
FakeResponse _bare(
  RecordedRequest r, {
  required int total,
  required Map<String, dynamic> Function(int id) row,
}) {
  final page = int.tryParse('${r.query['page'] ?? 1}') ?? 1;
  final size = int.tryParse('${r.query['page_size'] ?? 100}') ?? 100;
  final start = (page - 1) * size;
  return FakeResponse.withHeaders(
    200,
    [for (var i = start; i < total && i < start + size; i++) row(i)],
    {
      'x-total-count': ['$total'],
      if (start + size < total) 'x-next-page': ['${page + 1}'],
    },
  );
}

Map<String, dynamic> _journey(int id) => {
  'id': id,
  'traveler_id': 42,
  'status': 'active',
  'start_location': {'id': id, 'public_label': 'Origin $id'},
  'destination_location': {'id': 10000 + id, 'public_label': 'Paris'},
  'legs': <Object>[],
};

Map<String, dynamic> _parcel(int id) => {
  'id': id,
  'sender_id': 42,
  'target_traveler_id': null,
  'kind': 'delivery',
  'status': 'open',
  'schema_version': 3,
  'title': 'Parcel $id',
  'description': '',
  'category': 'documents',
  'fragile': false,
  'handling_notes': '',
  'created_at': '2026-09-19T08:00:00Z',
};

void main() {
  test('journey search sends page_size=20 and reads pages in order', () async {
    final backend = FakeBackend()
      ..handle(
        'GET',
        '/api/journeys/search',
        (r) => _bare(r, total: 45, row: _journey),
      );
    final api = apiClientFor(backend, FakeTokenStore());
    addTearDown(() => api.raw.close(force: true));
    final repo = JourneyRepository(api);

    final ids = <int>[];
    var page = 1;
    while (true) {
      final result = await repo.searchPage(page: page, startPlaceId: 7);
      expect(result.total, 45);
      ids.addAll(result.journeys.map((j) => j.id));
      if (!result.hasNext) break;
      page++;
    }

    final sent = backend.to('GET', '/api/journeys/search');
    expect(sent, hasLength(3), reason: '45 rows at 20 a page');
    expect(sent.first.query['page_size'], 20);
    expect(sent.first.query.containsKey('page'), isFalse);
    expect(sent.first.query['start_place_id'], 7);
    expect([for (final r in sent) r.query['page']], [null, 2, 3]);
    expect(ids, [for (var i = 0; i < 45; i++) i], reason: 'server order kept');
  });

  test(
    'open-request feed sends page_size=20 and reads pages in order',
    () async {
      final backend = FakeBackend()
        ..handle(
          'GET',
          '/api/parcels/open',
          (r) => _bare(r, total: 25, row: _parcel),
        );
      final api = apiClientFor(backend, FakeTokenStore());
      addTearDown(() => api.raw.close(force: true));
      final repo = RequestRepository(api);

      final first = await repo.openFeedPage(page: 1, maxWeightKg: 4);
      expect(first.requests.map((r) => r.id), [for (var i = 0; i < 20; i++) i]);
      expect(first.hasNext, isTrue);
      expect(first.total, 25);

      final last = await repo.openFeedPage(page: 2, maxWeightKg: 4);
      expect(last.requests.map((r) => r.id), [20, 21, 22, 23, 24]);
      expect(last.hasNext, isFalse);

      final sent = backend.to('GET', '/api/parcels/open');
      expect(sent.first.query['page_size'], 20);
      expect(sent.first.query['max_weight_kg'], '4.00');
      expect(sent.last.query['page'], 2);
    },
  );
}
