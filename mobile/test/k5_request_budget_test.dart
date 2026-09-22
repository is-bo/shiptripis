/// K5: how many HTTP requests the real app makes, surface by surface.
///
/// Everything above the Dio adapter is production code — the router, the
/// shell, every provider, the session restore — so the counts here are the
/// counts a phone would send. The fake emulates the server's real pagination
/// (`/api/deals` pages at 20 rows) so a client that silently stops at page 1
/// shows up as missing rows, not as a pass.
///
/// Before K5 a cold start to Home cost 26 requests, 19 of them one
/// `/api/deals/{id}` per Deal just to learn which ones needed the user.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/features/common/delivery_card.dart';

import 'support/fake_api.dart';

/// Cold start to a settled Home. Measured at 6 after K5; the headroom is for
/// one legitimate new Home read, not for a per-row fan-out.
const _coldStartBudget = 8;

/// A resume after a real absence. Measured at 5 after K5.
const _resumeBudget = 6;

/// Sign-out asks the keystore for the installation id; a widget test has no
/// keystore to answer, so this one does.
class _TokenStore extends FakeTokenStore {
  @override
  Future<String> readOrCreateInstallationId() async => 'installation';
}

class _IdleConnection implements NotificationSocketConnection {
  final _controller = StreamController<dynamic>();
  @override
  Stream<dynamic> get stream => _controller.stream;
  @override
  Future<void> close() async {
    if (!_controller.isClosed) await _controller.close();
  }
}

Map<String, dynamic> _deal(
  int id, {
  required int senderId,
  required String status,
  required String activity,
  String? deliveryConfirmedAt,
  bool canSubmitDeliveryCode = false,
}) => {
  'id': id,
  'match_id': 1000 + id,
  'delivery_request_id': 2000 + id,
  'sender_id': senderId,
  'traveler_id': 99,
  'status': status,
  'activity_state': activity,
  'is_legacy': false,
  'leg_allocations': <Object>[],
  'delivery_confirmed_at': deliveryConfirmedAt,
  'created_at': '2026-08-${(id % 28 + 1).toString().padLeft(2, '0')}T10:00:00Z',
  'attention': {
    'can_reveal_pickup_code': false,
    'can_submit_pickup_code': false,
    'can_reveal_delivery_code': false,
    'can_submit_delivery_code': canSubmitDeliveryCode,
    'can_rate': false,
  },
};

/// Account A (42): 3 active Deals and 22 finished ones — more than one
/// 20-row history page. Deal 98's row says a delivery code is waiting.
List<Map<String, dynamic>> _dealsOfA() => [
  _deal(100, senderId: 42, status: 'payment_required', activity: 'active'),
  _deal(99, senderId: 42, status: 'pickup_ready', activity: 'active'),
  _deal(
    98,
    senderId: 42,
    status: 'in_transit',
    activity: 'active',
    canSubmitDeliveryCode: true,
  ),
  for (var id = 97; id >= 76; id--)
    _deal(
      id,
      senderId: 42,
      status: 'completed',
      activity: 'completed',
      deliveryConfirmedAt: '2026-08-01T10:00:00Z',
    ),
];

/// Account B (77): one live Deal and two finished ones, none shared with A.
List<Map<String, dynamic>> _dealsOfB() => [
  _deal(502, senderId: 77, status: 'in_transit', activity: 'active'),
  for (final id in [501, 500])
    _deal(
      id,
      senderId: 77,
      status: 'completed',
      activity: 'completed',
      deliveryConfirmedAt: '2026-08-01T10:00:00Z',
    ),
];

final _idsOfA = {for (final d in _dealsOfA()) d['id'] as int};
final _idsOfB = {for (final d in _dealsOfB()) d['id'] as int};

/// A server that knows which account is signed in, and pages like Django.
class _Server {
  int accountId = 42;

  final backend = FakeBackend();

  _Server() {
    backend
      ..fallback = _answer
      ..handle('POST', '/api/auth/sign-in', (_) {
        accountId = 77;
        return FakeResponse(200, {
          'access': 'b-access',
          'refresh': 'b-refresh',
          'user': _me(),
        });
      });
  }

  Map<String, dynamic> _me() => accountId == 42
      ? meFixture()
      : {...meFixture(), 'id': 77, 'email': 'b@example.com'};

