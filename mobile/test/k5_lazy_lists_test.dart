/// K5 13.9 / 13.10: growing lists are built lazily, and photos are decoded at
/// the size they are drawn.
///
/// "Lazily" is asserted on the element tree, not inferred from the widget
/// type: with 200 rows behind the screen, only the rows near the viewport may
/// exist, and scrolling must still reach the last one. The states around the
/// lists (empty, failure) are checked through the same screens.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/design/components/images.dart';
import 'package:shiptrip/domain/rating.dart';
import 'package:shiptrip/features/deliveries/deliveries_screen.dart';
import 'package:shiptrip/features/journeys/journey_detail_screen.dart';
import 'package:shiptrip/features/profile/ratings_screen.dart';
import 'package:shiptrip/features/requests/request_detail_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const _rows = 200;

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

Map<String, dynamic> _journey(int id) => {
  'id': id,
  'traveler_id': 42,
  'status': 'completed',
  'start_location': {'id': id, 'public_label': 'Origin $id'},
  'destination_location': {'id': 10000 + id, 'public_label': 'Paris'},
  'legs': <Object>[],
};

Map<String, dynamic> _liveJourney() => {
  'id': 7,
  'traveler_id': 42,
  'status': 'active',
  'notes': '',
  'editable': false,
  'legs': [
    {
      'id': 101,
      'position': 0,
      'mode': 'DRIVE',
      'depart_at': '2026-10-01T08:00:00Z',
      'arrive_at': '2026-10-01T13:00:00Z',
      'capacity_kg': '12.00',
      'proofs': <Object>[],
    },
  ],
};

Map<String, dynamic> _candidate(int id) => {
  'delivery_request': {
    'id': id,
    'sender_id': 5,
    'pickup': {'id': id, 'public_label': 'Pickup $id'},
    'delivery': {'id': 10000 + id, 'public_label': 'Paris'},
  },
};

/// Every element currently built for a row labelled `<prefix> <n>`,
/// on-screen or in the cache extent.
int _built(String prefix) => find
    .textContaining(RegExp('^$prefix \\d+\$'), skipOffstage: false)
    .evaluate()
    .length;

Finder get _mainScroll => find.byWidgetPredicate(
  (w) => w is Scrollable && w.axisDirection == AxisDirection.down,
);

Future<ProviderContainer> _signedIn(
  WidgetTester tester,
  FakeBackend backend, {
  String role = 'both',
}) async {
  backend.on(
    'GET',
    '/api/me',
    FakeResponse(200, {...meFixture(), 'role': role}),
  );
  // `containerFor`, minus Riverpod's automatic retry: a failure state is part
  // of what is asserted here, and a retry timer outliving the test would fail
  // it for a reason that has nothing to do with the screen.
  final tokens = FakeTokenStore();
  final container = ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      sessionCoreProvider.overrideWithValue(backend.session),
      apiClientProvider.overrideWithValue(apiClientFor(backend)),
    ],
    retry: (_, _) => null,
  );
  addTearDown(container.dispose);
  await launchPumped(tester, container);
  return container;
}

FakeBackend _deliveriesBackend({
  FakeResponse? parcels,
  FakeResponse? journeys,
}) => FakeBackend()
  ..on('GET', '/api/deals', FakeResponse(200, <Object>[]))
  ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
  ..on('GET', '/api/journeys', journeys ?? FakeResponse(200, <Object>[]))
  ..on(
    'GET',
    '/api/notifications/unread-count',
    FakeResponse(200, {'unread': 0}),
  )
  ..on('GET', '/api/parcels', parcels ?? FakeResponse(200, <Object>[]));

Future<L> _pumpDeliveries(WidgetTester tester, ProviderContainer c) async {
  await pumpApp(tester, const DeliveriesScreen(), container: c);
  await tester.pumpAndSettle();
  return L.of(tester.element(find.byType(DeliveriesScreen)));
}

