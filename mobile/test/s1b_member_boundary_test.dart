/// Rule S-4: the member's screens end with the member's session (brief
/// S1-B). The app runs here as `main()` runs it: inside the member boundary,
/// over the real session core, router, screens, client and sockets, with the
/// server in memory.
///
/// Member A is sign-in `sid-a` of account 42; member B is sign-in `sid-b` of
/// account 43. Every request is recorded with its bearer, so "nothing of A
/// is sent as B" is read off the wire.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/app_settings.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/api/api_client.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/features/auth/account_gate.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/kyc/kyc_screen.dart';
import 'package:shiptrip/features/profile/dzd_setup_screen.dart';
import 'package:shiptrip/l10n/app_localizations_en.dart';

import 'support/fake_api.dart';

final _en = LEn();

Map<String, dynamic> _accountA({String name = 'Amina Bouzid'}) => {
  ...meFixture(),
  'full_name': name,
};

Map<String, dynamic> _accountB({String name = 'Bilal Haddad'}) => {
  ...meFixture(id: 43),
  'full_name': name,
  'email': 'bilal@example.com',
};

/// The sign-in a request was sent as, read from its bearer; null for none.
String? _sentAs(RecordedRequest request) {
  final bearer = request.headers['Authorization'];
  return bearer is String && bearer.startsWith('Bearer ')
      ? SessionCore.sidOf(bearer.substring(7))
      : null;
}

class _IdleConnection implements NotificationSocketConnection {
  final _controller = StreamController<dynamic>();
  bool closed = false;

  @override
  Stream<dynamic> get stream => _controller.stream;

  @override
  Future<void> close() async {
    closed = true;
    if (!_controller.isClosed) await _controller.close();
  }
}

/// One phone: its storage, its core, the server, and how each member's
/// container is built, as `main()` builds it.
class _Phone {
  _Phone({bool member = true, Map<String, dynamic>? accountA}) {
    final a = accountA ?? _accountA();
    backend.session = coreFor(
      backend,
      storage: MemoryStorage({
        if (member) SessionCore.recordKey: signedInRecord(account: a),
      }),
    );
    backend
      ..emptyDiscovery()
      ..handle(
        'GET',
        '/api/me',
        (r) => FakeResponse(200, _sentAs(r) == 'sid-b' ? _accountB() : a),
      )
      ..on('POST', '/api/auth/sign-out', const FakeResponse(205))
      ..on('POST', '/api/auth/sign-in', signInAnswer(user: _accountB()))
      ..fallback = _memberRead;
  }

  final backend = FakeBackend();
  final tokens = FakeTokenStore();
  final settings = DeviceSettings();
  final connections = <_IdleConnection>[];

  SessionCore get core => backend.session;

