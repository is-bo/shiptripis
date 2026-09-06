/// Phase 8A regression coverage for mobile loading, empty, payment-gated,
/// offline and ready states.
library;

import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_state.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/features/chat/chat_list_screen.dart';
import 'package:shiptrip/features/chat/chat_thread_screen.dart';
import 'package:shiptrip/features/notifications/notifications_screen.dart';
import 'package:shiptrip/features/profile/payouts_screen.dart';
import 'package:shiptrip/features/profile/ratings_screen.dart';
import 'package:shiptrip/domain/chat.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

ProviderContainer _chatContainer(Future<List<ChatThread>> Function() load) {
  final source = FutureProvider.autoDispose<List<ChatThread>>((ref) => load());
  return ProviderContainer(
    retry: (_, _) => null,
    overrides: [
      chatThreadsProvider.overrideWith((ref) => ref.watch(source)),
      unreadNotificationsProvider.overrideWith((ref) => const AsyncData(0)),
    ],
  );
}

void main() {
  group('Chat states', () {
    testWidgets('loading is intentional', (tester) async {
      final waiting = Completer<List<ChatThread>>();
      final container = _chatContainer(() => waiting.future);
      addTearDown(() {
        if (!waiting.isCompleted) waiting.complete(<ChatThread>[]);
      });

      await pumpApp(tester, const ChatListScreen(), container: container);

      expect(find.byType(ChatListScreen), findsOneWidget);
      expect(find.text('No conversations'), findsNothing);
      expect(find.text('Something unexpected happened'), findsNothing);
    });

    testWidgets('empty inbox explains when chat opens', (tester) async {
      final container = _chatContainer(() async => <ChatThread>[]);
      await pumpApp(tester, const ChatListScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.text('No conversations'), findsOneWidget);
      expect(
        find.text('Chat opens once a delivery is paid for.'),
        findsOneWidget,
      );
    });

    testWidgets('offline failure is readable and retryable', (tester) async {
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          chatThreadsProvider.overrideWith(
            (ref) => AsyncError(
              ApiException(
                kind: ApiFailureKind.offline,
                code: ApiErrorCode.unknown,
              ),
              StackTrace.current,
            ),
          ),
          unreadNotificationsProvider.overrideWith((ref) => const AsyncData(0)),
        ],
      );
      await pumpApp(tester, const ChatListScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.text("You're offline"), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
      expect(find.textContaining('DioException'), findsNothing);
    });

    testWidgets('structured backend failure becomes user-facing copy', (
      tester,
    ) async {
      final container = ProviderContainer(
        retry: (_, _) => null,
        overrides: [
          chatThreadsProvider.overrideWith(
            (ref) => AsyncError(
              ApiException(
                kind: ApiFailureKind.conflict,
                code: ApiErrorCode.capacityExceeded,
                statusCode: 409,
                serverDetail: 'capacity_exceeded: internal reservation detail',
              ),
              StackTrace.current,
            ),
          ),
          unreadNotificationsProvider.overrideWith((ref) => const AsyncData(0)),
        ],
      );
      await pumpApp(tester, const ChatListScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.text('This has changed'), findsOneWidget);
      expect(
        find.text("There isn't enough space left on this journey."),
        findsOneWidget,
      );
      expect(find.textContaining('capacity_exceeded'), findsNothing);
      expect(find.textContaining('409'), findsNothing);
    });

    testWidgets('payment_pending is a payment state, not a raw error', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/chat/threads',
          const FakeResponse(200, {'results': <Object>[]}),
        )
        ..on(
          'GET',
          '/api/matches/55/chat-eligibility',
          const FakeResponse(200, {
            'eligible': false,
            'reason': 'payment_pending',
            'match_id': 55,
          }),
        );
      final container = containerFor(backend);

      await pumpApp(
        tester,
        const ChatThreadScreen(matchId: 55, dealId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text("Chat isn't available yet"), findsOneWidget);
      expect(find.text('Go to payment'), findsOneWidget);
      expect(find.textContaining('payment_pending'), findsNothing);
      expect(find.textContaining('402'), findsNothing);
      expect(backend.to('GET', '/api/matches/55/chat/messages'), isEmpty);
    });

    testWidgets('ready thread renders its intentional empty conversation', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/chat/threads',
          const FakeResponse(200, {
            'results': [
              {
                'match_id': 55,
                'deal_id': 7,
                'counterparty_id': 99,
                'counterparty_name': 'Yacine',
                'route': 'Paris → Algiers',
                'status': 'accepted',
                'can_send': true,
                'unread_count': 0,
              },
            ],
          }),
        )
        ..on(
          'GET',
          '/api/matches/55/chat-eligibility',
          const FakeResponse(200, {
            'eligible': true,
            'reason': 'ok',
            'match_id': 55,
          }),
        )
        ..on(
          'GET',
          '/api/matches/55/chat/messages',
          const FakeResponse(200, {
            'count': 0,
            'next': null,
            'results': <Object>[],
          }),
        );
      final container = containerFor(backend);

      await pumpApp(
        tester,
        const ChatThreadScreen(matchId: 55),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('Say hello'), findsOneWidget);
      expect(find.text('Write a message'), findsOneWidget);
      expect(find.text('Yacine'), findsOneWidget);
    });
  });

  group('missing empty states', () {
    testWidgets('Notifications names its empty state', (tester) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/notifications',
          const FakeResponse(200, {
            'count': 0,
            'next': null,
            'results': <Object>[],
          }),
        )
        ..on(
          'GET',
          '/api/notifications/unread-count',
          const FakeResponse(200, {'unread': 0}),
        );
      await pumpApp(
        tester,
        const NotificationsScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      expect(find.text('Nothing new'), findsOneWidget);
    });

    testWidgets('Payouts names its empty state', (tester) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/payouts',
          const FakeResponse(200, {'results': <Object>[]}),
        );
      await pumpApp(
        tester,
        const PayoutsScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      expect(find.text('No payouts yet'), findsOneWidget);
    });

    testWidgets('Ratings names its empty state', (tester) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/users/me/ratings',
          const FakeResponse(200, {'results': <Object>[]}),
        );
      await pumpApp(
        tester,
        const RatingsScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      expect(find.text('No ratings yet'), findsOneWidget);
    });
  });
}
