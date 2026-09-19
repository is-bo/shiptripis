import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';

class _Repository implements MatchingRepository {
  _Repository(this.reply);

  final Future<FindTravelersPage> Function(String sort, int offset) reply;

  @override
  Future<FindTravelersPage> findTravelers({
    required int parcelId,
    int? limit,
    int? offset,
    String? sort,
    CancelToken? cancelToken,
  }) => reply(sort ?? 'best_match', offset ?? 0);

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

FindTravelersPage _page(
  String sort,
  int offset,
  List<int> journeys, {
  bool hasMore = false,
}) => FindTravelersPage(
  state: DiscoveryState.results,
  sort: sort,
  page: DiscoveryPageInfo(
    limit: 10,
    offset: offset,
    total: 20,
    hasMore: hasMore,
    nextOffset: hasMore ? offset + 10 : null,
  ),
  candidates: [
    for (final id in journeys) TravelerCandidate.fromJson({'journey_id': id}),
  ],
);

Future<void> _initialReady(FindTravelersController controller) {
  if (!controller.isLoading) return Future<void>.value();
  final done = Completer<void>();
  void listener() {
    if (!controller.isLoading && !done.isCompleted) done.complete();
  }

  controller.addListener(listener);
  return done.future.whenComplete(() => controller.removeListener(listener));
}

List<int> _ids(FindTravelersController controller) => [
  for (final candidate in controller.state!.candidates) candidate.journeyId,
];

void main() {
  test('old loadMore cannot replace a completed new sort', () async {
    final oldPage = Completer<FindTravelersPage>();
    final newSort = Completer<FindTravelersPage>();
    final controller = FindTravelersController(
      requestId: 42,
      repository: _Repository((sort, offset) {
        if (sort == 'best_match' && offset == 0) {
          return Future.value(_page(sort, 0, [1], hasMore: true));
        }
        if (sort == 'best_match' && offset == 10) return oldPage.future;
        if (sort == 'reward_low_high' && offset == 0) return newSort.future;
        throw StateError('Unexpected query $sort/$offset');
      }),
    );
    await _initialReady(controller);
    final stale = controller.loadMore();
    final fresh = controller.setSort('reward_low_high');
    newSort.complete(_page('reward_low_high', 0, [99]));
    await fresh;
    oldPage.complete(_page('best_match', 10, [2]));
    await stale;
    expect(controller.state!.sort, 'reward_low_high');
    expect(_ids(controller), [99]);
    expect(controller.state!.isLoadingMore, isFalse);
  });

  test('refresh supersedes pagination even when sort is unchanged', () async {
    final oldPage = Completer<FindTravelersPage>();
    final refreshed = Completer<FindTravelersPage>();
    var firstPageCalls = 0;
    final controller = FindTravelersController(
      requestId: 42,
      repository: _Repository((sort, offset) {
        if (offset == 0) {
          firstPageCalls++;
          return firstPageCalls == 1
              ? Future.value(_page(sort, 0, [1], hasMore: true))
              : refreshed.future;
        }
        if (offset == 10) return oldPage.future;
        throw StateError('Unexpected offset $offset');
      }),
    );
    await _initialReady(controller);
    final stale = controller.loadMore();
    final fresh = controller.refresh();
    refreshed.complete(_page('best_match', 0, [30]));
    await fresh;
    oldPage.complete(_page('best_match', 10, [2]));
    await stale;
    expect(_ids(controller), [30]);
    expect(controller.state!.isLoadingMore, isFalse);
  });

  test('second sort wins over both earlier sort and pagination', () async {
    final oldPage = Completer<FindTravelersPage>();
    final firstSort = Completer<FindTravelersPage>();
    final secondSort = Completer<FindTravelersPage>();
    final controller = FindTravelersController(
      requestId: 42,
      repository: _Repository((sort, offset) {
        if (sort == 'best_match' && offset == 0) {
          return Future.value(_page(sort, 0, [1], hasMore: true));
        }
        if (sort == 'best_match' && offset == 10) return oldPage.future;
        if (sort == 'reward_low_high') return firstSort.future;
        if (sort == 'soonest_departure') return secondSort.future;
        throw StateError('Unexpected query $sort/$offset');
      }),
    );
    await _initialReady(controller);
    final stalePage = controller.loadMore();
    final staleSort = controller.setSort('reward_low_high');
    final fresh = controller.setSort('soonest_departure');
    secondSort.complete(_page('soonest_departure', 0, [77]));
    await fresh;
    firstSort.complete(_page('reward_low_high', 0, [99]));
    oldPage.complete(_page('best_match', 10, [2]));
    await Future.wait([staleSort, stalePage]);
    expect(controller.state!.sort, 'soonest_departure');
    expect(_ids(controller), [77]);
    expect(controller.isLoading, isFalse);
  });

  test(
    'unchanged query appends a normal page and removes duplicates',
    () async {
      final page = Completer<FindTravelersPage>();
      final controller = FindTravelersController(
        requestId: 42,
        repository: _Repository((sort, offset) {
          if (offset == 0) {
            return Future.value(_page(sort, 0, [1], hasMore: true));
          }
          if (offset == 10) return page.future;
          throw StateError('Unexpected offset $offset');
        }),
      );
      await _initialReady(controller);
      final loading = controller.loadMore();
      page.complete(_page('best_match', 10, [1, 2]));
      await loading;
      expect(_ids(controller), [1, 2]);
      expect(controller.state!.hasMore, isFalse);
      expect(controller.state!.isLoadingMore, isFalse);
    },
  );
}
