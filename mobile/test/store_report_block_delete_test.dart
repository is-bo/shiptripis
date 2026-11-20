/// Store readiness: reporting a chat message, blocking a member, the blocked
/// people list, and deleting the account from inside the app.
///
/// The screens are driven over a fake server, so these hold what the app
/// sends and how it reads the server's answer:
///
/// * **report**: a received message is reported by pressing and holding it,
///   with a required reason, an optional note and "also block"; the app's
///   own and removed messages offer nothing;
/// * **block**: the top bar blocks after a confirmation; the notice above the
///   missing composer unblocks; a send refused as blocked says so without an
///   error snack;
/// * **removed**: a message Wassla removed reads "Removed by Wassla";
/// * **blocked people**: Profile lists them and unblocks each;
/// * **deletion**: what is still open is listed with no way to delete; the
///   password is checked by the server; an Apple account asks Apple for a
///   code first, and cannot be deleted where Apple is not offered; once
///   deleted the phone is signed out and Profile says so.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/auth/social_sign_in.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/features/chat/chat_thread_controller.dart';
import 'package:shiptrip/features/chat/chat_thread_screen.dart';
import 'package:shiptrip/features/profile/blocked_people_screen.dart';
import 'package:shiptrip/features/profile/delete_account_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/fake_social_sign_in.dart';
import 'support/harness.dart';

final L _en = lookupL(const Locale('en'));
final L _ar = lookupL(const Locale('ar'));