  FakeResponse _answer(RecordedRequest r) {
    if (r.path == '/api/me') return FakeResponse(200, _me());
    if (r.path == '/api/deals') {
      var rows = accountId == 42 ? _dealsOfA() : _dealsOfB();
      final scope = r.query['scope'];
      if (scope == 'current') {
        rows = rows.where((d) => d['activity_state'] == 'active').toList();
      } else if (scope == 'history') {
        rows = rows.where((d) => d['activity_state'] != 'active').toList();
      }
      final status = r.query['status'];
      if (status != null) {
        rows = rows.where((d) => d['status'] == status).toList();
      }
      final page = int.tryParse('${r.query['page'] ?? 1}') ?? 1;
      final size = int.tryParse('${r.query['page_size'] ?? 20}') ?? 20;
      final slice = rows.skip((page - 1) * size).take(size).toList();
      return FakeResponse(200, {
        'count': rows.length,
        'next': page * size < rows.length ? 'next' : null,
        'previous': null,
        'results': slice,
      });
    }
    if (_isDealDetail(r)) {
      // Answered so a regression shows up as a failed count, not a crash.
      final id = int.parse(r.path.split('/').last);
      return FakeResponse(
        200,
        [..._dealsOfA(), ..._dealsOfB()].firstWhere((d) => d['id'] == id),
      );
    }
    if (r.path.contains('count')) {
      return const FakeResponse(200, {'count': 0});
    }
    return const FakeResponse(200, <Object>[]);
  }

  List<RecordedRequest> since(int from) =>
      backend.requests.skip(from).toList(growable: false);
}

bool _isDealDetail(RecordedRequest r) =>
    RegExp(r'^/api/deals/\d+$').hasMatch(r.path);

List<RecordedRequest> _dealLists(Iterable<RecordedRequest> requests) =>
    requests.where((r) => r.path == '/api/deals').toList(growable: false);

List<RecordedRequest> _history(Iterable<RecordedRequest> requests) =>
    _dealLists(requests).where((r) => r.query['scope'] == 'history').toList();

Future<void> _settle(WidgetTester tester, [int frames = 30]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Boots the real app over [server] and waits for Home to settle.
Future<ProviderContainer> _boot(WidgetTester tester, _Server server) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = const Size(412, 915);
  addTearDown(tester.view.reset);

  final store = _TokenStore();
  final socket = NotificationSocket(
    connector: (_, _) async => _IdleConnection(),
  );
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(store),
        apiClientProvider.overrideWithValue(
          apiClientFor(server.backend, store),
        ),
        notificationSocketProvider.overrideWithValue(socket),
      ],
      child: const ShipTripApp(),
    ),
  );
  await _settle(tester);
  return ProviderScope.containerOf(tester.element(find.byType(ShipTripApp)));
}

/// Awaits [work] while fake time runs; awaiting it bare would wait on timers
/// the test clock never fires.
Future<void> _drive(WidgetTester tester, Future<void> work) async {
  await _settle(tester);
  await work;
}

/// Unmounts the app so the push coordinator and sockets stop before the
/// test's pending-timer check.
Future<void> _shutdown(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await _settle(tester, 5);
}

Future<void> _openTab(WidgetTester tester, IconData icon) async {
  await tester.tap(find.byIcon(icon).first);
  await _settle(tester);
}

Future<void> _openHistoryFilter(WidgetTester tester) async {
  final choice = find.byWidgetPredicate(
    (w) => w.runtimeType.toString().startsWith('AppSegmentedChoice'),
  );
  expect(choice, findsOneWidget);
  await tester.tap(find.descendant(of: choice, matching: find.text('History')));
  await _settle(tester);
}

Finder _cardFor(int dealId) => find.byWidgetPredicate(
  (w) => w is DeliveryCard && w.deal.id == dealId,
  description: 'DeliveryCard for Deal $dealId',
);

/// Every Deal card in the tree, including tabs the shell keeps offstage.
Set<int> _renderedDealIds(WidgetTester tester) => {
  for (final card in tester.widgetList<DeliveryCard>(
    find.byType(DeliveryCard, skipOffstage: false),
  ))
    card.deal.id,
};

Set<int> _ids(AsyncValue<List<Deal>> value) => {
  for (final deal in value.value ?? const <Deal>[]) deal.id,
};

