/// L13B: the Reviews screen, the report sheet and My ratings.
///
/// The server decides which reviews count and whether a viewer may report one;
/// each test drives a small fake of it and asserts what the screen shows from
/// what the server then says.
library;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/domain/reviews.dart';
import 'package:shiptrip/domain/public_discovery.dart';
import 'package:shiptrip/features/discovery/browse_screens.dart';
import 'package:shiptrip/features/discovery/person_screen.dart';
import 'package:shiptrip/features/profile/ratings_screen.dart';
import 'package:shiptrip/features/reviews/reviews_screen.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

Map<String, dynamic> _review(
  int id, {
  int score = 5,
  String? comment = 'Careful and on time',
  bool removed = false,
  String by = 'sender',
  Object? myReport,
}) => {
  'id': id,
  'score': score,
  'tags': ['on_time'],
  'comment': comment,
  'comment_removed': removed,
  'written_by': by,
  'month': '2026-11',
  'my_report': myReport,
};

Map<String, dynamic> _page(
  List<Map<String, dynamic>> rows, {
  int? next,
  Object? rating = const {'state': 'rated', 'average': 4.5, 'count': 2},
  String state = 'results',
}) => {'state': state, 'rating': rating, 'results': rows, 'next_offset': next};

Map<String, dynamic> _error(String code) => {'code': code, 'detail': code};

const _person = PersonReviews('p-1');

Future<FakeBackend> _backendWith(Map<String, dynamic> page) async =>
    discoveryBackend()
      ..on('GET', '/api/discovery/people/p-1/reviews', FakeResponse(200, page));