void main() {
  group('reporting and blocking in a chat', () {
    testWidgets('a received message is reported, with a reason, and the '
        'sender blocked in the same step', (tester) async {
      final server = _ChatServer([
        _message(1, senderId: 99, body: 'Pay me cash or else'),
        _message(2, body: 'No, through Wassla'),
      ]);
      await _openThread(tester, server);

      // The app's own message offers no report.
      await tester.longPress(find.text('No, through Wassla'));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatReportTitle), findsNothing);

      await tester.longPress(find.text('Pay me cash or else'));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatReportTitle), findsOneWidget);

      // A reason is required.
      await tester.tap(find.text(_en.chatReportSend));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatReportChooseReason), findsOneWidget);
      expect(server.backend.to('POST', _ChatServer.reportPath), isEmpty);

      await tester.tap(find.text(_en.chatReportReasonHarassment));
      await tester.enterText(
        find.descendant(
          of: find.byType(BottomSheet),
          matching: find.byType(TextField),
        ),
        'Threatening me',
      );
      await tester.ensureVisible(find.text(_en.chatReportAlsoBlock));
      await tester.tap(find.text(_en.chatReportAlsoBlock));
      server.onBlock = () => server.blockedByMe = true;
      await tester.tap(find.text(_en.chatReportSend));
      await tester.pumpAndSettle();

      final report = server.backend.lastTo('POST', _ChatServer.reportPath)!;
      expect(report.body, {
        'reason': 'harassment',
        'note': 'Threatening me',
        'block': true,
      });
      expect(find.text(_en.chatReportTitle), findsNothing);
      expect(find.text(_en.chatReportSent), findsOneWidget);
      // The eligibility was read again: the composer gives way to the notice.
      expect(find.text(_en.chatBlockedByMeTitle), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      // History stays readable.
      expect(find.text('Pay me cash or else'), findsOneWidget);
    });

    testWidgets('blocking asks first, and the notice unblocks', (tester) async {
      final server = _ChatServer([_message(1, senderId: 99)]);
      await _openThread(tester, server);

      await tester.tap(find.byTooltip(_en.chatSafetyTitle));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatSafetySubtitle), findsOneWidget);
      await tester.tap(find.text(_en.chatBlockAction));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatBlockConfirmTitle), findsOneWidget);

      // Cancelling blocks nobody.
      await tester.tap(find.text(_en.actionCancel));
      await tester.pumpAndSettle();
      expect(server.backend.to('POST', _ChatServer.blockPath), isEmpty);

      await tester.tap(find.byTooltip(_en.chatSafetyTitle));
      await tester.pumpAndSettle();
      await tester.tap(find.text(_en.chatBlockAction));
      await tester.pumpAndSettle();
      server.onBlock = () => server.blockedByMe = true;
      await tester.tap(find.widgetWithText(TextButton, _en.chatBlockAction));
      await tester.pumpAndSettle();
      expect(server.backend.to('POST', _ChatServer.blockPath), hasLength(1));
      expect(find.text(_en.chatBlockedByMeTitle), findsOneWidget);
      expect(find.byType(TextField), findsNothing);
      // Let the confirmation snack go: it sits over the notice.
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();

      server.onUnblock = () => server.blockedByMe = false;
      await tester.tap(find.text(_en.chatUnblockAction));
      await tester.pumpAndSettle();
      expect(server.backend.to('DELETE', _ChatServer.blockPath), hasLength(1));
      expect(find.text(_en.chatBlockedByMeTitle), findsNothing);
      expect(find.byType(TextField), findsOneWidget);
    });

    testWidgets('blocked by the other member: no unblock, no composer', (
      tester,
    ) async {
      final server = _ChatServer([_message(1, senderId: 99)])
        ..blockedByOther = true;
      await _openThread(tester, server);
      expect(find.text(_en.chatBlockedTitle), findsOneWidget);
      expect(find.text(_en.chatUnblockAction), findsNothing);
      expect(find.byType(TextField), findsNothing);
      expect(find.text('message 1'), findsOneWidget);
    });

    testWidgets('a removed message reads "Removed by Wassla" and cannot be '
        'reported', (tester) async {
      final server = _ChatServer([
        {..._message(1, senderId: 99, body: ''), 'removed': true},
      ]);
      await _openThread(tester, server);
      expect(find.text(_en.chatMessageRemoved), findsOneWidget);
      await tester.longPress(find.text(_en.chatMessageRemoved));
      await tester.pumpAndSettle();
      expect(find.text(_en.chatReportTitle), findsNothing);
    });

    test('a send refused because of a block stops sending', () async {
      final server = _ChatServer([_message(1, senderId: 99)]);
      server.backend.on(
        'POST',
        _ChatServer.messagesPath,
        const FakeResponse(403, {'reason': 'blocked', 'match_id': 7}),
      );
      final container = containerFor(server.backend);
      addTearDown(container.dispose);
      final controller = ChatThreadController(
        matchId: 7,
        accountId: 42,
        repository: container.read(chatRepositoryProvider),
        registerLive: (_) => () {},
        invalidateThreads: () {},
      );
      addTearDown(controller.dispose);
      await controller.initialLoad;

      expect(await controller.send('hello'), isNotNull);
      expect(controller.sendBlock.name, 'blocked');
      expect(controller.canSend, isFalse);
    });

    testWidgets('the report sheet fits a small phone in Arabic', (
      tester,
    ) async {
      final server = _ChatServer([_message(1, senderId: 99, body: 'مرحبا')]);
      await _openThread(
        tester,
        server,
        locale: const Locale('ar'),
        device: DeviceProfile.smallAndroid,
      );
      await tester.longPress(find.text('مرحبا'));
      await tester.pumpAndSettle();
      expect(find.text(_ar.chatReportTitle), findsOneWidget);
      expect(
        Directionality.of(tester.element(find.text(_ar.chatReportTitle))),
        TextDirection.rtl,
      );
      await tester.ensureVisible(find.text(_ar.chatReportSend));
      expect(tester.takeException(), isNull);
    });
  });

  group('blocked people', () {
    testWidgets('lists each person and unblocks them', (tester) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()));
      var blocks = <Map<String, dynamic>>[
        {
          'user_id': 99,
          'name': 'Karim Haddad',
          'deleted': false,
          'blocked_at': '2026-11-19T10:00:00Z',
        },
        {
          'user_id': 77,
          'name': '',
          'deleted': true,
          'blocked_at': '2026-11-18T10:00:00Z',
        },
      ];
      backend
        ..handle(
          'GET',
          '/api/me/blocks',
          (_) => FakeResponse(200, {'results': blocks}),
        )
        ..handle('DELETE', '/api/me/blocks/99', (_) {
          blocks = blocks.where((row) => row['user_id'] != 99).toList();
          return const FakeResponse(204, <String, dynamic>{});
        });
      await pumpApp(
        tester,
        const BlockedPeopleScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();

      expect(find.text('Karim Haddad'), findsOneWidget);
      expect(find.text(_en.chatDeletedAccount), findsOneWidget);

      await tester.tap(find.text(_en.chatUnblockAction).first);
      await tester.pumpAndSettle();
      expect(backend.to('DELETE', '/api/me/blocks/99'), hasLength(1));
      expect(find.text('Karim Haddad'), findsNothing);
      expect(find.text(_en.chatDeletedAccount), findsOneWidget);
    });

    testWidgets('says so when nobody is blocked', (tester) async {
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/me/blocks',
          const FakeResponse(200, {'results': <Object>[]}),
        );
      await pumpApp(
        tester,
        const BlockedPeopleScreen(),
        container: containerFor(backend),
      );
      await tester.pumpAndSettle();
      expect(find.text(_en.blockedPeopleEmptyTitle), findsOneWidget);
    });
  });

  group('deleting the account', () {
    testWidgets('what is still open is listed, and nothing can be deleted', (
      tester,
    ) async {
      final server = _DeletionServer()
        ..blockers = ['open_deliveries', 'open_requests'];
      await _openDeletion(tester, server);

      expect(find.text(_en.deleteAccountBlockedTitle), findsOneWidget);
      expect(find.text(_en.deleteAccountBlockerDeliveries), findsOneWidget);
      expect(find.text(_en.deleteAccountBlockerRequests), findsOneWidget);
      expect(find.text(_en.deleteAccountAction), findsNothing);
      expect(find.text(_en.deleteAccountPasswordLabel), findsNothing);
    });

    testWidgets('the password is checked, then the phone is signed out and '
        'Profile says the account is deleted', (tester) async {
      final server = _DeletionServer();
      final container = await _openDeletion(tester, server);

      // An empty password is caught before anything is sent.
      await tester.tap(find.text(_en.deleteAccountAction));
      await _settle(tester);
      expect(find.text(_en.deleteAccountPasswordMissing), findsOneWidget);

      await tester.enterText(_passwordField(), 'wrong');
      await tester.tap(find.text(_en.deleteAccountAction));
      await _settle(tester);
      expect(find.text(_en.deleteAccountConfirmTitle), findsOneWidget);
      await tester.tap(find.text(_en.deleteAccountConfirm));
      await _settle(tester);
      expect(find.text(_en.deleteAccountPasswordIncorrect), findsOneWidget);
      expect(container.read(sessionProvider), isA<SessionSignedIn>());

      await tester.enterText(_passwordField(), server.password);
      await tester.tap(find.text(_en.deleteAccountAction));
      await _settle(tester);
      await tester.tap(find.text(_en.deleteAccountConfirm));
      await _settle(tester);

      final sent = server.backend.to('POST', _DeletionServer.path);
      expect(sent.last.body, {'password': server.password});
      final session = container.read(sessionProvider);
      expect(session, isA<SessionSignedOut>());
      expect((session as SessionSignedOut).becauseDeleted, isTrue);
      expect(container.read(routerProvider).state.uri.path, '/profile');
      expect(find.text(_en.deleteAccountDone), findsOneWidget);
      // The server already ended every session.
      expect(server.backend.to('POST', '/api/auth/sign-out'), isEmpty);
    });

    testWidgets('an Apple account asks Apple for a code first, and cancelling '
        "Apple's sheet deletes nothing", (tester) async {
      final server = _DeletionServer()
        ..passwordRequired = false
        ..appleRequired = true;
      final social = FakeSocialSignIn();
      social.appleCodeAnswers
        ..clear()
        ..addAll([() => null, () => 'fresh-apple-code']);
      final container = await _openDeletion(tester, server, social: social);
      expect(find.text(_en.deleteAccountAppleNote), findsOneWidget);
      expect(find.text(_en.deleteAccountPasswordLabel), findsNothing);

      Future<void> confirm() async {
        await tester.tap(find.text(_en.deleteAccountAction));
        await _settle(tester);
        await tester.tap(find.text(_en.deleteAccountConfirm));
        await _settle(tester);
      }

      await confirm();
      expect(social.appleCodeCalls, 1);
      expect(server.backend.to('POST', _DeletionServer.path), isEmpty);
      expect(container.read(sessionProvider), isA<SessionSignedIn>());

      await confirm();
      expect(server.backend.lastTo('POST', _DeletionServer.path)!.body, {
        'apple_authorization_code': 'fresh-apple-code',
      });
      expect(container.read(sessionProvider), isA<SessionSignedOut>());
    });

    testWidgets('where Apple is not offered, an Apple account is pointed to '
        'an iPhone or support', (tester) async {
      final server = _DeletionServer()
        ..passwordRequired = false
        ..appleRequired = true;
      await _openDeletion(
        tester,
        server,
        social: FakeSocialSignIn(offersApple: false),
      );
      expect(find.text(_en.deleteAccountAppleElsewhereTitle), findsOneWidget);
      expect(find.text(_en.deleteAccountAction), findsNothing);
    });

    testWidgets('fits a small phone in Arabic', (tester) async {
      final server = _DeletionServer();
      await _openDeletion(
        tester,
        server,
        locale: 'ar',
        size: const Size(320, 640),
      );
      expect(find.text(_ar.deleteAccountTitle), findsWidgets);
      expect(find.text(_ar.deleteAccountAction), findsOneWidget);
      expect(tester.takeException(), isNull);
    });
  });
}