void main() {
  testWidgets('cold start to Home stays inside its request budget', (
    tester,
  ) async {
    final server = _Server();
    final container = await _boot(tester, server);
    final cold = server.since(0);

    expect(
      cold.where(_isDealDetail),
      isEmpty,
      reason: 'Home must not fetch one Deal detail per row',
    );
    expect(
      cold.length,
      lessThanOrEqualTo(_coldStartBudget),
      reason: 'cold start sent ${cold.map((r) => r.path).toList()}',
    );
    final lists = _dealLists(cold);
    expect(lists, hasLength(1), reason: 'one current-Deal read, one page');
    expect(lists.single.query['scope'], 'current');
    expect(_history(cold), isEmpty);
    expect(cold.where((r) => r.path == '/api/me'), hasLength(1));

    // "Needs you" comes from the list row's `attention` flags alone.
    final attention = container.read(attentionProvider);
    expect(
      attention.where(
        (item) =>
            item.dealId == 98 &&
            item.reason == AttentionReason.submitDeliveryCode,
      ),
      hasLength(1),
    );
    expect(find.text('Enter the delivery code'), findsOneWidget);

    await _shutdown(tester);
  });

  testWidgets('history is read only when opened, then a page per scroll', (
    tester,
  ) async {
    final server = _Server();
    final container = await _boot(tester, server);

    final beforeDeliveries = server.backend.requests.length;
    await _openTab(tester, Icons.inventory_2_outlined);
    expect(
      _history(server.since(0)),
      isEmpty,
      reason: 'Deliveries opens on Active; history is not read yet',
    );
    expect(server.since(beforeDeliveries).where(_isDealDetail), isEmpty);

    await _openHistoryFilter(tester);
    var history = _history(server.since(0));
    expect(history, hasLength(1), reason: 'the first page only');
    expect(history.single.query['page'], isNull);
    expect(history.single.query['page_size'], 20);
    expect(_ids(container.read(historyDealsProvider)), hasLength(20));
    expect(_cardFor(76), findsNothing);

    // Scroll to the end of the first page; the second is asked for then.
    final scrollable = find
        .descendant(
          of: find.byType(CustomScrollView),
          matching: find.byType(Scrollable),
        )
        .first;
    for (var i = 0; i < 40 && _cardFor(76).evaluate().isEmpty; i++) {
      await tester.drag(scrollable, const Offset(0, -400));
      await _settle(tester, 3);
    }

    expect(_cardFor(76), findsOneWidget, reason: 'a row from page 2');
    history = _history(server.since(0));
    expect(history.map((r) => r.query['page']).toList(), [null, 2]);
    expect(_ids(container.read(historyDealsProvider)), hasLength(22));
    expect(server.since(0).where(_isDealDetail), isEmpty);

    await _shutdown(tester);
  });

  testWidgets('resume reads the profile once; push state rebuilds nothing', (
    tester,
  ) async {
    final server = _Server();
    final container = await _boot(tester, server);

    // The push coordinator's state really moves here — the assertion below
    // would be empty if it did not.
    var pushChanges = 0;
    final pushListener = container.listen(
      pushCoordinatorProvider,
      (_, _) => pushChanges++,
    );
    addTearDown(pushListener.close);
    final appBefore = tester.widget(find.byType(MaterialApp));
    await container.read(pushCoordinatorProvider.notifier).refreshPermission();
    await tester.pump();
    expect(pushChanges, greaterThan(0));
    expect(
      identical(appBefore, tester.widget(find.byType(MaterialApp))),
      isTrue,
      reason: 'a push permission refresh must not rebuild MaterialApp',
    );

    final beforeResume = server.backend.requests.length;
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    // ResumeRefresher ignores an absence under a second, on the wall clock.
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(milliseconds: 1100)),
    );
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await _settle(tester);

    final resume = server.since(beforeResume);
    expect(resume.where((r) => r.path == '/api/me'), hasLength(1));
    expect(resume.where(_isDealDetail), isEmpty);
    expect(
      resume.length,
      lessThanOrEqualTo(_resumeBudget),
      reason: 'resume sent ${resume.map((r) => r.path).toList()}',
    );

    await _shutdown(tester);
  });

  testWidgets('a different account sees none of the first one\'s Deals', (
    tester,
  ) async {
    final server = _Server();
    final container = await _boot(tester, server);

    await _openTab(tester, Icons.inventory_2_outlined);
    await _openHistoryFilter(tester);
    expect(_ids(container.read(currentDealsProvider)), isNotEmpty);
    expect(_ids(container.read(historyDealsProvider)), hasLength(20));

    final session = container.read(sessionProvider.notifier);
    // `signOut` ends by invalidating `roleContextProvider`, which depends on
    // the session, and debug-mode Riverpod rejects that as a circular
    // dependency *after* the session, tokens and snapshot are already gone.
    // A pre-existing defect outside K5, reported separately; tolerated here
    // so this test keeps asserting what it is about.
    await _drive(
      tester,
      session.signOut().catchError(
        (_) {},
        test: (e) => e.runtimeType.toString() == 'CircularDependencyError',
      ),
    );
    await _drive(
      tester,
      session.signIn(email: 'b@example.com', password: 'secret'),
    );
    expect(container.read(accountProvider)?.id, 77);

    // Home, then Deliveries on both of its Deal sources.
    expect(_renderedDealIds(tester).intersection(_idsOfA), isEmpty);
    expect(
      container.read(attentionProvider).map((item) => item.dealId),
      everyElement(isNot(isIn(_idsOfA))),
    );
    await _openTab(tester, Icons.inventory_2_outlined);
    expect(_ids(container.read(currentDealsProvider)), {502});
    expect(_renderedDealIds(tester), contains(502));
    expect(_renderedDealIds(tester).intersection(_idsOfA), isEmpty);

    await _openHistoryFilter(tester);
    expect(_ids(container.read(historyDealsProvider)), {500, 501});
    expect(_renderedDealIds(tester), containsAll(<int>[500, 501]));
    expect(_renderedDealIds(tester).intersection(_idsOfA), isEmpty);
    expect(_idsOfB.intersection(_idsOfA), isEmpty);

    await _shutdown(tester);
  });
}
