/// K5: how long a read lives, and who shares it.
///
/// A read that no screen wants any more is cancelled; a read two callers want
/// at once is sent once; a write is never cancelled because a screen went
/// away; and nothing a previous sign-in held — a read, a cached page, a role —
/// reaches the next one. Everything below the repositories is the real
/// `ApiClient` with its auth interceptor, over the in-process fake backend.
library;

import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/find_travelers.dart';
import 'package:shiptrip/features/requests/discovery_screen.dart';

import 'support/fake_api.dart';

/// Real time, not just turns of the event loop: live events are coalesced on
/// a 75 ms timer before any provider hears of them.
Future<void> _waitFor(bool Function() condition) async {
  for (var i = 0; i < 400 && !condition(); i++) {
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  expect(condition(), isTrue);
}

class _TokenStore extends FakeTokenStore {
  @override
  Future<String> readOrCreateInstallationId() async => 'installation';
}

Future<ProviderContainer> _signedIn(
  FakeBackend backend, {
  FakeTokenStore? tokens,
}) async {
  final container = containerFor(backend, tokens: tokens);
  addTearDown(container.dispose);
  container.read(sessionProvider);
  await _waitFor(() => container.read(sessionProvider) is SessionSignedIn);
  return container;
}

FakeBackend _backend() =>
    FakeBackend()..on('GET', '/api/me', FakeResponse(200, meFixture()));

class _Discovery implements MatchingRepository {
  final calls = <({String sort, int offset, CancelToken? token})>[];
  final replies = <Completer<FindTravelersPage>>[];

  @override
  Future<FindTravelersPage> findTravelers({
    required int parcelId,
    int? limit,
    int? offset,
    String? sort,
    CancelToken? cancelToken,
  }) {
    calls.add((
      sort: sort ?? 'best_match',
      offset: offset ?? 0,
      token: cancelToken,
    ));
    final reply = Completer<FindTravelersPage>();
    replies.add(reply);
    return reply.future;
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

FindTravelersPage _page(String sort, List<int> journeys) => FindTravelersPage(
  state: DiscoveryState.results,
  sort: sort,
  page: const DiscoveryPageInfo(
    limit: 10,
    offset: 0,
    total: 1,
    hasMore: false,
    nextOffset: null,
  ),
  candidates: [
    for (final id in journeys) TravelerCandidate.fromJson({'journey_id': id}),
  ],
);

/// Counts Deal-history controllers mounted in a container. A rebuild is not a
/// mount, so a count that grows means the previous one was released.
final class _HistoryMounts extends ProviderObserver {
  int count = 0;

  @override
  void didAddProvider(ProviderObserverContext context, Object? value) {
    if ('${context.provider}'.contains('DealHistoryController')) count++;
  }
}

void main() {
  group('cancellation follows the provider', () {
    test('an abandoned Deal detail read is cancelled, not delivered', () async {
      final reply = Completer<FakeResponse>();
      final backend = _backend()
        ..handle('GET', '/api/deals/7', (_) => reply.future);
      final container = await _signedIn(backend);

      final seen = <AsyncValue<Deal>>[];
      final screen = container.listen(
        dealDetailProvider(7),
        (_, next) => seen.add(next),
        fireImmediately: true,
      );
      await _waitFor(() => backend.to('GET', '/api/deals/7').isNotEmpty);

      screen.close(); // the user backs out before the Deal arrives
      await _waitFor(() => backend.lastTo('GET', '/api/deals/7')!.cancelled);
      reply.complete(FakeResponse(200, dealFixture()));
      await pumpEventQueue();

      expect(seen.where((value) => value.hasError), isEmpty);
    });

    test('a read superseded by a live event is cancelled without an error '
        'state', () async {
      final first = Completer<FakeResponse>();
      var reads = 0;
      final backend = _backend()
        ..handle('GET', '/api/deals/7', (_) {
          reads++;
          return reads == 1
              ? first.future
              : FakeResponse(200, dealFixture(status: 'in_transit'));
        });
      final container = await _signedIn(backend);
      container.read(liveUpdatesProvider).bindAccount(42);

      final seen = <AsyncValue<Deal>>[];
      final screen = container.listen(
        dealDetailProvider(7),
        (_, next) => seen.add(next),
        fireImmediately: true,
      );
      addTearDown(screen.close);
      await _waitFor(() => reads == 1);

      container.read(liveUpdatesProvider).ingest({
        'type': 'deal.updated',
        'event_id': 'e-1',
        'payload': {'deal_id': 7},
      }, source: LiveEventSource.websocket);
      await _waitFor(() => reads == 2);
      await _waitFor(() => container.read(dealDetailProvider(7)).hasValue);

      expect(backend.to('GET', '/api/deals/7').first.cancelled, isTrue);
      first.complete(FakeResponse(200, dealFixture()));
      await pumpEventQueue();

      expect(seen.where((value) => value.hasError), isEmpty);
      expect(
        container.read(dealDetailProvider(7)).value?.status,
        DealStatus.inTransit,
      );
    });

    test(
      'a write in flight is never cancelled when its screen goes away',
      () async {
        final written = Completer<FakeResponse>();
        final backend = _backend()
          ..on('GET', '/api/deals/7', FakeResponse(200, dealFixture()))
          ..handle('PUT', '/api/deals/7/recipient', (_) => written.future);
        final container = await _signedIn(backend);

        final screen = container.listen(dealDetailProvider(7), (_, _) {});
        await _waitFor(() => container.read(dealDetailProvider(7)).hasValue);

        final saving = container
            .read(dealRepositoryProvider)
            .setRecipient(
              dealId: 7,
              fullName: 'Yacine',
              email: 'y@example.com',
            );
        await _waitFor(
          () => backend.to('PUT', '/api/deals/7/recipient').isNotEmpty,
        );
        screen.close();
        await pumpEventQueue();

        written.complete(FakeResponse(200, {'deal': dealFixture()}));
        final deal = await saving;

        expect(deal.id, 7);
        expect(
          backend.lastTo('PUT', '/api/deals/7/recipient')!.cancelled,
          isFalse,
        );
      },
    );

    test('a superseded or abandoned traveller search is cancelled', () async {
      final repository = _Discovery();
      final controller = FindTravelersController(
        requestId: 42,
        repository: repository,
      );
      repository.replies.first.complete(_page('best_match', [1]));
      await _waitFor(() => !controller.isLoading);

      unawaited(controller.setSort('reward_low_high'));
      unawaited(controller.setSort('soonest_departure'));
      expect(repository.calls[1].token?.isCancelled, isTrue);
      expect(repository.calls[2].token?.isCancelled, isFalse);

      // Leaving the screen mid-search: the read is dropped and nothing is
      // announced to listeners that no longer exist.
      controller.dispose();
      expect(repository.calls[2].token?.isCancelled, isTrue);
      repository.replies[2].complete(_page('soonest_departure', [9]));
      repository.replies[1].complete(_page('reward_low_high', [8]));
      await pumpEventQueue();
    });
  });

  group('in-flight GET sharing', () {
    test('concurrent identical shared reads send one request, and each '
        'caller gets its own copy', () async {
      final reply = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) => reply.future);
      final api = apiClientFor(backend);

      final first = api.getObject('/api/me', share: true);
      final second = api.getObject('/api/me', share: true);
      await _waitFor(() => backend.requests.isNotEmpty);
      reply.complete(FakeResponse(200, meFixture()));
      final results = await Future.wait([first, second]);

      expect(backend.to('GET', '/api/me'), hasLength(1));
      expect(results.first, results.last);
      expect(identical(results.first, results.last), isFalse);
    });

    test('unshared reads are never joined', () async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()));
      final api = apiClientFor(backend);

      await Future.wait([api.getObject('/api/me'), api.getObject('/api/me')]);

      expect(backend.to('GET', '/api/me'), hasLength(2));
    });

    test('a read from another sign-in is never joined', () async {
      final replies = <Completer<FakeResponse>>[];
      final backend = FakeBackend()
        ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
        ..handle('GET', '/api/me', (_) {
          final reply = Completer<FakeResponse>();
          replies.add(reply);
          return reply.future;
        });
      final core = backend.session;
      await core.load();
      final api = apiClientFor(backend);

      final before = api.getObject('/api/me', share: true);
      await _waitFor(() => replies.length == 1);
      // Sign-out and sign-in happened meanwhile.
      await core.end('sid-a', EndReason.signedOut);
      await core.signedIn(core.reserve()!, signInFor(sid: 'sid-b'));
      final after = api.getObject('/api/me', share: true);
      await _waitFor(() => replies.length == 2);
      for (final reply in replies) {
        reply.complete(FakeResponse(200, meFixture()));
      }

      await expectLater(
        before,
        throwsA(
          isA<ApiException>().having(
            (e) => e.kind,
            'kind',
            ApiFailureKind.cancelled,
          ),
        ),
      );
      expect((await after)['id'], 42);
      expect(backend.to('GET', '/api/me'), hasLength(2));
    });

    test(
      'one caller leaving does not cancel the read for the others',
      () async {
        final reply = Completer<FakeResponse>();
        final backend = FakeBackend()
          ..handle('GET', '/api/me', (_) => reply.future);
        final api = apiClientFor(backend);

        final leaving = CancelToken();
        final left = api.getObject(
          '/api/me',
          share: true,
          cancelToken: leaving,
        );
        final staying = api.getObject('/api/me', share: true);
        await _waitFor(() => backend.requests.isNotEmpty);
        leaving.cancel();

        await expectLater(
          left,
          throwsA(
            isA<ApiException>().having(
              (e) => e.kind,
              'kind',
              ApiFailureKind.cancelled,
            ),
          ),
        );
        reply.complete(FakeResponse(200, meFixture()));
        expect((await staying)['id'], 42);
        expect(backend.lastTo('GET', '/api/me')!.cancelled, isFalse);
      },
    );

    test('when every caller leaves the read is cancelled, and the next one '
        'starts fresh', () async {
      final replies = <Completer<FakeResponse>>[];
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          final reply = Completer<FakeResponse>();
          replies.add(reply);
          return reply.future;
        });
      final api = apiClientFor(backend);

      final a = CancelToken();
      final b = CancelToken();
      final first = api.getObject('/api/me', share: true, cancelToken: a);
      final second = api.getObject('/api/me', share: true, cancelToken: b);
      await _waitFor(() => replies.length == 1);
      a.cancel();
      b.cancel();
      await expectLater(first, throwsA(isA<ApiException>()));
      await expectLater(second, throwsA(isA<ApiException>()));
      await _waitFor(() => backend.requests.single.cancelled);

      final next = api.getObject('/api/me', share: true);
      await _waitFor(() => replies.length == 2);
      replies.last.complete(FakeResponse(200, meFixture()));
      expect((await next)['id'], 42);
    });

    test('a read started before a write is not shared after it', () async {
      final replies = <Completer<FakeResponse>>[];
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          final reply = Completer<FakeResponse>();
          replies.add(reply);
          return reply.future;
        })
        ..on('POST', '/api/kyc/submit', const FakeResponse(200));
      final api = apiClientFor(backend);

      final stale = api.getObject('/api/me', share: true);
      await _waitFor(() => replies.length == 1);
      await api.postVoid('/api/kyc/submit');
      final fresh = api.getObject('/api/me', share: true);
      await _waitFor(() => replies.length == 2);
      for (final reply in replies) {
        reply.complete(FakeResponse(200, meFixture()));
      }
      await Future.wait([stale, fresh]);

      expect(backend.to('GET', '/api/me'), hasLength(2));
    });

    test('a failure reaches every caller and is not remembered', () async {
      var reads = 0;
      final reply = Completer<FakeResponse>();
      final backend = FakeBackend()
        ..handle('GET', '/api/me', (_) {
          reads++;
          return reads == 1 ? reply.future : FakeResponse(200, meFixture());
        });
      final api = apiClientFor(backend);

      final first = api.getObject('/api/me', share: true);
      final second = api.getObject('/api/me', share: true);
      await _waitFor(() => reads == 1);
      reply.complete(const FakeResponse(503));
      await expectLater(first, throwsA(isA<ApiException>()));
      await expectLater(second, throwsA(isA<ApiException>()));

      expect((await api.getObject('/api/me', share: true))['id'], 42);
      expect(reads, 2);
    });

    test(
      'a profile refresh and two socket token probes read /api/me once',
      () async {
        var reads = 0;
        final reply = Completer<FakeResponse>();
        final backend = FakeBackend()
          ..handle('GET', '/api/me', (_) {
            reads++;
            return reads == 1 ? FakeResponse(200, meFixture()) : reply.future;
          });
        final container = await _signedIn(backend);

        final refresh = container
            .read(sessionProvider.notifier)
            .refreshAccount();
        final probes = [
          container.read(authRepositoryProvider).me(),
          container.read(authRepositoryProvider).me(),
        ];
        await _waitFor(() => reads == 2);
        reply.complete(FakeResponse(200, meFixture()));
        await Future.wait([refresh, ...probes]);

        expect(reads, 2, reason: 'one at sign-in, one shared by all three');
      },
    );
  });

  group('badge counts', () {
    test('the bell and "Mark all read" come from one read', () async {
      var reads = 0;
      final backend = _backend()
        ..handle('GET', '/api/notifications/unread-count', (_) {
          reads++;
          return const FakeResponse(200, {'active': 3, 'unread_active': 2});
        });
      final container = await _signedIn(backend);

      final bell = container.listen(unreadNotificationsProvider, (_, _) {});
      final inbox = container.listen(
        unreadActiveNotificationsProvider,
        (_, _) {},
      );
      addTearDown(bell.close);
      addTearDown(inbox.close);
      await _waitFor(
        () =>
            container.read(unreadNotificationsProvider).hasValue &&
            container.read(unreadActiveNotificationsProvider).hasValue,
      );
      expect(container.read(unreadNotificationsProvider).value, 3);
      expect(container.read(unreadActiveNotificationsProvider).value, 2);
      expect(reads, 1);

      // Pull-to-refresh and mark-read invalidate both; still one read.
      container
        ..invalidate(unreadNotificationsProvider)
        ..invalidate(unreadActiveNotificationsProvider);
      await _waitFor(() => reads >= 2);
      await pumpEventQueue();
      expect(reads, 2);
    });
  });

  group('derived state', () {
    test('a profile refresh does not recompute what needs the user', () async {
      final backend = _backend()
        ..fallback = (_) => const FakeResponse(200, <Object>[]);
      final container = await _signedIn(backend);

      var recomputed = 0;
      final attention = container.listen(
        attentionProvider,
        (_, _) => recomputed++,
      );
      addTearDown(attention.close);
      await _waitFor(
        () =>
            container.read(currentDealsProvider).hasValue &&
            container.read(matchesProvider).hasValue,
      );
      await pumpEventQueue();
      final settled = recomputed;

      await container.read(sessionProvider.notifier).refreshAccount();
      await pumpEventQueue();

      expect(recomputed, settled);
    });
  });

  group('history grace period', () {
    testWidgets('unviewed history hit by a live Deal event is still released '
        'within its grace period', (tester) async {
      final backend = _backend()
        ..handle(
          'GET',
          '/api/deals',
          (_) => FakeResponse(200, {
            'count': 1,
            'next': null,
            'results': [dealFixture(status: 'completed')],
          }),
        );
      // A widget test for the fake clock: the grace period is a minute.
      final mounts = _HistoryMounts();
      final tokens = FakeTokenStore();
      final container = ProviderContainer(
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          sessionCoreProvider.overrideWithValue(backend.session),
          apiClientProvider.overrideWithValue(apiClientFor(backend)),
        ],
        observers: [mounts],
      );
      addTearDown(container.dispose);
      Future<void> settle() async {
        for (var i = 0; i < 20; i++) {
          await tester.pump(const Duration(milliseconds: 10));
        }
      }

      container.read(sessionProvider);
      await settle();
      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      container.read(liveUpdatesProvider).bindAccount(42);

      var screen = container.listen(historyDealsProvider, (_, _) {});
      await settle();
      expect(container.read(historyDealsProvider).value, hasLength(1));
      expect(mounts.count, 1);
      final reads = backend.to('GET', '/api/deals').length;

      // The user switches away from History, then a Deal changes.
      screen.close();
      await tester.pump(const Duration(seconds: 10));
      container.read(liveUpdatesProvider).ingest({
        'type': 'deal.updated',
        'event_id': 'e-history',
        'payload': {'deal_id': 7},
      }, source: LiveEventSource.websocket);
      await tester.pump(const Duration(milliseconds: 200));
      expect(
        backend.to('GET', '/api/deals'),
        hasLength(reads),
        reason: 'history nobody is looking at is not re-read',
      );
      await tester.pump(DealHistoryController.keptFor);

      // Back to History: a new controller, so the old one was released.
      screen = container.listen(historyDealsProvider, (_, _) {});
      await settle();
      expect(mounts.count, 2);
      expect(backend.to('GET', '/api/deals'), hasLength(reads + 1));

      // And the grace period still ends for the new one.
      screen.close();
      await tester.pump(DealHistoryController.keptFor);
      screen = container.listen(historyDealsProvider, (_, _) {});
      await settle();
      expect(mounts.count, 3);
      screen.close();
      await tester.pump(DealHistoryController.keptFor);
    });
  });

  group('sign-out and account switch', () {
    test(
      'sign-out completes and the next account starts from its own role',
      () async {
        final tokens = _TokenStore();
        final backend = _backend()
          ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
          ..on(
            'POST',
            '/api/auth/sign-in',
            FakeResponse(200, {
              'access': fakeToken('b', 'access'),
              'refresh': fakeToken('b'),
              'user': {...meFixture(), 'id': 77, 'email': 'b@example.com'},
            }),
          );
        final container = await _signedIn(backend, tokens: tokens);
        final role = container.listen(roleContextProvider, (_, _) {});
        addTearDown(role.close);

        // Account A, able to do both, switches to carrying.
        container.read(roleContextProvider.notifier).set(RoleContext.traveler);
        expect(container.read(roleContextProvider), RoleContext.traveler);

        await container.read(sessionProvider.notifier).signOut();
        await container
            .read(sessionProvider.notifier)
            .signIn(email: 'b@example.com', password: 'secret');
        await pumpEventQueue();

        expect(container.read(accountProvider)?.id, 77);
        expect(await tokens.readRoleContext(), RoleContext.sender.wire);
        expect(
          container.read(roleContextProvider),
          RoleContext.sender,
          reason: 'account B must not inherit account A\'s traveller choice',
        );
      },
    );

    test('a refused session tears down without an error', () async {
      final container = await _signedIn(_backend(), tokens: _TokenStore());
      final role = container.listen(roleContextProvider, (_, _) {});
      addTearDown(role.close);

      final core = container.read(sessionCoreProvider);
      await core.end(core.current!.sid, EndReason.refused);

      expect(
        container.read(sessionProvider),
        isA<SessionSignedOut>().having(
          (state) => state.becauseExpired,
          'becauseExpired',
          isTrue,
        ),
      );
    });
  });
}