// ---------------------------------------------------------------------------
// Chat
// ---------------------------------------------------------------------------

Future<void> _openThread(
  WidgetTester tester,
  _ChatServer server, {
  Locale locale = const Locale('en'),
  DeviceProfile device = DeviceProfile.android,
}) async {
  await pumpApp(
    tester,
    const ChatThreadScreen(matchId: 7),
    container: containerFor(server.backend),
    locale: locale,
    device: device,
  );
  await tester.pumpAndSettle();
}

class _ChatServer {
  _ChatServer(this.messages) {
    backend
      ..on('GET', '/api/me', FakeResponse(200, meFixture()))
      ..handle(
        'GET',
        '/api/chat/threads',
        (_) => FakeResponse(200, [
          {
            'match_id': 7,
            'deal_id': 3,
            'counterparty_id': 99,
            'counterparty_name': 'Karim',
            'route': 'Paris - Algiers',
            'status': 'accepted',
            'can_send': !_blocked,
            'blocked_by_me': blockedByMe,
            'unread_count': 0,
          },
        ]),
      )
      ..handle(
        'GET',
        '/api/matches/7/chat-eligibility',
        (_) => FakeResponse(200, {
          'eligible': !_blocked,
          'reason': _blocked ? 'blocked' : 'ok',
          'match_id': 7,
          'blocked_by_me': blockedByMe,
        }),
      )
      ..handle('GET', messagesPath, (_) {
        return FakeResponse(200, {
          'count': messages.length,
          'results': messages,
          'has_more': false,
          'next': null,
          'oldest_id': messages.isEmpty ? null : messages.first['id'],
          'latest_id': messages.isEmpty ? null : messages.last['id'],
        });
      })
      ..handle('POST', reportPath, (request) {
        if (request.body['block'] == true) onBlock?.call();
        return const FakeResponse(201, {'id': 1, 'status': 'open'});
      })
      ..handle('POST', blockPath, (_) {
        onBlock?.call();
        return const FakeResponse(204, <String, dynamic>{});
      })
      ..handle('DELETE', blockPath, (_) {
        onUnblock?.call();
        return const FakeResponse(204, <String, dynamic>{});
      });
  }

