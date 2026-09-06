import 'dart:async';
import 'dart:collection';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/live/live_updates.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/features/chat/chat_thread_controller.dart';
import 'package:shiptrip/features/chat/chat_thread_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

void main() {
  group('Phase 8F-F4 chat pipeline', () {
    test(
      'latest window keeps an immediate pending send through its ACK',
      () async {
        final server = _ChatServer(
          List.generate(80, (index) => _message(index + 1)),
        );
        final post = Completer<FakeResponse>();
        server.postResponses.add((_) => post.future);
        final harness = _Harness(server);
        addTearDown(harness.dispose);

        await harness.controller.initialLoad;

        expect(harness.controller.messages, hasLength(50));
        expect(harness.controller.messages.first.id, 31);
        expect(server.latestReads, 1);
        expect(server.backend.lastTo('GET', _ChatServer.messagesPath)!.query, {
          'page_size': 50,
          'latest': 1,
        });

        final send = harness.controller.send('  acknowledged  ');

        expect(harness.controller.pendingMessages, hasLength(1));
        expect(harness.controller.pendingMessages.single.body, 'acknowledged');
        expect(harness.controller.isSending, isTrue);

        post.complete(FakeResponse(201, _message(81, body: 'acknowledged')));
        expect(await send, isNull);

        expect(harness.controller.pendingMessages, isEmpty);
        expect(harness.controller.messages, hasLength(51));
        expect(harness.controller.messages.last.id, 81);
        expect(server.latestReads, 1, reason: 'an ACK must not reload history');
      },
    );

    test(
      'live reconciliation is ordered, replay-safe, and body-agnostic',
      () async {
        final server = _ChatServer([_message(10)]);
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;

        server.messages.addAll([
          _message(13, body: 'later'),
          _message(12, body: 'same'),
          _message(11, body: 'same'),
          // A replay of an already loaded server identity.
          _message(10),
          // This belongs to another thread and must never enter this timeline.
          _message(99, matchId: 999),
        ]);
        harness.liveCallback!();
        await _eventually(
          () =>
              harness.controller.messages.map((m) => m.id).toList().length == 4,
        );

        expect(harness.controller.messages.map((message) => message.id), [
          10,
          11,
          12,
          13,
        ]);
        expect(
          harness.controller.messages.where(
            (message) => message.body == 'same',
          ),
          hasLength(2),
        );

        harness.liveCallback!();
        await _eventually(() => server.afterReads >= 2);
        expect(harness.controller.messages, hasLength(4));
      },
    );

    test(
      'a real live bus event fetches an inbound message for its match',
      () async {
        final server = _ChatServer([_message(1)]);
        final bus = LiveUpdates(coalesceFor: Duration.zero)..bindAccount(42);
        final harness = _Harness(server, liveUpdates: bus);
        addTearDown(() {
          harness.dispose();
          bus.dispose();
        });
        await harness.controller.initialLoad;

        server.messages.add(_message(2, senderId: 99, body: 'arrived live'));
        bus.ingest({
          'type': 'chat.message.new',
          'event_id': 'chat-message-2',
          'match_id': 7,
        }, source: LiveEventSource.websocket);

        await _eventually(() => harness.controller.messages.length == 2);
        expect(harness.controller.messages.last.body, 'arrived live');
      },
    );

    test(
      'a live event during a delta fetch queues one following pass',
      () async {
        final server = _ChatServer([_message(1)]);
        final afterStarted = Completer<void>();
        final afterGate = Completer<void>();
        server
          ..nextAfterStarted = afterStarted
          ..nextAfterGate = afterGate;
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;

        harness.liveCallback!();
        await afterStarted.future;
        harness.liveCallback!();
        afterGate.complete();

        await _eventually(() => server.afterReads == 2);
        expect(server.afterReads, 2);
      },
    );

    test('history echo completing ahead of POST ACK is merged once', () async {
      final server = _ChatServer([_message(1)]);
      final afterStarted = Completer<void>();
      final afterGate = Completer<void>();
      server
        ..nextAfterStarted = afterStarted
        ..nextAfterGate = afterGate;
      final post = Completer<FakeResponse>();
      server.postResponses.add((_) => post.future);
      final harness = _Harness(server);
      addTearDown(harness.dispose);
      await harness.controller.initialLoad;

      harness.liveCallback!();
      await afterStarted.future;

      final send = harness.controller.send('racing echo');
      server.messages.add(_message(2, body: 'racing echo'));
      afterGate.complete();
      await _eventually(() => server.afterReads == 1);

      expect(harness.controller.pendingMessages, hasLength(1));
      expect(harness.controller.messages.map((message) => message.id), [1]);

      post.complete(FakeResponse(201, _message(2, body: 'racing echo')));
      expect(await send, isNull);

      expect(harness.controller.pendingMessages, isEmpty);
      expect(harness.controller.messages.map((message) => message.id), [1, 2]);
    });

    test('POST ACK does not advance the HTTP reconciliation cursor', () async {
      final server = _ChatServer([_message(50)]);
      final post = Completer<FakeResponse>();
      server.postResponses.add((_) => post.future);
      final harness = _Harness(server);
      addTearDown(harness.dispose);
      await harness.controller.initialLoad;

      final send = harness.controller.send('mine');
      // This inbound commit precedes the outbound ACK but has not been fetched.
      server.messages.add(_message(51, senderId: 99, body: 'inbound'));
      server.messages.add(_message(52, body: 'mine'));
      post.complete(FakeResponse(201, _message(52, body: 'mine')));
      expect(await send, isNull);

      await _eventually(() => harness.controller.messages.length == 3);

      expect(harness.controller.messages.map((message) => message.id), [
        50,
        51,
        52,
      ]);
      expect(server.afterCursors, contains(50));
    });

    test(
      'reconnect walks more than one bounded delta page without gaps',
      () async {
        final server = _ChatServer(
          List.generate(50, (index) => _message(index + 1)),
        );
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;

        server.messages.addAll(
          List.generate(405, (index) => _message(index + 51)),
        );
        harness.liveCallback!();
        await _eventually(() => harness.controller.messages.length == 455);

        expect(harness.controller.messages.first.id, 1);
        expect(harness.controller.messages.last.id, 455);
        expect(server.afterCursors.take(3), [50, 250, 450]);
        expect(
          server.backend
              .to('GET', _ChatServer.messagesPath)
              .where((request) => request.query.containsKey('after_id'))
              .every((request) => request.query['page_size'] == 200),
          isTrue,
        );
      },
    );

    test(
      'reading initial and live history refreshes thread unread state',
      () async {
        final server = _ChatServer([_message(1, senderId: 99)]);
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;
        expect(harness.threadInvalidations, 1);

        server.messages.add(_message(2, senderId: 99));
        harness.liveCallback!();
        await _eventually(() => harness.controller.messages.length == 2);

        expect(harness.threadInvalidations, 2);
      },
    );

    test(
      'reconciliation opens a thread after payment becomes funded',
      () async {
        final server = _ChatServer([_message(1)])
          ..eligible = false
          ..eligibilityReason = 'payment_pending';
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;

        expect(harness.controller.canSend, isFalse);
        expect(harness.controller.messages, isEmpty);
        expect(server.latestReads, 0);

        server
          ..eligible = true
          ..eligibilityReason = 'ok';
        harness.liveCallback!();
        await _eventually(() => harness.controller.messages.length == 1);

        expect(harness.controller.canSend, isTrue);
        expect(server.afterCursors, [0]);
      },
    );

    test('a closed thread keeps history while disabling sending', () async {
      final server = _ChatServer([_message(1)]);
      final harness = _Harness(server);
      addTearDown(harness.dispose);
      await harness.controller.initialLoad;
      expect(harness.controller.canSend, isTrue);

      server
        ..eligible = false
        ..eligibilityReason = 'match_closed'
        ..messages.add(_message(2, senderId: 99));
      harness.liveCallback!();
      await _eventually(() => harness.controller.messages.length == 2);

      expect(harness.controller.canSend, isFalse);
      expect(harness.controller.sendBlock.name, 'matchClosed');
      expect(harness.controller.messages.map((message) => message.id), [1, 2]);
    });

    test(
      'failed pending send retries explicitly and keeps its local identity',
      () async {
        final server = _ChatServer([_message(1)]);
        server.postResponses
          ..add((_) => const FakeResponse(503, {'detail': 'unavailable'}))
          ..add((_) => FakeResponse(201, _message(2, body: 'retry me')));
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;

        final firstError = await harness.controller.send('retry me');
        expect(firstError, isNotNull);
        final failed = harness.controller.pendingMessages.single;
        expect(failed.hasFailed, isTrue);

        final retry = harness.controller.retry(failed);
        expect(
          harness.controller.pendingMessages.single.localId,
          failed.localId,
        );
        expect(harness.controller.pendingMessages.single.hasFailed, isFalse);
        expect(await retry, isNull);

        expect(harness.controller.pendingMessages, isEmpty);
        expect(harness.controller.messages.map((message) => message.id), [
          1,
          2,
        ]);
        expect(
          server.backend.to('POST', _ChatServer.messagesPath),
          hasLength(2),
        );
      },
    );

    test(
      'dispose rejects stale send completion and unregisters live callback',
      () async {
        final server = _ChatServer([_message(1)]);
        final post = Completer<FakeResponse>();
        server.postResponses.add((_) => post.future);
        final harness = _Harness(server);
        await harness.controller.initialLoad;
        final invalidationsBeforeSend = harness.threadInvalidations;

        final send = harness.controller.send('old account');
        expect(harness.controller.pendingMessages, hasLength(1));
        harness.controller.dispose();
        expect(harness.unsubscribed, isTrue);
        expect(harness.controller.pendingMessages, isEmpty);

        post.complete(FakeResponse(201, _message(2, body: 'old account')));
        expect(await send, isNull);
        expect(harness.controller.messages.map((message) => message.id), [1]);
        expect(harness.threadInvalidations, invalidationsBeforeSend);
        harness.container.dispose();
      },
    );

    test(
      'account identity recreates the provider and rejects the old ACK',
      () async {
        final server = _ChatServer([_message(1)]);
        final post = Completer<FakeResponse>();
        server.postResponses.add((_) => post.future);
        final tokens = FakeTokenStore();
        final live = LiveUpdates()..bindAccount(42);
        final container = ProviderContainer(
          overrides: [
            tokenStoreProvider.overrideWithValue(tokens),
            apiClientProvider.overrideWithValue(
              apiClientFor(server.backend, tokens),
            ),
            sessionProvider.overrideWith(_TestSessionController.new),
            liveUpdatesProvider.overrideWithValue(live),
          ],
        );
        final provider = chatThreadControllerProvider(7);
        final subscription = container.listen(
          provider,
          (_, _) {},
          fireImmediately: true,
        );
        addTearDown(() {
          subscription.close();
          container.dispose();
          live.dispose();
        });

        final first = subscription.read();
        await first.initialLoad;
        final oldSend = first.send('belongs to 42');
        expect(first.pendingMessages, hasLength(1));

        (container.read(sessionProvider.notifier) as _TestSessionController)
            .switchAccount(Account.fromJson({...meFixture(), 'id': 99}));
        await _eventually(() => !identical(subscription.read(), first));
        final second = subscription.read();

        expect(second.accountId, 99);
        expect(first.pendingMessages, isEmpty);
        post.complete(FakeResponse(201, _message(2, body: 'belongs to 42')));
        expect(await oldSend, isNull);
        expect(first.messages.map((message) => message.id), [1]);
      },
    );

    test(
      'older cursor appends history in order without replacing latest',
      () async {
        final server = _ChatServer(
          List.generate(100, (index) => _message(index + 1)),
        );
        final harness = _Harness(server);
        addTearDown(harness.dispose);
        await harness.controller.initialLoad;
        expect(harness.controller.messages.first.id, 51);
        expect(harness.controller.hasMoreOlder, isTrue);

        await harness.controller.loadOlder();

        expect(
          harness.controller.messages.map((message) => message.id),
          List.generate(100, (index) => index + 1),
        );
        expect(harness.controller.hasMoreOlder, isFalse);
        expect(server.beforeCursors, [51]);
      },
    );

    testWidgets('loading older rows preserves the reverse-list scroll offset', (
      tester,
    ) async {
      final server = _ChatServer(
        List.generate(100, (index) => _message(index + 1)),
      );
      final beforeStarted = Completer<void>();
      final beforeGate = Completer<void>();
      server
        ..nextBeforeStarted = beforeStarted
        ..nextBeforeGate = beforeGate;
      final container = containerFor(server.backend);
      await pumpApp(
        tester,
        const ChatThreadScreen(matchId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      final list = find.byType(ListView);
      expect(list, findsOneWidget);
      final position = tester
          .state<ScrollableState>(
            find.descendant(of: list, matching: find.byType(Scrollable)),
          )
          .position;
      position.jumpTo(position.maxScrollExtent);
      for (var pump = 0; pump < 10 && !beforeStarted.isCompleted; pump++) {
        await tester.pump(const Duration(milliseconds: 10));
      }
      expect(beforeStarted.isCompleted, isTrue);

      final oldPixels = position.pixels;
      final oldMaximum = position.maxScrollExtent;
      beforeGate.complete();
      await tester.pumpAndSettle();

      expect(position.maxScrollExtent, greaterThan(oldMaximum));
      expect(position.pixels, closeTo(oldPixels, 1));
      expect(position.pixels, lessThan(position.maxScrollExtent));
    });

    testWidgets(
      'open chat shows sends before ACK and inbound without navigation',
      (tester) async {
        final server = _ChatServer([_message(1, senderId: 99, body: 'hello')]);
        final post = Completer<FakeResponse>();
        server.postResponses.add((_) => post.future);
        final container = containerFor(server.backend);
        await pumpApp(
          tester,
          const ChatThreadScreen(matchId: 7),
          container: container,
        );
        await tester.pumpAndSettle();
        final live = container.read(liveUpdatesProvider)..bindAccount(42);
        final l = L.of(tester.element(find.byType(ChatThreadScreen)));

        await tester.enterText(find.byType(TextField), 'immediate outbound');
        await tester.tap(find.byTooltip(l.chatSend));
        await tester.pump();
        expect(post.isCompleted, isFalse);
        expect(find.text('immediate outbound'), findsOneWidget);
        expect(find.text(l.chatSending), findsOneWidget);

        final acknowledged = _message(2, body: 'immediate outbound');
        server.messages.add(acknowledged);
        post.complete(FakeResponse(201, acknowledged));
        await tester.pumpAndSettle();
        live.ingest({
          'type': 'chat.message.new',
          'event_id': 'chat-echo-2',
          'payload': {'match_id': 7, 'message_id': 2},
        }, source: LiveEventSource.websocket);
        await tester.pump(const Duration(milliseconds: 100));
        await tester.pumpAndSettle();
        expect(find.text('immediate outbound'), findsOneWidget);
        expect(find.text(l.chatSending), findsNothing);

        server.messages.add(_message(3, senderId: 99, body: 'live inbound'));
        for (var duplicate = 0; duplicate < 2; duplicate++) {
          live.ingest({
            'type': 'chat.message.new',
            'event_id': 'chat-inbound-3',
            'payload': {'match_id': 7, 'message_id': 3},
          }, source: LiveEventSource.websocket);
        }
        await tester.pump(const Duration(milliseconds: 100));
        await tester.pumpAndSettle();
        expect(find.byType(ChatThreadScreen), findsOneWidget);
        expect(find.text('live inbound'), findsOneWidget);
        expect(find.text('immediate outbound'), findsOneWidget);
      },
    );

    testWidgets(
      'reconnect clears the initial history error on the open screen',
      (tester) async {
        final server = _ChatServer([
          _message(1, senderId: 99, body: 'recovered history'),
        ]);
        final container = containerFor(server.backend);
        server.backend.handle('GET', _ChatServer.messagesPath, (request) {
          if (request.query.containsKey('latest')) {
            return const FakeResponse(503, {
              'detail': 'Temporarily unavailable',
            });
          }
          return server._getMessages(request);
        });
        await pumpApp(
          tester,
          const ChatThreadScreen(matchId: 7),
          container: container,
        );
        await tester.pumpAndSettle();
        expect(find.text('recovered history'), findsNothing);
        final live = container.read(liveUpdatesProvider)..bindAccount(42);
        live.reconcileScope(liveResourcesForLocation('/chat/thread/7'));
        await tester.pump(const Duration(milliseconds: 100));
        await tester.pumpAndSettle();
        expect(find.text('recovered history'), findsOneWidget);
      },
    );
  });
}

class _Harness {
  _Harness(_ChatServer server, {LiveUpdates? liveUpdates})
    : container = containerFor(server.backend) {
    controller = ChatThreadController(
      matchId: 7,
      accountId: 42,
      repository: container.read(chatRepositoryProvider),
      registerLive: (callback) {
        liveCallback = callback;
        final unregister = liveUpdates?.register(
          const LiveResource.chat(7),
          callback,
        );
        return () {
          unregister?.call();
          unsubscribed = true;
        };
      },
      invalidateThreads: () => threadInvalidations++,
    );
  }

  final ProviderContainer container;
  late final ChatThreadController controller;
  VoidCallback? liveCallback;
  int threadInvalidations = 0;
  bool unsubscribed = false;

  void dispose() {
    controller.dispose();
    container.dispose();
  }
}

class _ChatServer {
  _ChatServer(this.messages) {
    backend
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..on(
        'GET',
        '/api/chat/threads',
        const FakeResponse(200, [
          {
            'match_id': 7,
            'deal_id': 3,
            'counterparty_id': 99,
            'counterparty_name': 'Karim',
            'route': 'Paris - Algiers',
            'status': 'accepted',
            'can_send': true,
            'unread_count': 0,
          },
        ]),
      );
    backend.handle('GET', eligibilityPath, (_) {
      eligibilityReads++;
      return FakeResponse(200, {
        'eligible': eligible,
        'reason': eligibilityReason,
        'match_id': 7,
      });
    });
    backend.handle('GET', messagesPath, _getMessages);
    backend.handle('POST', messagesPath, _postMessage);
  }

  static const eligibilityPath = '/api/matches/7/chat-eligibility';
  static const messagesPath = '/api/matches/7/chat/messages';

  final FakeBackend backend = FakeBackend();
  final List<Map<String, dynamic>> messages;
  final Queue<FutureOr<FakeResponse> Function(RecordedRequest request)>
  postResponses = Queue();
  final List<int> afterCursors = [];
  final List<int> beforeCursors = [];
  int latestReads = 0;
  int afterReads = 0;
  int eligibilityReads = 0;
  bool eligible = true;
  String eligibilityReason = 'ok';
  Completer<void>? nextAfterStarted;
  Completer<void>? nextAfterGate;
  Completer<void>? nextBeforeStarted;
  Completer<void>? nextBeforeGate;

  Future<FakeResponse> _getMessages(RecordedRequest request) async {
    final sorted =
        messages
            .where((message) => message['match_id'] == 7)
            .toList(growable: false)
          ..sort((a, b) => (a['id'] as int).compareTo(b['id'] as int));
    final pageSize = _asInt(request.query['page_size']) ?? 50;
    late final List<Map<String, dynamic>> available;
    late final List<Map<String, dynamic>> page;
    late final bool hasMore;

    if (request.query['latest'] == 1) {
      latestReads++;
      available = sorted;
      final start = (available.length - pageSize).clamp(0, available.length);
      page = available.sublist(start);
      hasMore = start > 0;
    } else if (request.query['after_id'] case final Object raw) {
      final cursor = _asInt(raw)!;
      afterReads++;
      afterCursors.add(cursor);
      nextAfterStarted?.complete();
      nextAfterStarted = null;
      final gate = nextAfterGate;
      nextAfterGate = null;
      if (gate != null) await gate.future;
      final refreshed =
          messages
              .where(
                (message) =>
                    message['match_id'] == 7 && (message['id'] as int) > cursor,
              )
              .toList(growable: false)
            ..sort((a, b) => (a['id'] as int).compareTo(b['id'] as int));
      available = refreshed;
      page = available.take(pageSize).toList(growable: false);
      hasMore = available.length > page.length;
    } else if (request.query['before_id'] case final Object raw) {
      final cursor = _asInt(raw)!;
      beforeCursors.add(cursor);
      nextBeforeStarted?.complete();
      nextBeforeStarted = null;
      final gate = nextBeforeGate;
      nextBeforeGate = null;
      if (gate != null) await gate.future;
      available = sorted
          .where((message) => (message['id'] as int) < cursor)
          .toList(growable: false);
      final start = (available.length - pageSize).clamp(0, available.length);
      page = available.sublist(start);
      hasMore = start > 0;
    } else {
      available = sorted;
      page = available.take(pageSize).toList(growable: false);
      hasMore = available.length > page.length;
    }

    return FakeResponse(200, {
      'count': page.length,
      'results': page,
      'has_more': hasMore,
      'next': null,
      'oldest_id': page.isEmpty ? null : page.first['id'],
      'latest_id': page.isEmpty ? null : page.last['id'],
    });
  }

  FutureOr<FakeResponse> _postMessage(RecordedRequest request) {
    if (postResponses.isNotEmpty) return postResponses.removeFirst()(request);
    final id = messages.isEmpty
        ? 1
        : messages
                  .map((message) => message['id'] as int)
                  .reduce((a, b) => a > b ? a : b) +
              1;
    final message = _message(id, body: request.body['body'] as String);
    messages.add(message);
    return FakeResponse(201, message);
  }
}

Map<String, dynamic> _message(
  int id, {
  int matchId = 7,
  int senderId = 42,
  String? body,
}) => {
  'id': id,
  'match_id': matchId,
  'sender_id': senderId,
  'body': body ?? 'message $id',
  'created_at': '2026-09-06T12:00:00Z',
  'read_at': null,
};

int? _asInt(Object? value) => switch (value) {
  final int value => value,
  final num value => value.toInt(),
  final String value => int.tryParse(value),
  _ => null,
};

Future<void> _eventually(bool Function() condition) async {
  for (var attempt = 0; attempt < 200; attempt++) {
    if (condition()) return;
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  fail('condition did not become true');
}

class _TestSessionController extends SessionController {
  @override
  SessionState build() => SessionSignedIn(Account.fromJson(meFixture()));

  void switchAccount(Account account) {
    state = SessionSignedIn(account);
  }
}
