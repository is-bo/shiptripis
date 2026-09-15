/// Phase 8F-F4: typed live invalidation stays scoped and HTTP-authoritative.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/push/push_messaging.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/deal.dart';

import 'support/fake_api.dart';

void main() {
  group('event resource map', () {
    test('covers every server event family with its typed resources', () {
      final cases = <(String, Map<String, dynamic>, LiveResource)>[
        ('parcel.created', {'parcel_id': 1}, const LiveResource.request(1)),
        ('match.created', {'match_id': 2}, const LiveResource.match(2)),
        ('offer.updated', {'match_id': 2}, const LiveResource.offers(2)),
        ('deal.updated', {'deal_id': 3}, const LiveResource.deal(3)),
        ('payment.captured', {'deal_id': 3}, const LiveResource.payment(3)),
        ('handover.confirmed', {'deal_id': 3}, const LiveResource.deal(3)),
        ('dispute.opened', {'dispute_id': 4}, const LiveResource.dispute(4)),
        ('payout.status_changed', {'deal_id': 3}, const LiveResource.payouts()),
        ('trip.updated', {'journey_id': 5}, const LiveResource.journey(5)),
        (
          'flight_proof.status_changed',
          {'trip_id': 5},
          const LiveResource.journey(5),
        ),
        ('chat.message.new', {'match_id': 2}, const LiveResource.chat(2)),
        ('kyc.status_changed', const {}, const LiveResource.account()),
      ];

      for (final (type, data, expected) in cases) {
        final resources = resourcesForLiveEvent(type, data);
        expect(resources, contains(expected), reason: type);
        expect(resources, contains(const LiveResource.unread()), reason: type);
      }
    });

    test('route scope names only its current detail', () {
      expect(liveResourcesForLocation('/deals/7/payment'), {
        const LiveResource.deal(7),
        const LiveResource.payment(7),
      });
      expect(liveResourcesForLocation('/chat/thread/9'), {
        const LiveResource.threads(),
        const LiveResource.chat(9),
      });
      expect(liveResourcesForLocation('/deals/not-an-id'), isEmpty);
    });

    test(
      'protocol frames and malformed identities cannot fan out detail reads',
      () {
        expect(resourcesForLiveEvent('ping', {'deal_id': 7}), isEmpty);
        expect(
          resourcesForLiveEvent('chat.message_created', {'match_id': 7}),
          isEmpty,
        );
        for (final invalid in [
          -1,
          7.5,
          double.nan,
          double.infinity,
          'not-an-id',
        ]) {
          final resources = resourcesForLiveEvent('deal.updated', {
            'deal_id': invalid,
          });
          expect(
            resources.where(
              (resource) => resource.kind == LiveResourceKind.deal,
            ),
            isEmpty,
          );
        }
      },
    );
  });

  test('bursts coalesce and do not churn unrelated resources', () async {
    final live = LiveUpdates(coalesceFor: const Duration(milliseconds: 5));
    live.bindAccount(42);
    var dealCalls = 0;
    var otherDealCalls = 0;
    var threadCalls = 0;
    live.register(const LiveResource.deal(7), () => dealCalls++);
    live.register(const LiveResource.deal(8), () => otherDealCalls++);
    live.register(const LiveResource.threads(), () => threadCalls++);

    for (var index = 0; index < 8; index++) {
      live.ingest({
        'event_id': 'deal-$index',
        'type': 'deal.updated',
        'payload': {'deal_id': 7},
      }, source: LiveEventSource.websocket);
    }
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(dealCalls, 1);
    expect(otherDealCalls, 0);
    expect(threadCalls, 1);
    live.dispose();
  });

  test('duplicate FCM and WS copies still deliver a richer chat key', () async {
    final live = LiveUpdates(coalesceFor: const Duration(milliseconds: 5));
    live.bindAccount(42);
    var threads = 0;
    var chat = 0;
    live.register(const LiveResource.threads(), () => threads++);
    live.register(const LiveResource.chat(19), () => chat++);

    live.ingest({
      'event_id': 'same-event',
      'channel': 'chat.message.new',
    }, source: LiveEventSource.firebase);
    live.ingest({
      'event_id': 'same-event',
      'type': 'chat.message.new',
      'payload': {'match_id': 19},
    }, source: LiveEventSource.websocket);
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(threads, 1);
    expect(chat, 1);
    live.dispose();
  });

  test('account reset drops queued callbacks and dedup identity', () async {
    final live = LiveUpdates(coalesceFor: const Duration(milliseconds: 5));
    var calls = 0;
    live
      ..bindAccount(42)
      ..register(const LiveResource.deal(7), () => calls++)
      ..ingest({
        'event_id': 'shared-id',
        'type': 'deal.updated',
        'deal_id': 7,
      }, source: LiveEventSource.websocket)
      ..bindAccount(null);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(calls, 0);

    live
      ..bindAccount(99)
      ..ingest({
        'event_id': 'shared-id',
        'type': 'deal.updated',
        'deal_id': 7,
      }, source: LiveEventSource.websocket);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(calls, 1);
    live.dispose();
  });

  test('event invalidation performs another real provider HTTP read', () async {
    var reads = 0;
    final backend = FakeBackend()
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle('GET', '/api/deals', (_) {
        reads++;
        return FakeResponse(200, [dealFixture()]);
      });
    final container = containerFor(backend);
    addTearDown(container.dispose);
    final subscription = container.listen(
      dealsProvider,
      (_, _) {},
      fireImmediately: true,
    );
    addTearDown(subscription.close);

    await _waitFor(() => container.read(dealsProvider).hasValue);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    final beforeEvent = reads;
    final live = container.read(liveUpdatesProvider)..bindAccount(42);
    live.ingest({
      'event_id': 'deal-http-refresh',
      'type': 'deal.updated',
      'payload': {'deal_id': 7},
    }, source: LiveEventSource.websocket);
    await Future<void>.delayed(const Duration(milliseconds: 100));
    await _waitFor(() => reads == beforeEvent + 1);

    expect(reads, beforeEvent + 1);
  });

  testWidgets(
    'account switch exposes no previous deal while the new read fails',
    (tester) async {
      final secondRead = Completer<FakeResponse>();
      var reads = 0;
      final backend = FakeBackend()
        ..handle('GET', '/api/deals/7', (_) {
          reads++;
          return reads == 1
              ? FakeResponse(200, dealFixture())
              : secondRead.future;
        });
      final tokens = FakeTokenStore();
      final api = apiClientFor(backend, tokens);
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          tokenStoreProvider.overrideWithValue(tokens),
          apiClientProvider.overrideWithValue(api),
          sessionProvider.overrideWith(
            () => _SwitchingSession(Account.fromJson(meFixture())),
          ),
        ],
      );
      addTearDown(() {
        container.dispose();
        api.raw.close(force: true);
      });

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp(
            home: Consumer(
              builder: (context, ref, _) => AsyncView<Deal>(
                value: ref.watch(dealDetailProvider(7)),
                data: (deal) => Text('private deal ${deal.id}'),
                loading: () => const Text('loading new account'),
                error: (_) => const Text('new account forbidden'),
              ),
            ),
          ),
        ),
      );
      await _pumpUntil(
        tester,
        () => find.text('private deal 7').evaluate().isNotEmpty,
      );

      (container.read(sessionProvider.notifier) as _SwitchingSession).switchTo(
        Account.fromJson({
          ...meFixture(),
          'id': 99,
          'email': 'next@example.com',
        }),
      );
      await tester.pump();

      expect(container.read(dealDetailProvider(7)).value, isNull);
      expect(find.text('private deal 7'), findsNothing);
      expect(find.text('loading new account'), findsOneWidget);

      secondRead.complete(const FakeResponse(403, {'detail': 'forbidden'}));
      await tester.pumpAndSettle();

      final failed = container.read(dealDetailProvider(7));
      expect(failed.hasError, isTrue);
      expect(failed.value, isNull);
      expect(find.text('private deal 7'), findsNothing);
      expect(find.text('new account forbidden'), findsOneWidget);
    },
  );

  test(
    'resume/reconnect scope includes mounted collections but no details',
    () async {
      final live = LiveUpdates(coalesceFor: const Duration(milliseconds: 5));
      live.bindAccount(42);
      var routeDeal = 0;
      var hiddenDeal = 0;
      var deals = 0;
      var unread = 0;
      live.register(const LiveResource.deal(7), () => routeDeal++);
      live.register(const LiveResource.deal(8), () => hiddenDeal++);
      live.register(const LiveResource.deals(), () => deals++);
      live.register(const LiveResource.unread(), () => unread++);

      live.reconcileScope(liveResourcesForLocation('/deals/7'));
      await Future<void>.delayed(const Duration(milliseconds: 20));

      expect(routeDeal, 1);
      expect(hiddenDeal, 0);
      expect(deals, 1);
      expect(unread, 1);
      live.dispose();
    },
  );

  testWidgets(
    'mounted coordinator reconciles the actual route on resume and reconnect',
    (tester) async {
      final router = GoRouter(
        initialLocation: '/deals/7',
        routes: [
          GoRoute(
            path: '/deals/:id',
            builder: (_, _) => const Scaffold(body: Text('deal route')),
          ),
        ],
      );
      final socket = _CoordinatorSocket();
      final container = ProviderContainer(
        overrides: [
          sessionProvider.overrideWith(
            () => _FixedSession(Account.fromJson(meFixture())),
          ),
          routerProvider.overrideWithValue(router),
          notificationSocketProvider.overrideWithValue(socket),
          pushMessagingProvider.overrideWithValue(
            const DisabledPushMessaging(),
          ),
        ],
      );
      addTearDown(() {
        container.dispose();
        router.dispose();
      });

      final live = container.read(liveUpdatesProvider);
      var currentDeal = 0;
      var hiddenDeal = 0;
      var mountedCollection = 0;
      live.register(const LiveResource.deal(7), () => currentDeal++);
      live.register(const LiveResource.deal(8), () => hiddenDeal++);
      live.register(const LiveResource.deals(), () => mountedCollection++);

      await tester.pumpWidget(
        UncontrolledProviderScope(
          container: container,
          child: MaterialApp.router(
            routerConfig: router,
            builder: (context, child) => Consumer(
              builder: (context, ref, _) {
                ref.watch(pushCoordinatorProvider);
                return child ?? const SizedBox.shrink();
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('deal route'), findsOneWidget);
      expect(socket.starts, 1);

      TestWidgetsFlutterBinding.instance.handleAppLifecycleStateChanged(
        AppLifecycleState.paused,
      );
      await tester.pump();
      TestWidgetsFlutterBinding.instance.handleAppLifecycleStateChanged(
        AppLifecycleState.resumed,
      );
      await tester.pump(const Duration(milliseconds: 100));
      expect(currentDeal, 1);
      expect(mountedCollection, 1);
      expect(hiddenDeal, 0);
      expect(socket.starts, 2);
      expect(socket.stops, greaterThanOrEqualTo(2));

      // The second socket connecting asks for the *same* catch-up the resume
      // already performed. Inside the settle window that is not a second round
      // trip: the app used to refetch every mounted collection once per
      // reconnect, which is why one foreground produced three identical bursts
      // of `/api/deals`, `/api/matches`, `/api/parcels` and the bell.
      socket.connected('/ws/notifications');
      await tester.pump(const Duration(milliseconds: 100));
      expect(currentDeal, 1);
      expect(mountedCollection, 1);
      expect(hiddenDeal, 0);
    },
  );
}

class _FixedSession extends SessionController {
  _FixedSession(this.account);

  final Account account;

  @override
  SessionState build() => SessionSignedIn(account);
}

class _SwitchingSession extends SessionController {
  _SwitchingSession(this.account);

  Account account;

  @override
  SessionState build() => SessionSignedIn(account);

  void switchTo(Account next) {
    account = next;
    state = SessionSignedIn(next);
  }
}

Future<void> _waitFor(bool Function() condition) async {
  for (var attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  throw TimeoutException('Condition was not reached.');
}

Future<void> _pumpUntil(WidgetTester tester, bool Function() condition) async {
  for (var attempt = 0; attempt < 100; attempt++) {
    if (condition()) return;
    await tester.pump(const Duration(milliseconds: 5));
  }
  throw TimeoutException('Widget condition was not reached.');
}

class _CoordinatorSocket extends NotificationSocket {
  NotificationSocketConnected? _onConnected;
  int starts = 0;
  int stops = 0;

  @override
  Future<void> start({
    required NotificationSocketToken accessToken,
    required NotificationSocketEvent onEvent,
    required NotificationSocketConnected onConnected,
  }) async {
    starts++;
    _onConnected = onConnected;
  }

  @override
  Future<void> stop() async {
    stops++;
  }

  void connected(String path) => _onConnected?.call(path);
}