  static const messagesPath = '/api/matches/7/chat/messages';
  static const reportPath = '/api/chat/messages/1/report';
  static const blockPath = '/api/matches/7/block';

  final FakeBackend backend = FakeBackend();
  final List<Map<String, dynamic>> messages;
  bool blockedByMe = false;
  bool blockedByOther = false;
  VoidCallback? onBlock;
  VoidCallback? onUnblock;

  bool get _blocked => blockedByMe || blockedByOther;
}

Map<String, dynamic> _message(int id, {int senderId = 42, String? body}) => {
  'id': id,
  'match_id': 7,
  'sender_id': senderId,
  'body': body ?? 'message $id',
  'removed': false,
  'created_at': '2026-11-19T12:00:00Z',
  'read_at': null,
};

// ---------------------------------------------------------------------------
// Account deletion: the real app, so the landing on Profile is the router's.
// ---------------------------------------------------------------------------

class _Store extends FakeTokenStore {
  _Store({super.locale});

  @override
  Future<String?> readAccess() async => 'access-token';

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
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

class _DeletionServer {
  _DeletionServer() {
    backend
      ..emptyDiscovery()
      ..handle(
        'GET',
        '/api/me',
        (_) => deleted
            ? const FakeResponse(401, {'code': 'not_authenticated'})
            : FakeResponse(200, meFixture()),
      )
      ..handle(
        'GET',
        path,
        (_) => FakeResponse(200, {
          'blockers': blockers,
          'password_required': passwordRequired,
          'apple_authorization_required': appleRequired,
        }),
      )
      ..handle('POST', path, (request) {
        if (passwordRequired && request.body['password'] != password) {
          return const FakeResponse(400, {'code': 'password_incorrect'});
        }
        deleted = true;
        return const FakeResponse(204, <String, dynamic>{});
      })
      ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}))
      ..fallback = _memberRead;
  }

  static const path = '/api/me/deletion';

  final backend = FakeBackend();
  List<String> blockers = const [];
  bool passwordRequired = true;
  bool appleRequired = false;
  bool deleted = false;
  final String password = 'correct horse battery';

  static FakeResponse _memberRead(RecordedRequest r) {
    if (r.path == '/api/notifications' || r.path == '/api/deals') {
      return const FakeResponse(200, {
        'count': 0,
        'next': null,
        'previous': null,
        'results': <Object>[],
      });
    }
    if (r.path == '/api/notifications/unread-count') {
      return const FakeResponse(200, {'unread': 0});
    }
    if (r.path.contains('count')) {
      return const FakeResponse(200, {'count': 0});
    }
    return const FakeResponse(200, <Object>[]);
  }
}