void main() {
  // -------------------------------------------------------------------------
  group('Deliveries: own requests and journeys', () {
    testWidgets('200 requests build only the rows near the viewport', (
      tester,
    ) async {
      final backend = _deliveriesBackend(
        parcels: FakeResponse(200, [
          for (var i = 0; i < _rows; i++) _parcel(i),
        ]),
      );
      final container = await _signedIn(tester, backend);
      final l = await _pumpDeliveries(tester, container);

      expect(find.text(l.deliveriesSenderSection), findsOneWidget);
      expect(_built('Parcel'), inInclusiveRange(1, 20));

      await tester.scrollUntilVisible(
        find.text('Parcel ${_rows - 1}'),
        1200,
        scrollable: _mainScroll.first,
      );
      expect(find.text('Parcel ${_rows - 1}'), findsOneWidget);
      expect(find.text('Parcel 0', skipOffstage: false), findsNothing);
      expect(_built('Parcel'), lessThan(30));
    });

    testWidgets('a failed request read still says so, beside the Deals', (
      tester,
    ) async {
      final backend = _deliveriesBackend(
        parcels: const FakeResponse(500, {'detail': 'boom'}),
      );
      final container = await _signedIn(tester, backend);
      final l = await _pumpDeliveries(tester, container);

      expect(find.byType(InlineFailure), findsOneWidget);
      // The Deals part of the screen is unaffected: its own empty state.
      expect(find.text(l.deliveriesEmptyActiveTitle), findsOneWidget);
    });

    testWidgets('no requests: the empty Deals state and no section header', (
      tester,
    ) async {
      final container = await _signedIn(tester, _deliveriesBackend());
      final l = await _pumpDeliveries(tester, container);

      expect(find.text(l.deliveriesEmptyActiveTitle), findsOneWidget);
      expect(find.text(l.deliveriesSenderSection), findsNothing);
    });

    testWidgets('200 finished journeys in History build lazily too', (
      tester,
    ) async {
      final backend = _deliveriesBackend(
        journeys: FakeResponse(200, [
          for (var i = 0; i < _rows; i++) _journey(i),
        ]),
      );
      final container = await _signedIn(tester, backend, role: 'traveler');
      final l = await _pumpDeliveries(tester, container);

      await tester.tap(find.text(l.deliveriesFilterHistory));
      await tester.pumpAndSettle();

      expect(find.text(l.deliveriesJourneysSection), findsOneWidget);
      expect(_built('Origin'), inInclusiveRange(1, 12));

      await tester.scrollUntilVisible(
        find.text('Origin ${_rows - 1}'),
        1200,
        scrollable: _mainScroll.first,
      );
      expect(find.text('Origin ${_rows - 1}'), findsOneWidget);
      expect(_built('Origin'), lessThan(20));

      // History outlives its last viewer briefly (K5); let that run out
      // before the test's pending-timer check.
      await tester.pumpWidget(const SizedBox());
      await tester.pump(DealHistoryController.keptFor);
    });
  });

  // -------------------------------------------------------------------------
  group('Journey detail: compatible requests', () {
    FakeBackend backendWith(FakeResponse compatible) => FakeBackend()
      ..on('GET', '/api/journeys/7', FakeResponse(200, _liveJourney()))
      ..on('GET', '/api/matches/compatible-requests', compatible);

    testWidgets('a long result list is built as it scrolls', (tester) async {
      final container = await _signedIn(
        tester,
        backendWith(
          FakeResponse(200, {
            'count': 60,
            'results': [for (var i = 0; i < 60; i++) _candidate(i)],
          }),
        ),
      );
      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(JourneyDetailScreen)));

      expect(_built('Pickup'), lessThan(15));

      await tester.scrollUntilVisible(
        find.text('Pickup 59'),
        1200,
        scrollable: _mainScroll.first,
      );
      expect(find.text('Pickup 0', skipOffstage: false), findsNothing);

      // What follows the list is still there.
      await tester.scrollUntilVisible(
        find.text(l.journeyCancel),
        400,
        scrollable: _mainScroll.first,
      );
      expect(find.text(l.journeyCancel), findsOneWidget);
    });

    testWidgets('a failed discovery read is an inline failure', (tester) async {
      final container = await _signedIn(
        tester,
        backendWith(const FakeResponse(500, {'detail': 'boom'})),
      );
      await pumpRouted(
        tester,
        const JourneyDetailScreen(journeyId: 7),
        container: container,
      );
      await tester.pumpAndSettle();
      await tester.scrollUntilVisible(
        find.byType(InlineFailure),
        400,
        scrollable: _mainScroll.first,
      );
      expect(find.byType(InlineFailure), findsOneWidget);
    });
  });

  // -------------------------------------------------------------------------
  group('Ratings', () {
    testWidgets('200 ratings: summary first, rows built lazily', (
      tester,
    ) async {
      final ratings = [
        for (var i = 0; i < _rows; i++)
          Rating(
            id: i,
            dealId: 1000 + i,
            score: 5,
            tags: const [],
            isRevealed: true,
            comment: 'Comment $i',
          ),
      ];
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(FakeTokenStore()),
          receivedRatingsProvider.overrideWith((ref) => AsyncData(ratings)),
        ],
      );
      addTearDown(container.dispose);
      await pumpApp(tester, const RatingsScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.textContaining('5.0'), findsOneWidget);
      expect(_built('Comment'), inInclusiveRange(1, 25));

      await tester.scrollUntilVisible(
        find.text('Comment ${_rows - 1}'),
        1200,
        scrollable: _mainScroll.first,
      );
      expect(find.text('Comment ${_rows - 1}'), findsOneWidget);
      expect(_built('Comment'), lessThan(30));
    });
  });

  // -------------------------------------------------------------------------
  group('photo decode size', () {
    test('logical width times device pixel ratio, rounded up', () {
      // Exercised through a real MediaQuery below; this pins the arithmetic
      // and the unbounded case.
      expect(decodeWidthForRatio(371, 2.75), 1021);
      expect(decodeWidthForRatio(double.infinity, 3), isNull);
      expect(decodeWidthForRatio(0, 3), isNull);
    });

    testWidgets('the request item photo decodes at its drawn width', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/parcels/77',
          FakeResponse(200, {..._parcel(77), 'item_photo_media_id': 501}),
        )
        ..on('GET', '/api/matches', FakeResponse(200, <Object>[]))
        ..on(
          'GET',
          '/api/parcels/77/pricing',
          FakeResponse(404, {'code': 'not_found', 'detail': 'n/a'}),
        )
        ..on(
          'GET',
          '/api/parcels/77/media/501/url',
          const FakeResponse(200, {
            'url': 'https://storage.invalid/signed/item.jpg',
            'expires_in': 300,
          }),
        );
      final container = await _signedIn(tester, backend);
      await pumpApp(
        tester,
        Builder(
          builder: (context) => MediaQuery(
            data: MediaQuery.of(context).copyWith(devicePixelRatio: 3),
            child: const RequestDetailScreen(requestId: 77),
          ),
        ),
        container: container,
      );
      await tester.pumpAndSettle();

      final photo = find.byWidgetPredicate(
        (w) =>
            w is Image &&
            w.image is ResizeImage &&
            (w.image as ResizeImage).imageProvider is NetworkImage,
      );
      expect(photo, findsOneWidget);
      final resize = tester.widget<Image>(photo).image as ResizeImage;
      final drawnWidth = tester.getSize(photo).width;
      expect(resize.width, (drawnWidth * 3).ceil());
      // Aspect ratio is kept: only the width is pinned.
      expect(resize.height, isNull);
    });
  });
}