void main() {
  group('the Reviews screen', () {
    testWidgets('shows the server summary and the reviews, never an author', (
      tester,
    ) async {
      final backend = await _backendWith(
        _page([
          _review(1),
          _review(2, score: 4, comment: null, by: 'traveler'),
        ]),
      );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );

      expect(find.text('Reviews'), findsOneWidget);
      expect(find.text('4.5'), findsOneWidget);
      expect(find.text('2 reviews'), findsOneWidget);
      expect(find.text('Careful and on time'), findsOneWidget);
      expect(find.textContaining('From a sender'), findsOneWidget);
      expect(find.textContaining('From a traveler'), findsOneWidget);
      expect(find.text('on time'), findsNWidgets(2));
    });

    testWidgets('a hidden comment says Wassla removed it', (tester) async {
      final backend = await _backendWith(
        _page([_review(1, comment: null, removed: true)]),
      );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );

      expect(find.text('Comment removed by Wassla'), findsOneWidget);
    });

    testWidgets('pages on the server cursor and drops a repeated row', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/people/p-1/reviews', (r) {
          final offset = r.query['offset'];
          return FakeResponse(
            200,
            offset == null
                ? _page([
                    for (var i = 1; i <= 8; i++) _review(i, comment: 'row $i'),
                  ], next: 8)
                : _page([
                    _review(8, comment: 'row 8'),
                    _review(9, comment: 'row 9'),
                  ]),
          );
        });
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );

      await tester.drag(find.byType(ListView), const Offset(0, -4000));
      await tester.pumpAndSettle();

      final reads = backend.to('GET', '/api/discovery/people/p-1/reviews');
      expect(reads, hasLength(2));
      expect(reads.last.query['offset'], 8);
      expect(find.text('row 9'), findsOneWidget);
      expect(find.text('row 8'), findsOneWidget);
    });

    testWidgets('no reviews yet is an empty state', (tester) async {
      final backend = await _backendWith(_page(const [], rating: null));
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      expect(find.text('No reviews yet'), findsOneWidget);
    });

    testWidgets('a switched-off tier is not an error', (tester) async {
      final backend = await _backendWith(
        _page(const [], rating: null, state: 'disabled'),
      );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      expect(find.text('Reviews are not available'), findsOneWidget);
    });

    testWidgets('an unknown or unlisted subject is a calm dead end', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips/31/reviews',
          FakeResponse(404, _error('trip_not_found')),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: TripReviews(31)),
        backend,
      );
      expect(find.text('This is not available any more'), findsOneWidget);
    });

    testWidgets('a failed read offers a retry', (tester) async {
      var calls = 0;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/people/p-1/reviews', (_) {
          calls++;
          return calls == 1
              ? FakeResponse(500, _error('server_error'))
              : FakeResponse(200, _page([_review(1)]));
        });
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      expect(find.text('Try again'), findsOneWidget);

      await tester.tap(find.text('Try again'));
      await tester.pumpAndSettle();
      expect(find.text('Careful and on time'), findsOneWidget);
    });

    testWidgets('from Find Travelers the request id is sent', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips/31/reviews',
          FakeResponse(200, _page([_review(1)])),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: TripReviews(31, requestId: 7)),
        backend,
      );

      final read = backend.to('GET', '/api/discovery/trips/31/reviews').single;
      expect(read.query['request'], 7);
    });
  });

  group('reporting a review', () {
    Future<void> openSheet(WidgetTester tester) async {
      await tester.tap(find.byIcon(Icons.more_vert_rounded));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Report'));
      await tester.pumpAndSettle();
    }

    testWidgets('files the reason and note, then says it was received', (
      tester,
    ) async {
      final backend = await _backendWith(_page([_review(31)]))
        ..on(
          'POST',
          '/api/ratings/31/reports',
          FakeResponse(201, {
            'rating_id': 31,
            'state': 'received',
            'reported_at': '2026-11-14T09:00:00Z',
          }),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      await openSheet(tester);

      expect(find.text('Report this review'), findsOneWidget);
      for (final reason in [
        'Offensive or abusive',
        'Shares personal information',
        'Not about the delivery',
        'Not true',
        'Something else',
      ]) {
        expect(find.text(reason), findsOneWidget);
      }
      // Nothing is chosen yet, so nothing can be sent.
      expect(
        tester.widget<AppButton>(find.byType(AppButton)).onPressed,
        isNull,
      );

      await tester.tap(find.text('Not true'));
      await tester.enterText(find.byType(TextField), 'This is invented');
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      final sent = backend.to('POST', '/api/ratings/31/reports').single;
      expect(sent.body, {'reason': 'untrue', 'note': 'This is invented'});
      expect(find.text('Thanks, we will review it'), findsOneWidget);
      expect(
        find.text('You reported this. We have received it.'),
        findsOneWidget,
      );
      expect(
        find.byIcon(Icons.more_vert_rounded),
        findsNothing,
        reason: 'a reported review offers nothing more',
      );
    });

    testWidgets('a review already reviewed says so and has no menu', (
      tester,
    ) async {
      final backend = await _backendWith(
        _page([_review(31, myReport: 'reviewed')]),
      );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );

      expect(
        find.text('You reported this. We have reviewed it.'),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.more_vert_rounded), findsNothing);
    });

    testWidgets('a trip opened from Find Travelers reports with its context', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips/31/reviews',
          FakeResponse(200, _page([_review(5)])),
        )
        ..on(
          'POST',
          '/api/ratings/5/reports',
          FakeResponse(201, {'rating_id': 5, 'state': 'received'}),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: TripReviews(31, requestId: 7)),
        backend,
      );
      await openSheet(tester);
      await tester.tap(find.text('Something else'));
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      expect(backend.to('POST', '/api/ratings/5/reports').single.body, {
        'reason': 'other',
        'journey': 31,
        'request': 7,
      });
    });

    testWidgets('a trip opened without a request sends no context', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips/31/reviews',
          FakeResponse(200, _page([_review(5)])),
        )
        ..on(
          'POST',
          '/api/ratings/5/reports',
          FakeResponse(201, {'rating_id': 5, 'state': 'received'}),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: TripReviews(31)),
        backend,
      );
      await openSheet(tester);
      await tester.tap(find.text('Offensive or abusive'));
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      expect(backend.to('POST', '/api/ratings/5/reports').single.body, {
        'reason': 'offensive',
      });
    });

    testWidgets('a refusal is said in words and a gone review re-reads', (
      tester,
    ) async {
      var reads = 0;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/people/p-1/reviews', (_) {
          reads++;
          return FakeResponse(200, _page([_review(31)]));
        })
        ..on(
          'POST',
          '/api/ratings/31/reports',
          FakeResponse(409, _error('review_removed')),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      await openSheet(tester);
      await tester.tap(find.text('Not true'));
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      expect(find.text('Wassla has already removed this review.'), findsOne);
      expect(reads, 2, reason: 'the list behind the sheet re-reads');
      // The sheet stays, and nothing claims the report went through.
      expect(find.text('Send report'), findsOneWidget);
    });

    testWidgets('your own review cannot be reported', (tester) async {
      final backend = await _backendWith(_page([_review(31)]))
        ..on(
          'POST',
          '/api/ratings/31/reports',
          FakeResponse(409, _error('own_review')),
        );
      await pumpDiscovery(
        tester,
        const ReviewsScreen(subject: _person),
        backend,
      );
      await openSheet(tester);
      await tester.tap(find.text('Not true'));
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      expect(find.text('You cannot report your own review.'), findsOneWidget);
    });
  });

  group('the way in', () {
    Map<String, dynamic> personPage(Object? rating) => {
      'state': 'results',
      'profile': {...profileCardFixture(), 'rating': rating},
      'trips': <Object>[],
      'requests': <Object>[],
    };

    testWidgets('tapping a rating on the person page opens its reviews', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(
            200,
            personPage({'state': 'rated', 'average': 4.8, 'count': 24}),
          ),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
        extraRoutes: [marker(Routes.reviewsPerson, '/reviews/person/:id')],
      );

      await tester.tap(find.text('4.8 · 24 reviews'));
      await tester.pumpAndSettle();

      expect(find.textContaining('at reviews-person'), findsOneWidget);
      expect(find.textContaining('p-1'), findsOneWidget);
    });

    testWidgets('a new person has no reviews to open', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people/p-1',
          FakeResponse(
            200,
            personPage({'state': 'new', 'average': null, 'count': 0}),
          ),
        );
      await pumpDiscovery(
        tester,
        const PersonScreen(profileId: 'p-1'),
        backend,
      );

      expect(find.text('New'), findsOneWidget);
      expect(find.textContaining('reviews'), findsNothing);
    });
  });

  group('the trip preview', () {
    testWidgets('a rated traveler opens the trip reviews, no request', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/trips',
          discoveryPage([tripCardFixture(11, name: 'Nadia')]),
        );
      await pumpDiscovery(
        tester,
        const BrowseTripsScreen(),
        backend,
        extraRoutes: [marker(Routes.reviewsTrip, '/reviews/trip/:id')],
      );

      await tester.tap(find.text('Nadia'));
      await tester.pumpAndSettle();
      // The card itself shows the average and nothing of any review.
      await tester.tap(find.text('4.8 · 24 reviews'));
      await tester.pumpAndSettle();

      expect(find.text('at reviews-trip {id: 11} {}'), findsOneWidget);
    });
  });

  group('the contract', () {
    test('a person card reads the server rating object', () {
      final rated = PublicPerson.fromJson(
        discoveryPersonFields(
          rating: {'state': 'rated', 'average': 4.5, 'count': 2},
        ),
      );
      expect(rated.hasRating, isTrue);
      expect(rated.rating.average, 4.5);
      expect(rated.rating.count, 2);

      final fresh = PublicPerson.fromJson(
        discoveryPersonFields(
          rating: {'state': 'new', 'average': null, 'count': 0},
        ),
      );
      expect(fresh.hasRating, isFalse);
    });

    test('a review page reads the summary, the rows and the cursor', () {
      final page = ReviewsPage.fromJson(
        _page([
          _review(1, myReport: 'reviewed', comment: null, removed: true),
        ], next: 20),
      );
      expect(page.rating?.count, 2);
      expect(page.nextOffset, 20);
      expect(page.results.single.commentRemoved, isTrue);
      expect(page.results.single.myReport, MyReport.reviewed);
      expect(page.results.single.month, DateTime(2026, 11));
    });
  });

  group('My ratings', () {
    Map<String, dynamic> row(
      int id,
      int score, {
      String? moderation,
      Object? myReport,
      String? comment = 'Nice',
    }) => {
      'id': id,
      'deal_id': id,
      'score': score,
      'tags': <String>[],
      'comment': comment,
      'is_revealed': true,
      'created_at': '2026-09-01T10:00:00Z',
      'moderation': moderation,
      'my_report': myReport,
    };

    testWidgets('a removed rating says so and is not in the average', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/users/me/ratings',
          FakeResponse(200, [row(1, 4), row(2, 1, moderation: 'removed')]),
        );
      await pumpDiscovery(tester, const RatingsScreen(), backend);

      expect(find.text('Removed by Wassla, not counted'), findsOneWidget);
      expect(find.text('4.0 (1)'), findsOneWidget);
    });

    testWidgets('a hidden comment is marked and still counts', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/users/me/ratings',
          FakeResponse(200, [
            row(1, 4),
            row(2, 2, moderation: 'comment_hidden'),
          ]),
        );
      await pumpDiscovery(tester, const RatingsScreen(), backend);

      expect(
        find.text(
          'Wassla hid the comment from others. The score still counts.',
        ),
        findsOneWidget,
      );
      expect(find.text('3.0 (2)'), findsOneWidget);
    });

    testWidgets('reports a received rating, once', (tester) async {
      var reported = false;
      final backend = discoveryBackend()
        ..handle(
          'GET',
          '/api/users/me/ratings',
          (_) => FakeResponse(200, [
            row(1, 2, myReport: reported ? 'received' : null),
          ]),
        )
        ..handle('POST', '/api/ratings/1/reports', (_) {
          reported = true;
          return FakeResponse(201, {'rating_id': 1, 'state': 'received'});
        });
      await pumpDiscovery(tester, const RatingsScreen(), backend);

      await tester.tap(find.byIcon(Icons.more_vert_rounded));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Report'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Offensive or abusive'));
      await tester.pump();
      await tester.tap(find.text('Send report'));
      await tester.pumpAndSettle();

      expect(
        find.text('You reported this. We have received it.'),
        findsOneWidget,
      );
      expect(find.byIcon(Icons.more_vert_rounded), findsNothing);
    });

    testWidgets('a removed rating offers no report', (tester) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/users/me/ratings',
          FakeResponse(200, [row(1, 1, moderation: 'removed')]),
        );
      await pumpDiscovery(tester, const RatingsScreen(), backend);

      expect(find.byIcon(Icons.more_vert_rounded), findsNothing);
    });
  });

  group('layout', () {
    for (final device in [
      DeviceProfile.smallAndroid,
      DeviceProfile.largeText,
    ]) {
      for (final locale in [const Locale('en'), const Locale('ar')]) {
        testWidgets('no overflow on ${device.name} in ${locale.languageCode}', (
          tester,
        ) async {
          final backend = await _backendWith(
            _page([
              _review(1, comment: 'A long comment ' * 12),
              _review(2, comment: null, removed: true),
              _review(3, myReport: 'received'),
            ]),
          );
          await pumpDiscovery(
            tester,
            const ReviewsScreen(subject: _person),
            backend,
            device: device,
            locale: locale,
          );
          expect(tester.takeException(), isNull);
        });
      }
    }
  });
}