Future<void> _settle(WidgetTester tester, [int frames = 30]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Finder _passwordField() => find.descendant(
  of: find.byType(DeleteAccountScreen),
  matching: find.byType(TextFormField),
);

Future<ProviderContainer> _openDeletion(
  WidgetTester tester,
  _DeletionServer server, {
  SocialSignIn? social,
  String? locale,
  Size size = const Size(412, 915),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.reset);
  final tokens = _Store(locale: locale);
  await tester.pumpWidget(
    ProviderScope(
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        apiClientProvider.overrideWithValue(
          apiClientFor(server.backend, tokens),
        ),
        notificationSocketProvider.overrideWithValue(
          NotificationSocket(connector: (_, _) async => _IdleConnection()),
        ),
        socialSignInProvider.overrideWithValue(social ?? FakeSocialSignIn()),
      ],
      child: const ShipTripApp(),
    ),
  );
  await _settle(tester);
  final container = ProviderScope.containerOf(
    tester.element(find.byType(ShipTripApp)),
  );
  container.read(routerProvider).goNamed(Routes.profileDeleteAccount);
  await _settle(tester);
  expect(find.byType(DeleteAccountScreen), findsOneWidget);
  addTearDown(() async {
    await tester.pumpWidget(const SizedBox.shrink());
    await _settle(tester, 5);
  });
  return container;
}