  ProviderContainer container() => ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      sessionCoreProvider.overrideWithValue(core),
      deviceSettingsProvider.overrideWithValue(settings),
      fakeApiClient(backend),
      notificationSocketProvider.overrideWith(
        (ref) => NotificationSocket(
          connector: (_, _) async {
            final connection = _IdleConnection();
            connections.add(connection);
            return connection;
          },
        ),
      ),
    ],
  );

  Future<void> boot(WidgetTester tester) async {
    tester.view.devicePixelRatio = 1;
    tester.view.physicalSize = const Size(412, 915);
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
      MemberBoundary(
        session: core,
        container: container,
        child: const ShipTripApp(),
      ),
    );
    await _settle(tester);
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox.shrink());
      await _settle(tester, 5);
    });
  }

  /// Member A's sign-in ends, as the member signing out does.
  Future<void> endA() => core.end('sid-a', EndReason.signedOut);

  /// Member B signs in on the same phone, the way every sign-in control
  /// does: one attempt, then the sign-in the server issued.
  Future<void> signInB() async {
    final attempt = core.reserve();
    expect(attempt, isNotNull, reason: 'B starts from signed out');
    await core.signedIn(attempt!, signInFor(sid: 'sid-b', account: _accountB()));
  }

  /// Every request sent as [sid] since the test started.
  List<RecordedRequest> sentAs(String sid, String method, String path) => [
    for (final r in backend.to(method, path))
      if (_sentAs(r) == sid) r,
  ];

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
    if (r.path == '/api/discovery/profile/me') {
      return FakeResponse(200, ownProfileFixture());
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

/// The container of the tree on screen now.
ProviderContainer _current(WidgetTester tester) =>
    ProviderScope.containerOf(tester.element(find.byType(ShipTripApp)));

Future<void> _open(WidgetTester tester, String location) async {
  unawaited(_current(tester).read(routerProvider).push<void>(location));
  await _settle(tester);
}

/// The image picker's platform side, answering when the test says so.
class _Picker {
  _Picker() {
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(_channel, (call) {
          final answer = Completer<Object?>();
          pending.add(answer);
          return answer.future;
        });
    addTearDown(
      () => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(_channel, null),
    );
  }

  static const _channel = MethodChannel('plugins.flutter.io/image_picker');
  final pending = <Completer<Object?>>[];
}

void main() {
  // -------------------------------------------------------------------------
  // Plan Appendix A, P3B round 8, blocker 1: pointer down on A's control, a
  // rebuild publishes B, the release runs B's callback.
  group('S-4: a gesture does not outlive its member', () {
    testWidgets('pointer down on A\'s email-language row, A ends, B signs in, '
        'pointer up: nothing runs', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      await _open(tester, '/profile/language');

      final gesture = await tester.startGesture(
        tester.getCenter(find.text('Français').last),
      );
      await phone.endA();
      await phone.signInB();
      await tester.pump();
      await gesture.up();
      await _settle(tester);

      expect(phone.backend.to('PATCH', '/api/me'), isEmpty);
    });

    testWidgets('pointer down on A\'s public-profile consent, A ends, B signs '
        'in, pointer up: nothing runs', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      await _open(tester, '/profile/public');

      final gesture = await tester.startGesture(
        tester.getCenter(find.text(_en.publicShowSwitch)),
      );
      await phone.endA();
      await phone.signInB();
      await tester.pump();
      await gesture.up();
      await _settle(tester);

      expect(phone.backend.to('PUT', '/api/discovery/profile/me'), isEmpty);
    });
  });

  // -------------------------------------------------------------------------
  // Plan Appendix A, P3B round 8, blocker 3: the name draft and the language
  // retry take their scope when submitted.
  group('S-4: nothing of A\'s screens is in B\'s', () {
    testWidgets('a dialog, a sheet and a name draft at A\'s end: after B signs '
        'in none of them is there, and the draft is never sent', (
      tester,
    ) async {
      final phone = _Phone(accountA: _accountA(name: ''));
      await phone.boot(tester);
      await _open(tester, '/auth/name');
      await tester.enterText(find.byType(TextField), 'Draft of A');
      final context = tester.element(find.text(_en.accountNameLabel));
      unawaited(
        showModalBottomSheet<void>(
          context: context,
          builder: (_) => const Text('Sheet of A'),
        ),
      );
      await _settle(tester, 5);
      unawaited(
        showDialog<void>(
          context: context,
          builder: (_) => const AlertDialog(content: Text('Dialog of A')),
        ),
      );
      await _settle(tester, 5);
      expect(find.text('Dialog of A'), findsOneWidget);

      await phone.endA();
      await phone.signInB();
      await _settle(tester);

      expect(find.text('Draft of A'), findsNothing);
      expect(find.text('Sheet of A'), findsNothing);
      expect(find.text('Dialog of A'), findsNothing);
      final continueButton = find.text(_en.actionContinue);
      if (continueButton.evaluate().isNotEmpty) {
        await tester.tap(continueButton.first);
        await _settle(tester);
      }
      expect(
        phone.backend
            .to('PATCH', '/api/me')
            .where((r) => r.body['full_name'] == 'Draft of A'),
        isEmpty,
      );
    });

    testWidgets('A\'s failed language save, A ends, B signs in: there is no '
        'Retry, and nothing is sent as B', (tester) async {
      final phone = _Phone();
      phone.backend.on(
        'PATCH',
        '/api/me',
        const FakeResponse(500, {'code': 'server_error'}),
      );
      await phone.boot(tester);
      await _open(tester, '/profile/language');
      await tester.tap(find.text('Français').last);
      await _settle(tester);
      expect(find.text(_en.actionRetry), findsOneWidget);
      expect(phone.sentAs('sid-a', 'PATCH', '/api/me'), hasLength(1));

      await phone.endA();
      await phone.signInB();
      await _settle(tester);
      final retry = find.text(_en.actionRetry);
      if (retry.evaluate().isNotEmpty) {
        await tester.tap(retry);
        await _settle(tester);
      }

      expect(phone.sentAs('sid-b', 'PATCH', '/api/me'), isEmpty);
    });

    testWidgets('the cheque photo and form of A, A ends, B signs in: the '
        'screen is gone and nothing is uploaded', (tester) async {
      final picker = _Picker();
      final phone = _Phone();
      await phone.boot(tester);
      await _open(tester, '/profile/payouts/dzd');
      expect(find.byType(DzdSetupScreen), findsOneWidget);
      await tester.tap(find.text(_en.dzdChequeAddPhoto).first);
      await _settle(tester, 5);
      await tester.tap(find.text(_en.dzdChequeAddPhoto).last);
      await _settle(tester, 5);
      picker.pending.single.complete('/tmp/cheque-of-a.jpg');
      await _settle(tester, 5);

      await phone.endA();
      await phone.signInB();
      await _settle(tester);

      expect(find.byType(DzdSetupScreen), findsNothing);
      expect(
        phone.backend.requests.where(
          (r) => r.method == 'POST' && r.path.contains('payout'),
        ),
        isEmpty,
      );
    });
  });

  // -------------------------------------------------------------------------
  group('S-4: what returns into a tree that has gone is dropped', () {
    testWidgets('a KYC photo the picker returns after A ended is dropped', (
      tester,
    ) async {
      final picker = _Picker();
      final phone = _Phone();
      await phone.boot(tester);
      await _open(tester, '/kyc');
      expect(find.byType(KycScreen), findsOneWidget);
      await tester.tap(find.text(_en.kycFrontImage));
      await _settle(tester, 5);
      expect(picker.pending, hasLength(1));

      await phone.endA();
      await phone.signInB();
      await _settle(tester);
      picker.pending.single.complete('/tmp/front-of-a.jpg');
      await _settle(tester);

      expect(tester.takeException(), isNull);
      expect(find.byType(KycScreen), findsNothing);
      expect(
        phone.backend.requests.where((r) => r.path.contains('kyc')),
        isEmpty,
      );
    });

    testWidgets('A\'s account deletion answered after B signed in: B stays '
        'signed in', (tester) async {
      final phone = _Phone();
      final answer = Completer<FakeResponse>();
      phone.backend
        ..on(
          'GET',
          '/api/me/deletion',
          const FakeResponse(200, {
            'blockers': <String>[],
            'password_required': false,
            'apple_authorization_required': false,
          }),
        )
        ..handle('POST', '/api/me/deletion', (_) => answer.future);
      await phone.boot(tester);
      await _open(tester, '/profile/delete-account');
      await tester.tap(find.text(_en.deleteAccountAction));
      await _settle(tester, 5);
      await tester.tap(find.text(_en.deleteAccountConfirm).last);
      await _settle(tester, 5);
      expect(phone.backend.to('POST', '/api/me/deletion'), hasLength(1));

      await phone.endA();
      await phone.signInB();
      await _settle(tester);
      answer.complete(const FakeResponse(204, <String, dynamic>{}));
      await _settle(tester);

      expect(phone.core.current?.sid, 'sid-b');
      expect(phone.core.notice, isNull);
      expect(_current(tester).read(sessionProvider), isA<SessionSignedIn>());
    });

    testWidgets('A\'s controller, signing out or deleting after B signed '
        'in, ends nothing', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      final session = _current(tester).read(sessionProvider.notifier);

      await phone.endA();
      await phone.signInB();
      await session.signOut();
      await session.accountDeleted();
      await _settle(tester);

      expect(phone.core.current?.sid, 'sid-b');
    });

    testWidgets('an old client and an old ref after the end get "session '
        'ended", and nothing is sent', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      final old = _current(tester);
      final client = old.read(apiClientProvider);
      final sent = phone.backend.requests.length;

      await phone.endA();
      await phone.signInB();
      // Before the frame that removes A's tree, and after it.
      await expectLater(client.getObject('/api/one'), throwsA(isA<SessionEnded>()));
      await expectLater(
        old.read(apiClientProvider).postVoid('/api/one'),
        throwsA(isA<SessionEnded>()),
      );
      await _settle(tester);
      await expectLater(client.getObject('/api/one'), throwsA(isA<SessionEnded>()));
      expect(() => old.read(apiClientProvider), throwsStateError);

      expect(
        phone.backend.requests.skip(sent).where((r) => r.path == '/api/one'),
        isEmpty,
      );
    });

    testWidgets('an answer to A\'s request that lands after the end is '
        'dropped', (tester) async {
      final phone = _Phone();
      final answer = Completer<FakeResponse>();
      phone.backend.handle('GET', '/api/one', (_) => answer.future);
      await phone.boot(tester);
      final request = _current(tester)
          .read(apiClientProvider)
          .getObject('/api/one');

      await phone.endA();
      answer.complete(const FakeResponse(200, {'of': 'A'}));
      await expectLater(request, throwsA(isA<SessionEnded>()));
    });

    testWidgets('an open socket at A\'s end closes and does not reconnect', (
      tester,
    ) async {
      final phone = _Phone();
      await phone.boot(tester);
      expect(phone.connections, isNotEmpty);
      final opened = phone.connections.length;

      await phone.endA();
      await _settle(tester);
      // Long past every backoff.
      await tester.pump(const Duration(minutes: 2));
      await _settle(tester);

      expect(phone.connections.take(opened).every((c) => c.closed), isTrue);
      expect(phone.connections, hasLength(opened), reason: 'no reconnect');
      expect(_current(tester).read(sessionProvider), isA<SessionSignedOut>());
    });
  });

  // -------------------------------------------------------------------------
  group('S-4: the boundary', () {
    testWidgets('the old container is disposed without the signed-out state '
        'being published into it', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      final old = _current(tester);
      final shown = <SessionState>[];
      old.listen(sessionProvider, (_, next) => shown.add(next));

      await phone.endA();
      await _settle(tester);

      expect(shown, isEmpty);
      expect(() => old.read(sessionProvider), throwsStateError);
      expect(identical(_current(tester), old), isFalse);
      expect(_current(tester).read(sessionProvider), isA<SessionSignedOut>());
      expect(find.byType(HomeScreen), findsOneWidget);
    });

    testWidgets('language and theme are identical on the frame before and '
        'after the reset', (tester) async {
      final phone = _Phone();
      await phone.boot(tester);
      _current(tester).read(localeProvider.notifier).set(const Locale('ar'));
      _current(tester).read(themeModeProvider.notifier).set(ThemeMode.dark);
      await _settle(tester, 5);
      BuildContext screen() => tester.element(find.byType(HomeScreen));
      expect(Localizations.localeOf(screen()), const Locale('ar'));
      expect(Theme.of(screen()).brightness, Brightness.dark);

      await phone.endA();
      await tester.pump();

      expect(Localizations.localeOf(screen()), const Locale('ar'));
      expect(Theme.of(screen()).brightness, Brightness.dark);
    });

    testWidgets('"sign in to continue" resumes only the flow that asked; a '
        'guest\'s client kept from before fails with "session ended"', (
      tester,
    ) async {
      final phone = _Phone(member: false);
      await phone.boot(tester);
      final guest = _current(tester);
      final guestClient = guest.read(apiClientProvider);

      final answer = ensureAccount(
        tester.element(find.byType(HomeScreen)),
        AccountReason.postRequest,
      );
      await _settle(tester);
      await tester.tap(find.text(_en.authSignIn).first);
      await _settle(tester);
      await tester.enterText(find.byType(TextField).at(0), 'bilal@example.com');
      await tester.enterText(find.byType(TextField).at(1), 'secret');
      await tester.tap(find.text(_en.authSignIn).last);
      await _settle(tester);

      expect(await answer, isTrue);
      expect(identical(_current(tester), guest), isTrue, reason: 'same tree');
      expect(phone.core.current?.sid, 'sid-b');
      await expectLater(
        guestClient.getObject('/api/one'),
        throwsA(isA<SessionEnded>()),
      );
      expect(phone.backend.to('GET', '/api/one'), isEmpty);
      expect(guest.read(apiClientProvider), isNot(same(guestClient)));
    });
  });

  // -------------------------------------------------------------------------
  group('S-4: a socket takes its token through the client of its sign-in', () {
    test('the bearer of a client is its own sign-in\'s, and none after it', () async {
      final backend = FakeBackend();
      await backend.session.load();
      final client = apiClientFor(backend);
      expect(client.bearer, fakeToken('sid-a', 'access'));
      await backend.session.end('sid-a', EndReason.signedOut);
      expect(client.bearer, isNull);
      expect(ApiClient(session: backend.session, sid: null).bearer, isNull);
    });
  });
}
