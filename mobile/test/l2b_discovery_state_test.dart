/// L2B: discovery's read models, below any widget.
///
/// Three properties are asserted here and nowhere else, because a screen test
/// cannot see them:
///
/// * a list pages on **the server's own cursor** and shows a row once;
/// * a card read for one member is **never shown to the next**, and a signed
///   out app reads only the public listings;
/// * two filters that say the same thing are the same read.
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/discovery_state.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/public_discovery.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';

/// Waits for a provider's future with the container's timers running.
Future<T> _ready<T>(AsyncValue<T> Function() read) async {
  for (var i = 0; i < 50; i++) {
    final value = read();
    if (value.hasValue && !value.isLoading) return value.requireValue;
    if (value.hasError && !value.isLoading) throw value.error!;
    await Future<void>.delayed(Duration.zero);
  }
  throw StateError('never settled');
}

Future<ProviderContainer> _signedIn(FakeBackend backend) async {
  final container = discoveryContainer(backend);
  addTearDown(container.dispose);
  await container.read(sessionProvider.notifier).restore();
  return container;
}

Map<String, dynamic> _row(int id) => tripCardFixture(id, name: 'Traveler $id');

void main() {
  group('paging on the server\'s cursor', () {
    test('sends next_offset as given, not the number of rows held', () async {
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (r) {
          final offset = (r.query['offset'] as int?) ?? 0;
          return switch (offset) {
            // Three rows, and a cursor that is deliberately not 3.
            0 => discoveryPage([_row(1), _row(2), _row(3)], next: 7),
            7 => discoveryPage([_row(8), _row(9)], next: null),
            _ => throw StateError('unexpected offset $offset'),
          };
        });
      final container = await _signedIn(backend);
      const filter = BrowseFilter();
      final sub = container.listen(tripFeedProvider(filter), (_, _) {});
      addTearDown(sub.close);

      final first = await _ready(
        () => container.read(tripFeedProvider(filter)),
      );
      expect(first.items.map((t) => t.journeyId), [1, 2, 3]);
      expect(first.hasMore, isTrue);

      await container.read(tripFeedProvider(filter).notifier).loadMore();
      final feed = container.read(tripFeedProvider(filter)).requireValue;
      expect(feed.items.map((t) => t.journeyId), [1, 2, 3, 8, 9]);
      expect(feed.hasMore, isFalse);

      final sent = backend.to('GET', '/api/discovery/trips');
      expect([for (final r in sent) r.query['offset']], [null, 7]);
      expect(sent.first.query['limit'], 20);
    });

    test('a row that moved between two pages is shown once', () async {
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (r) {
          final offset = (r.query['offset'] as int?) ?? 0;
          return offset == 0
              ? discoveryPage([_row(1), _row(2)], next: 2)
              : discoveryPage([_row(2), _row(3)], next: null);
        });
      final container = await _signedIn(backend);
      final sub = container.listen(
        tripFeedProvider(const BrowseFilter()),
        (_, _) {},
      );
      addTearDown(sub.close);
      await _ready(
        () => container.read(tripFeedProvider(const BrowseFilter())),
      );

      await container
          .read(tripFeedProvider(const BrowseFilter()).notifier)
          .loadMore();

      final ids = container
          .read(tripFeedProvider(const BrowseFilter()))
          .requireValue
          .items
          .map((t) => t.journeyId);
      expect(ids, [1, 2, 3]);
    });

    test(
      'loadMore does nothing without a cursor or while one is in flight',
      () async {
        final backend = discoveryBackend()
          ..on(
            'GET',
            '/api/discovery/requests',
            discoveryPage([requestCardFixture(1)]),
          );
        final container = await _signedIn(backend);
        const filter = BrowseFilter();
        final sub = container.listen(requestFeedProvider(filter), (_, _) {});
        addTearDown(sub.close);
        await _ready(() => container.read(requestFeedProvider(filter)));

        await container.read(requestFeedProvider(filter).notifier).loadMore();

        expect(backend.to('GET', '/api/discovery/requests'), hasLength(1));
      },
    );

    test('a failed next page keeps the rows and can be retried', () async {
      var failing = true;
      final backend = discoveryBackend()
        ..handle('GET', '/api/discovery/trips', (r) {
          final offset = (r.query['offset'] as int?) ?? 0;
          if (offset == 0) return discoveryPage([_row(1)], next: 1);
          return failing
              ? const FakeResponse(500, {'detail': 'boom'})
              : discoveryPage([_row(2)], next: null);
        });
      final container = await _signedIn(backend);
      const filter = BrowseFilter();
      final sub = container.listen(tripFeedProvider(filter), (_, _) {});
      addTearDown(sub.close);
      await _ready(() => container.read(tripFeedProvider(filter)));
      final notifier = container.read(tripFeedProvider(filter).notifier);

      await notifier.loadMore();
      var feed = container.read(tripFeedProvider(filter)).requireValue;
      expect(feed.items, hasLength(1), reason: 'the rows already read stay');
      expect(feed.loadMoreError, isNotNull);
      expect(feed.loadingMore, isFalse);
      expect(feed.hasMore, isTrue, reason: 'the cursor is kept for a retry');

      failing = false;
      await notifier.loadMore();
      feed = container.read(tripFeedProvider(filter)).requireValue;
      expect(feed.items.map((t) => t.journeyId), [1, 2]);
      expect(feed.loadMoreError, isNull);
    });

    test('a tier switched off is a state, not an error', () async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/discovery/people',
          const FakeResponse(200, {'state': 'disabled', 'results': <Object>[]}),
        );
      final container = await _signedIn(backend);
      final sub = container.listen(peopleFeedProvider(true), (_, _) {});
      addTearDown(sub.close);

      final feed = await _ready(() => container.read(peopleFeedProvider(true)));

      expect(feed.disabled, isTrue);
      expect(feed.items, isEmpty);
    });

    test('equal filters are one read, different filters are two', () async {
      final backend = discoveryBackend();
      final container = await _signedIn(backend);
      final a = BrowseFilter(
        origin: PlaceRef(placeId: 1, label: 'Paris', countryCode: 'FR'),
      );
      final b = BrowseFilter(
        origin: PlaceRef(placeId: 1, label: 'Paris (FR)', countryCode: 'FR'),
      );
      final c = BrowseFilter(
        origin: PlaceRef(placeId: 3, label: 'Lyon', countryCode: 'FR'),
      );
      for (final f in [a, b, c]) {
        final sub = container.listen(tripFeedProvider(f), (_, _) {});
        addTearDown(sub.close);
        await _ready(() => container.read(tripFeedProvider(f)));
      }

      final sent = backend.to('GET', '/api/discovery/trips');
      expect([for (final r in sent) r.query['origin_place_id']], [1, 3]);
    });
  });

  group('one viewer\'s cards are never shown to the next', () {
    test('a sign-out drops the member\'s value, the guest reads the public '
        'listings, and a sign-in reads them again for the member', () async {
      var account = 42;
      var viewer = 'A';
      final backend = discoveryBackend()
        ..handle(
          'GET',
          '/api/me',
          (_) => FakeResponse(200, {...meFixture(), 'id': account}),
        )
        ..handle(
          'GET',
          '/api/discovery/trips',
          (_) => discoveryPage([tripCardFixture(1, name: '$viewer-card')]),
        )
        ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}));
      final container = await _signedIn(backend);
      final sub = container.listen(previewTripsProvider(null), (_, _) {});
      addTearDown(sub.close);
      final a = await _ready(() => container.read(previewTripsProvider(null)));
      expect(a.results.single.traveler.displayName, 'A-card');

      viewer = 'guest';
      await container.read(sessionProvider.notifier).signOut();

      final whileSignedOut = container.read(previewTripsProvider(null));
      expect(
        whileSignedOut.ofCurrentAccount.hasValue,
        isFalse,
        reason: 'the previous account\'s card must not be readable',
      );
      final guest = await _ready(
        () => container.read(previewTripsProvider(null)),
      );
      expect(guest.results.single.traveler.displayName, 'guest-card');

      // The guest signs in. Their public cards may stay on screen while the
      // member's read is in flight, so the screen under the account moment
      // stays as it was; the previous member's never come back.
      account = 99;
      viewer = 'B';
      await container.read(sessionProvider.notifier).restore();
      final inFlight = container
          .read(previewTripsProvider(null))
          .ofCurrentAccount;
      expect(
        inFlight.value?.results.single.traveler.displayName,
        anyOf(isNull, 'guest-card'),
      );
      final b = await _ready(() => container.read(previewTripsProvider(null)));
      expect(b.results.single.traveler.displayName, 'B-card');
      expect(backend.to('GET', '/api/discovery/trips'), hasLength(3));
    });

    test('signed out, only the public listings are read', () async {
      // Nothing stored: the app opens as a guest.
      final backend = discoveryBackend();
      final store = FakeTokenStore(refresh: null);
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          tokenStoreProvider.overrideWithValue(store),
          apiClientProvider.overrideWithValue(apiClientFor(backend, store)),
        ],
      );
      addTearDown(container.dispose);
      await container.read(sessionProvider.notifier).restore();
      expect(container.read(sessionProvider), isA<SessionSignedOut>());

      final subs = [
        container.listen(senderMatchesProvider, (_, _) {}),
        container.listen(travelerMatchesProvider, (_, _) {}),
        container.listen(previewTripsProvider(null), (_, _) {}),
        container.listen(tripFeedProvider(const BrowseFilter()), (_, _) {}),
        container.listen(ownProfileProvider, (_, _) {}),
        container.listen(routeAlertsProvider, (_, _) {}),
      ];
      addTearDown(() {
        for (final s in subs) {
          s.close();
        }
      });
      await _ready(() => container.read(previewTripsProvider(null)));
      await _ready(
        () => container.read(tripFeedProvider(const BrowseFilter())),
      );
      final alerts = await _ready(() => container.read(routeAlertsProvider));

      expect(alerts, isEmpty);
      expect(
        backend.requests
            .where((r) => r.path.startsWith('/api/discovery'))
            .map((r) => r.path)
            .toSet(),
        {'/api/discovery/trips'},
        reason: 'matches, the own profile and alerts are a member\'s',
      );
    });
  });
}
