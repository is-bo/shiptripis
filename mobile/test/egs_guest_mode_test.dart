/// Part C of the email, guest and social plan: guest mode.
///
/// The real app is booted over a fake server, so the router, the shell, the
/// session and every provider are the production ones. These tests hold:
///
/// * **the guard**: one list of places a guest may be, Home first, and
///   sign-in in front of every other place, which it then returns to;
/// * **no private request**: a guest who looks everywhere reads only the
///   public listings, reviews, support and the place catalogue;
/// * **the account moment**: an account-only action asks for an account and,
///   once made, goes ahead on the screen it was asked from, with what the
///   guest had chosen; closing or leaving the account screen does nothing;
/// * **session expiry**: on a public screen the person stays as a guest and
///   is told; on a private screen they get sign-in, which takes them back;
/// * **the layout**: every guest surface fits a 320 px phone at 1.6x text in
///   Arabic, with nothing under the bottom navigation.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/session/session_core.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/design/components/feedback.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/navigation.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/identity.dart';
import 'package:shiptrip/features/auth/account_gate.dart';
import 'package:shiptrip/features/discovery/discovery_widgets.dart';
import 'package:shiptrip/features/auth/forgot_password_screen.dart';
import 'package:shiptrip/features/auth/guest_states.dart';
import 'package:shiptrip/features/auth/sign_in_screen.dart';
import 'package:shiptrip/features/auth/sign_up_screen.dart';
import 'package:shiptrip/features/auth/verify_email_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/journeys/journey_create_screen.dart';
import 'package:shiptrip/features/onboarding/benefits_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/features/shell/app_shell.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';

final L _en = lookupL(const Locale('en'));
final L _ar = lookupL(const Locale('ar'));

/// The phone's own keys. A widget test has no keystore to answer for the
/// installation id or a pending push token, so this one does.
class _Store extends FakeTokenStore {
  _Store({super.locale});

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
}

/// The server refuses the current sign-in's refresh token: the one exit a
/// session that expired takes.
void _expire(ProviderContainer container) {
  final core = container.read(sessionCoreProvider);
  unawaited(core.end(core.current!.sid, EndReason.refused));
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

const _personId = 'p-1';

Map<String, dynamic> _personCard() => profileCardFixture(
  id: _personId,
  name: 'Nadia',
  routes: [usualRouteFixture()],
);

/// A server with something to look at, and the member's own reads answered
/// calmly for once the guest has made an account.
class _Server {
  _Server({this.journeys = const [], this.role = 'both'}) {
    backend
      ..emptyDiscovery()
      ..on(
        'GET',
        '/api/discovery/trips',
        discoveryPage([tripCardFixture(11, name: 'Samira')]),
      )
      ..on(
        'GET',
        '/api/discovery/requests',
        discoveryPage([requestCardFixture(31, title: 'Passport photos')]),
      )
      ..on('GET', '/api/discovery/people', discoveryPage([_personCard()]))
      ..on(
        'GET',
        '/api/discovery/people/$_personId',
        FakeResponse(200, {
          'state': 'results',
          'profile': _personCard(),
          'trips': <Object>[],
          'requests': <Object>[],
        }),
      )
      ..on(
        'GET',
        '/api/discovery/people/$_personId/reviews',
        const FakeResponse(200, {
          'state': 'results',
          'rating': {'state': 'rated', 'average': 4.5, 'count': 1},
          'results': [
            {
              'id': 5,
              'score': 5,
              'tags': ['on_time'],
              'comment': 'Careful and on time',
              'comment_removed': false,
              'written_by': 'sender',
              'month': '2026-11',
              'my_report': null,
            },
          ],
          'next_offset': null,
        }),
      )
      ..handle('GET', '/api/discovery/alerts', (_) {
        return FakeResponse(200, {'results': alerts});
      })
      ..handle('POST', '/api/discovery/alerts', (r) {
        final alert = alertFixture(
          alerts.length + 1,
          watches: r.body['watches'] as String,
          subject: {'id': _personId, 'display_name': 'Nadia'},
        );
        alerts.add(alert);
        return FakeResponse(201, alert);
      })
      ..handle('GET', '/api/me', (_) => FakeResponse(200, _me()))
      ..handle('POST', '/api/auth/sign-in', (_) => _signedIn(200))
      ..handle('POST', '/api/auth/sign-up', (_) {
        verified = false;
        return _signedIn(201);
      })
      ..handle('POST', '/api/auth/verify-email', (_) {
        verified = true;
        return const FakeResponse(200, <String, dynamic>{});
      })
      ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}))
      ..handle(
        'GET',
        '/api/journeys',
        (_) => FakeResponse(200, [
          for (final id in journeys) liveJourneyFixture(id),
        ]),
      )
      ..on(
        'POST',
        '/api/discovery/requests/31/interest',
        const FakeResponse(201, {
          'request_id': 31,
          'journey_id': 3,
          'created': true,
        }),
      )
      ..fallback = _memberRead;
  }

  final backend = FakeBackend();

  /// The trips the account has once it exists.
  final List<int> journeys;

  /// The side the account may work from, as the server states it.
  final String role;

  final alerts = <Map<String, dynamic>>[];
  bool verified = true;

  Map<String, dynamic> _me() => {
    ...meFixture(),
    'role': role,
    'is_email_verified': verified,
  };

  FakeResponse _signedIn(int status) => FakeResponse(status, {
    'access': fakeToken('sid-b', 'access'),
    'refresh': fakeToken('sid-b'),
    'user': _me(),
  });

  /// The member's own lists, all empty.
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

  List<RecordedRequest> posts(String path) => backend.to('POST', path);
}

Future<void> _settle(WidgetTester tester, [int frames = 30]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

/// Boots the real app, the way `main` does.
Future<ProviderContainer> _boot(
  WidgetTester tester,
  _Server server, {
  _Store? store,
  bool member = false,
  MemoryStorage? storage,
  Size size = const Size(412, 915),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.reset);

  final tokens = store ?? _Store();
  server.backend.session = coreFor(
    server.backend,
    signedIn: member,
    storage: storage,
  );
  await tester.pumpWidget(
    ProviderScope(
      retry: appRetry,
      overrides: [
        tokenStoreProvider.overrideWithValue(tokens),
        sessionCoreProvider.overrideWithValue(server.backend.session),
        apiClientProvider.overrideWithValue(apiClientFor(server.backend)),
        notificationSocketProvider.overrideWithValue(
          NotificationSocket(connector: (_, _) async => _IdleConnection()),
        ),
      ],
      child: const ShipTripApp(),
    ),
  );
  await _settle(tester);
  return ProviderScope.containerOf(tester.element(find.byType(ShipTripApp)));
}

/// Unmounts the app so the push coordinator and sockets stop before the
/// test's pending-timer check.
Future<void> _shutdown(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await _settle(tester, 5);
}

GoRouter _router(ProviderContainer container) => container.read(routerProvider);

/// The top route's location.
Uri _at(ProviderContainer container) => _router(container).state.uri;

/// Android's back button.
Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
    'flutter/navigation',
    const JSONMethodCodec().encodeMethodCall(const MethodCall('popRoute')),
    (_) {},
  );
  await _settle(tester);
}

Future<void> _openTab(WidgetTester tester, String label) async {
  await tester.tap(
    find.descendant(
      of: find.byType(AppNavigationBar),
      matching: find.text(label),
    ),
  );
  await _settle(tester);
}

Finder _field(String label) => find.descendant(
  of: find.ancestor(of: find.text(label), matching: find.byType(AppTextField)),
  matching: find.byType(TextFormField),
);

Finder _button(String label) => find.widgetWithText(AppButton, label);

Finder _hero() => find.byWidgetPredicate(
  (w) => w is AppButton && w.variant == AppButtonVariant.hero,
  description: 'the hero button',
);

/// The account screen, open for [reason].
void _expectGate(AccountReason reason) {
  expect(find.byType(AccountGateScreen), findsOneWidget);
  expect(find.text(reason.title(_en)), findsOneWidget);
  expect(find.text(reason.body(_en)), findsOneWidget);
}

/// No account-flow screen is left anywhere on the stack.
void _expectFlowClosed() {
  for (final type in [
    AccountGateScreen,
    SignInScreen,
    SignUpScreen,
    ForgotPasswordScreen,
    VerifyEmailScreen,
  ]) {
    expect(find.byType(type, skipOffstage: false), findsNothing);
  }
}

Future<void> _signIn(WidgetTester tester) async {
  await tester.enterText(_field(_en.authEmail), 'sender@example.com');
  await tester.enterText(_field(_en.authPassword), 'correct horse battery');
  await tester.tap(_button(_en.authSignIn));
  await _settle(tester);
}

Future<void> _signInFromGate(WidgetTester tester) async {
  await tester.tap(_button(_en.accountGateHaveAccount));
  await _settle(tester);
  expect(find.byType(SignInScreen), findsOneWidget);
  await _signIn(tester);
}

/// Every request the guest made is to a public read.
void _expectOnlyPublicReads(_Server server) {
  final allowed = [
    RegExp(r'^/api/discovery/(trips|requests|people)$'),
    RegExp(r'^/api/discovery/people/[^/]+$'),
    RegExp(r'^/api/discovery/(people|trips)/[^/]+/reviews$'),
    RegExp(r'^/api/support$'),
    RegExp(r'^/api/geography/(countries|places)$'),
  ];
  final private = [
    for (final r in server.backend.requests)
      if (r.method != 'GET' || !allowed.any((p) => p.hasMatch(r.path)))
        '${r.method} ${r.path}',
  ];
  expect(private, isEmpty, reason: 'a guest sent $private');
  expect(
    server.backend.requests.where((r) => r.headers.containsKey(_bearer)),
    isEmpty,
    reason: 'a guest has no bearer to send',
  );
}

const _bearer = 'Authorization';

void main() {
  group('the guard', () {
    test('one list says where a guest may be', () {
      for (final path in [
        '/home',
        '/deliveries',
        '/chat',
        '/profile',
        '/profile/language',
        '/profile/appearance',
        '/profile/notifications',
        '/how-it-works',
        '/location/pick',
        '/discover/trips',
        '/discover/people/p-1',
        '/reviews/person/p-1',
        '/reviews/trip/4',
        '/auth/sign-in',
        '/auth/continue',
        '/guest/pay/token',
      ]) {
        expect(isPublicLocation(path), isTrue, reason: path);
      }
      for (final path in [
        '/notifications',
        '/requests/new',
        '/requests/4',
        '/journeys/new',
        '/journeys/4',
        '/matches/4',
        '/deals/4',
        '/chat/4',
        '/profile/payouts',
        '/profile/public',
        '/profile/alerts',
        '/kyc',
        '/splash',
        '/homes',
        '/discover',
      ]) {
        expect(isPublicLocation(path), isFalse, reason: path);
      }
    });

    test('only a place inside the app is a place to return to', () {
      expect(isSafePostLoginLocation('/deals/7'), isTrue);
      expect(isSafePostLoginLocation('/requests/new?x=1'), isTrue);
      for (final location in [
        null,
        '',
        'deals/7',
        '//evil.example/x',
        r'/\evil.example',
        r'/\\evil.example/x',
        r'/deals\7',
        'https://evil.example',
        '/auth/sign-in',
        '/splash',
      ]) {
        expect(isSafePostLoginLocation(location), isFalse, reason: location);
      }
    });

    testWidgets('a signed-out launch opens Home, ready to look around', (
      tester,
    ) async {
      final server = _Server();
      final container = await _boot(tester, server);

      expect(_at(container).path, '/home');
      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.byType(ShipTripMark), findsOneWidget);
      expect(find.text(_en.authSignIn), findsOneWidget);
      expect(find.byType(NotificationBell), findsNothing);
      expect(find.text(_en.guestWelcomeTitle), findsOneWidget);
      expect(find.text(_en.roleSender), findsOneWidget);
      expect(find.text('Samira'), findsWidgets, reason: 'the listings');
      expect(find.text(_en.homeCreateRequest), findsOneWidget);

      await _shutdown(tester);
    });

    testWidgets('a guest can switch to carrying, and it is kept', (
      tester,
    ) async {
      final store = _Store();
      final container = await _boot(tester, _Server(), store: store);

      await tester.tap(find.text(_en.roleTraveler));
      await _settle(tester);

      expect(container.read(roleContextProvider), RoleContext.traveler);
      expect(await store.readRoleContext(), RoleContext.traveler.wire);
      expect(find.text('Passport photos'), findsWidgets);
      expect(find.text(_en.homeCreateJourney), findsOneWidget);

      await _shutdown(tester);
    });

    testWidgets('a private place asks for sign-in, then opens', (tester) async {
      final container = await _boot(tester, _Server());
      final router = _router(container);

      for (final path in [
        '/requests/new',
        '/journeys/new',
        '/profile/alerts',
      ]) {
        router.go(path);
        await _settle(tester, 5);
        expect(_at(container).path, '/auth/sign-in', reason: path);
        expect(_at(container).queryParameters['next'], path);
        expect(_at(container).queryParameters['continue'], '1');
      }

      router.go('/notifications');
      await _settle(tester);
      expect(find.byType(SignInScreen), findsOneWidget);
      await _signIn(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(_at(container).path, '/notifications');
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('a private place pushed over Home asks for sign-in, then opens '
        'there, with Home under it', (tester) async {
      final container = await _boot(tester, _Server());

      _router(container).push('/notifications');
      await _settle(tester);
      expect(_at(container).path, '/auth/sign-in');
      expect(_at(container).queryParameters['next'], '/notifications');
      await _signIn(tester);

      expect(_at(container).path, '/notifications');
      _expectFlowClosed();
      await _systemBack(tester);
      expect(_at(container).path, '/home');

      await _shutdown(tester);
    });

    testWidgets('a member who reaches an account-flow screen by a link is '
        'moved on at once', (tester) async {
      final container = await _boot(tester, _Server(), member: true);
      final router = _router(container);

      for (final location in [
        '/auth/sign-in?continue=1',
        '/auth/sign-up?continue=1',
        '/auth/forgot?continue=1',
        '/auth/continue?reason=post_request',
      ]) {
        router.go(location);
        await _settle(tester);
        expect(_at(container).path, '/home', reason: location);
        _expectFlowClosed();
      }
      router.go('/auth/sign-in?continue=1&next=/notifications');
      await _settle(tester);
      expect(_at(container).path, '/notifications');
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('the public places open for a guest', (tester) async {
      final container = await _boot(tester, _Server());
      final router = _router(container);

      for (final path in [
        '/how-it-works',
        '/profile/language',
        '/profile/appearance',
        '/discover/trips',
        '/discover/people/$_personId',
        '/reviews/person/$_personId',
      ]) {
        router.go(path);
        await _settle(tester, 10);
        expect(_at(container).path, path);
      }
      expect(find.byType(SignInScreen, skipOffstage: false), findsNothing);

      await _shutdown(tester);
    });
  });

  testWidgets('a guest who looks everywhere reads only public listings', (
    tester,
  ) async {
    final server = _Server();
    final container = await _boot(tester, server);
    final router = _router(container);

    // Home, both sides, and a card from each.
    await tester.tap(find.text('Samira').first);
    await _settle(tester);
    await _systemBack(tester);
    await tester.tap(find.text(_en.roleTraveler));
    await _settle(tester);
    await tester.tap(find.text('Passport photos').first);
    await _settle(tester);
    await _systemBack(tester);

    // The other tabs.
    await _openTab(tester, _en.navDeliveries);
    expect(find.text(_en.guestDeliveriesTitle), findsOneWidget);
    await _openTab(tester, _en.navChat);
    expect(find.text(_en.guestChatTitle), findsOneWidget);
    await _openTab(tester, _en.navProfile);
    expect(find.text(_en.guestProfileTitle), findsOneWidget);
    expect(find.text(_en.guestHowItWorks), findsOneWidget);

    // Everything a guest can open.
    for (final path in [
      '/how-it-works',
      '/profile/language',
      '/profile/appearance',
      '/discover/trips',
      '/discover/requests',
      '/discover/people',
      '/discover/people/$_personId',
      '/reviews/person/$_personId',
    ]) {
      router.push(path);
      await _settle(tester, 10);
      await _systemBack(tester);
    }
    await _openTab(tester, _en.navHome);
    await tester.drag(find.byType(Scrollable).first, const Offset(0, 300));
    await _settle(tester);

    _expectOnlyPublicReads(server);
    expect(server.backend.to('GET', '/api/discovery/trips'), isNotEmpty);
    expect(server.backend.to('GET', '/api/discovery/requests'), isNotEmpty);

    await _shutdown(tester);
  });

  group('the account moment', () {
    testWidgets('"Send a parcel": sign in, and the form opens over Home; '
        'Back returns to Home', (tester) async {
      final container = await _boot(tester, _Server());

      await tester.tap(_hero());
      await _settle(tester);
      _expectGate(AccountReason.postRequest);
      expect(_at(container).path, '/auth/continue');

      await _signInFromGate(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(find.byType(RequestCreateScreen), findsOneWidget);
      expect(_at(container).path, '/requests/new');
      _expectFlowClosed();

      await _systemBack(tester);
      expect(find.byType(RequestCreateScreen), findsNothing);
      expect(_at(container).path, '/home');
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.byType(NotificationBell), findsOneWidget, reason: 'member');

      await _shutdown(tester);
    });

    testWidgets('"Add a journey": create an account, confirm the email, and '
        'the trip form opens', (tester) async {
      final server = _Server();
      final container = await _boot(tester, server);
      await tester.tap(find.text(_en.roleTraveler));
      await _settle(tester);

      await tester.tap(_hero());
      await _settle(tester);
      _expectGate(AccountReason.postTrip);

      await tester.tap(_button(_en.accountGateEmail));
      await _settle(tester);
      await tester.enterText(_field(_en.authFullName), 'Amina Bouzid');
      await tester.enterText(_field(_en.authEmail), 'sender@example.com');
      await tester.enterText(_field(_en.authPassword), 'correct horse battery');
      await tester.enterText(_field(_en.authPhone), '+213555000111');
      await tester.tap(_button(_en.authSignUp));
      await _settle(tester);

      expect(server.posts('/api/auth/sign-up'), hasLength(1));
      expect(find.byType(VerifyEmailScreen), findsOneWidget);
      expect(find.byType(JourneyCreateScreen), findsNothing);

      await tester.enterText(
        find.descendant(
          of: find.byType(VerifyEmailScreen),
          matching: find.byType(EditableText),
        ),
        '123456',
      );
      await tester.tap(_button(_en.actionConfirm));
      await _settle(tester);

      expect(server.posts('/api/auth/verify-email'), hasLength(1));
      expect(find.byType(JourneyCreateScreen), findsOneWidget);
      expect(_at(container).path, '/journeys/new');
      expect(container.read(roleContextProvider), RoleContext.traveler);
      _expectFlowClosed();

      await _systemBack(tester);
      expect(_at(container).path, '/home');

      await _shutdown(tester);
    });

    testWidgets('leaving the confirm-email screen still lets the action go '
        'ahead: the account exists', (tester) async {
      final container = await _boot(tester, _Server());

      await tester.tap(_hero());
      await _settle(tester);
      await tester.tap(_button(_en.accountGateEmail));
      await _settle(tester);
      await tester.enterText(_field(_en.authFullName), 'Amina Bouzid');
      await tester.enterText(_field(_en.authEmail), 'sender@example.com');
      await tester.enterText(_field(_en.authPassword), 'correct horse battery');
      await tester.enterText(_field(_en.authPhone), '+213555000111');
      await tester.tap(_button(_en.authSignUp));
      await _settle(tester);
      expect(find.byType(VerifyEmailScreen), findsOneWidget);

      await _systemBack(tester);

      expect(find.byType(RequestCreateScreen), findsOneWidget);
      _expectFlowClosed();
      expect(container.read(sessionProvider), isA<SessionSignedIn>());

      await _shutdown(tester);
    });

    testWidgets('closing the account screen, or Back, does nothing', (
      tester,
    ) async {
      final server = _Server();
      final container = await _boot(tester, server);

      await tester.tap(_hero());
      await _settle(tester);
      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);
      _expectFlowClosed();
      expect(find.byType(RequestCreateScreen), findsNothing);
      expect(_at(container).path, '/home');

      await tester.tap(_hero());
      await _settle(tester);
      await tester.tap(_button(_en.accountGateHaveAccount));
      await _settle(tester);
      await _systemBack(tester);
      expect(find.byType(AccountGateScreen), findsOneWidget);
      await _systemBack(tester);
      _expectFlowClosed();
      expect(find.byType(RequestCreateScreen), findsNothing);
      expect(_at(container).path, '/home');
      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      _expectOnlyPublicReads(server);

      await _shutdown(tester);
    });

    testWidgets('a second tap while the account screen opens asks once', (
      tester,
    ) async {
      final container = await _boot(tester, _Server());
      final home = tester.element(find.byType(HomeScreen));

      final first = ensureAccount(home, AccountReason.generic);
      await tester.pump();
      final second = ensureAccount(home, AccountReason.generic);
      await _settle(tester);

      expect(find.byType(AccountGateScreen), findsOneWidget);
      expect(await second, isFalse);
      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);
      expect(await first, isFalse);
      expect(_at(container).path, '/home');

      await _shutdown(tester);
    });

    testWidgets('Back on a sign-in that is still answering: the action goes '
        'ahead once it does', (tester) async {
      final server = _Server();
      final answer = Completer<FakeResponse>();
      server.backend.handle('POST', '/api/auth/sign-in', (_) => answer.future);
      final container = await _boot(tester, server);

      await tester.tap(_hero());
      await _settle(tester);
      await tester.tap(_button(_en.accountGateHaveAccount));
      await _settle(tester);
      await tester.enterText(_field(_en.authEmail), 'sender@example.com');
      await tester.enterText(_field(_en.authPassword), 'correct horse battery');
      await tester.tap(_button(_en.authSignIn));
      await tester.pump();
      await _systemBack(tester);
      expect(find.byType(SignInScreen), findsNothing);
      _expectGate(AccountReason.postRequest);

      answer.complete(
        FakeResponse(200, {
          'access': fakeToken('sid-b', 'access'),
          'refresh': fakeToken('sid-b'),
          'user': meFixture(),
        }),
      );
      await _settle(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(find.byType(RequestCreateScreen), findsOneWidget);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('a sign-in the account screen\'s own button finishes is '
        'finished once, by that button', (tester) async {
      final container = await _boot(tester, _Server());

      await tester.tap(_hero());
      await _settle(tester);
      final gate = tester.element(
        find
            .descendant(
              of: find.byType(AccountGateScreen),
              matching: find.byWidgetPredicate((_) => true),
            )
            .first,
      );
      final signedIn = AccountGateScreen.finishingHere(
        gate,
        () => container
            .read(sessionProvider.notifier)
            .signIn(
              email: 'sender@example.com',
              password: 'correct horse battery',
            ),
      );
      await _settle(tester);
      await signedIn;

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      _expectGate(AccountReason.postRequest);

      finishSignIn(gate, AccountFlow.of(_router(container).state));
      await _settle(tester);

      expect(find.byType(RequestCreateScreen), findsOneWidget);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('a new stack while the account screen is open answers "no"', (
      tester,
    ) async {
      final container = await _boot(tester, _Server());
      final home = tester.element(find.byType(HomeScreen));

      final pending = ensureAccount(home, AccountReason.generic);
      await _settle(tester);
      expect(find.byType(AccountGateScreen), findsOneWidget);
      _router(container).go('/discover/trips');
      await _settle(tester);

      expect(await pending, isFalse);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('"Sign in" on guest Home returns to Home as the member', (
      tester,
    ) async {
      final container = await _boot(tester, _Server());

      await tester.tap(find.widgetWithText(TextButton, _en.authSignIn));
      await _settle(tester);
      await _signIn(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(_at(container).path, '/home');
      expect(find.byType(NotificationBell), findsOneWidget);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    for (final from in ['/home', '/discover/trips']) {
      testWidgets('"Post a parcel for this route" from $from keeps the route '
          'through sign-in', (tester) async {
        final container = await _boot(tester, _Server());
        if (from != '/home') {
          _router(container).push(from);
          await _settle(tester);
        }

        await tester.tap(find.text('Samira').first);
        await _settle(tester);
        await tester.tap(_button(_en.tripPostForRoute));
        await _settle(tester);
        _expectGate(AccountReason.postRequest);

        await _signInFromGate(tester);

        final form = tester.widget<RequestCreateScreen>(
          find.byType(RequestCreateScreen),
        );
        expect(form.prefill?.pickup?.displayLabel, 'Paris');
        expect(form.prefill?.delivery?.displayLabel, 'Algiers');
        _expectFlowClosed();
        await _systemBack(tester);
        expect(_at(container).path, from);

        await _shutdown(tester);
      });
    }

    testWidgets('"I can carry this" sends the signal once signed in', (
      tester,
    ) async {
      final server = _Server(journeys: [3]);
      await _boot(tester, server);
      await tester.tap(find.text(_en.roleTraveler));
      await _settle(tester);

      await tester.tap(find.text('Passport photos').first);
      await _settle(tester);
      await tester.tap(_button(_en.requestCarryAction));
      await _settle(tester);
      _expectGate(AccountReason.carry);
      expect(server.posts('/api/discovery/requests/31/interest'), isEmpty);

      await _signInFromGate(tester);

      expect(
        server.backend
            .lastTo('POST', '/api/discovery/requests/31/interest')
            ?.body,
        {'journey_id': 3},
      );
      expect(server.posts('/api/discovery/requests/31/interest'), hasLength(1));
      expect(find.text(_en.actionDone), findsOneWidget);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('"I can carry this" without a trip offers to add one', (
      tester,
    ) async {
      final server = _Server();
      await _boot(tester, server);
      await tester.tap(find.text(_en.roleTraveler));
      await _settle(tester);

      await tester.tap(find.text('Passport photos').first);
      await _settle(tester);
      await tester.tap(_button(_en.requestCarryAction));
      await _settle(tester);
      await _signInFromGate(tester);

      expect(server.posts('/api/discovery/requests/31/interest'), isEmpty);
      expect(_button(_en.carryPublishTrip), findsOneWidget);
      await tester.tap(_button(_en.carryPublishTrip));
      await _settle(tester);
      expect(find.byType(JourneyCreateScreen), findsOneWidget);

      await _shutdown(tester);
    });

    testWidgets('an alert switched on as a guest is created once signed in', (
      tester,
    ) async {
      final server = _Server();
      final container = await _boot(tester, server);
      _router(container).push('/discover/people/$_personId');
      await _settle(tester);

      await tester.tap(find.byType(Switch).first);
      await _settle(tester);
      _expectGate(AccountReason.alert);
      await _signInFromGate(tester);

      expect(server.posts('/api/discovery/alerts'), hasLength(1));
      expect(_at(container).path, '/discover/people/$_personId');
      expect(tester.widget<Switch>(find.byType(Switch).first).value, isTrue);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('the alert asked for on one side stays that side when the '
        'account turns out to work from the other', (tester) async {
      final server = _Server(role: 'sender');
      final container = await _boot(tester, server);
      await tester.tap(find.text(_en.roleTraveler));
      await _settle(tester);
      _router(container).push('/discover/people/$_personId');
      await _settle(tester);

      await tester.tap(find.byType(Switch).first);
      await _settle(tester);
      await _signInFromGate(tester);

      expect(container.read(roleContextProvider), RoleContext.sender);
      expect(
        server.posts('/api/discovery/alerts').single.body['watches'],
        'requests',
        reason: 'the guest asked while carrying',
      );

      await _shutdown(tester);
    });

    testWidgets('an alert the member already has is not created twice', (
      tester,
    ) async {
      final server = _Server();
      server.alerts.add(
        alertFixture(
          9,
          watches: 'trips',
          subject: {'id': _personId, 'display_name': 'Nadia'},
        ),
      );
      final container = await _boot(tester, server);
      _router(container).push('/discover/people/$_personId');
      await _settle(tester);

      await tester.tap(find.byType(Switch).first);
      await _settle(tester);
      await _signInFromGate(tester);

      expect(server.posts('/api/discovery/alerts'), isEmpty);
      expect(server.backend.to('DELETE', '/api/discovery/alerts/9'), isEmpty);
      expect(tester.widget<Switch>(find.byType(Switch).first).value, isTrue);

      await _shutdown(tester);
    });

    testWidgets('reporting a review asks for an account, then opens the '
        'report', (tester) async {
      final container = await _boot(tester, _Server());
      _router(container).push('/reviews/person/$_personId');
      await _settle(tester);

      await tester.tap(find.byTooltip(_en.reviewsMenuLabel));
      await _settle(tester);
      await tester.tap(find.text(_en.reviewsReportAction));
      await _settle(tester);
      _expectGate(AccountReason.report);
      await _signInFromGate(tester);

      expect(find.text(_en.reviewReportSheetTitle), findsOneWidget);
      expect(_at(container).path, '/reviews/person/$_personId');

      await _shutdown(tester);
    });

    testWidgets('Deliveries, Chat and How Wassla works lead to the account '
        'screen', (tester) async {
      final container = await _boot(tester, _Server());

      await _openTab(tester, _en.navDeliveries);
      await tester.tap(_button(_en.guestAccountAction));
      await _settle(tester);
      _expectGate(AccountReason.deliveries);
      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);
      expect(_at(container).path, '/deliveries');

      await _openTab(tester, _en.navChat);
      await tester.tap(_button(_en.guestAccountAction));
      await _settle(tester);
      _expectGate(AccountReason.chat);
      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);

      await _openTab(tester, _en.navProfile);
      await tester.tap(find.text(_en.guestHowItWorks));
      await _settle(tester);
      expect(find.byType(BenefitsScreen), findsOneWidget);
      for (var i = 0; i < 5; i++) {
        if (find.byType(AccountGateScreen).evaluate().isNotEmpty) break;
        await tester.tap(
          find.byWidgetPredicate(
            (w) => w.runtimeType.toString() == '_AdvanceButton',
          ),
        );
        await _settle(tester, 10);
      }
      _expectGate(AccountReason.generic);
      await _signInFromGate(tester);
      expect(find.byType(BenefitsScreen, skipOffstage: false), findsNothing);
      expect(_at(container).path, '/profile');
      _expectFlowClosed();

      await _shutdown(tester);
    });
  });

  group('session expiry', () {
    testWidgets('on a public screen the person stays, as a guest, and is '
        'told', (tester) async {
      final container = await _boot(tester, _Server(), member: true);
      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      _router(container).push('/discover/trips');
      await _settle(tester);

      _expire(container);
      await _settle(tester);

      expect(_at(container).path, '/discover/trips');
      expect(find.byType(SignInScreen, skipOffstage: false), findsNothing);
      await _systemBack(tester);
      expect(_at(container).path, '/home');
      expect(find.text(_en.guestSignedOutNotice), findsOneWidget);
      expect(find.byType(NotificationBell), findsNothing);

      await _openTab(tester, _en.navProfile);
      expect(find.text(_en.guestSignedOutNotice), findsOneWidget);
      await tester.tap(
        find.descendant(
          of: find.byType(SignedOutNotice),
          matching: find.byType(AppIconButton),
        ),
      );
      await _settle(tester);

      expect(find.text(_en.guestSignedOutNotice), findsNothing);
      final session = container.read(sessionProvider);
      expect(session, isA<SessionSignedOut>());
      expect((session as SessionSignedOut).becauseExpired, isFalse);
      await _openTab(tester, _en.navHome);
      expect(find.text(_en.guestSignedOutNotice), findsNothing);

      await _shutdown(tester);
    });

    testWidgets('the notice\'s "Sign in" brings the member back to where '
        'they were', (tester) async {
      final container = await _boot(tester, _Server(), member: true);
      _expire(container);
      await _settle(tester);

      await tester.tap(
        find.descendant(
          of: find.byType(SignedOutNotice),
          matching: find.text(_en.authSignIn),
        ),
      );
      await _settle(tester);
      expect(find.text(_en.stateSessionExpiredTitle), findsOneWidget);
      await _signIn(tester);

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(_at(container).path, '/home');
      expect(find.text(_en.guestSignedOutNotice), findsNothing);
      _expectFlowClosed();

      await _shutdown(tester);
    });

    testWidgets('on a private screen: Home, with sign-in on top, which goes '
        'back there', (tester) async {
      final container = await _boot(tester, _Server(), member: true);
      _router(container).push('/notifications');
      await _settle(tester);
      expect(_at(container).path, '/notifications');

      _expire(container);
      await _settle(tester);

      final at = _at(container);
      expect(at.path, '/auth/sign-in');
      expect(at.queryParameters['next'], '/notifications');
      expect(
        _router(container).routerDelegate.currentConfiguration.uri.path,
        '/home',
      );
      expect(find.text(_en.stateSessionExpiredTitle), findsOneWidget);

      await _signIn(tester);
      expect(_at(container).path, '/notifications');
      _expectFlowClosed();
      await _systemBack(tester);
      expect(_at(container).path, '/home');

      await _shutdown(tester);
    });

    testWidgets('closing sign-in after an expiry leaves a guest on Home', (
      tester,
    ) async {
      final container = await _boot(tester, _Server(), member: true);
      _router(container).push('/notifications');
      await _settle(tester);
      _expire(container);
      await _settle(tester);

      await _systemBack(tester);

      expect(_at(container).path, '/home');
      expect(find.byType(SignInScreen, skipOffstage: false), findsNothing);
      expect(find.text(_en.guestSignedOutNotice), findsOneWidget);

      await _shutdown(tester);
    });

    testWidgets('signing out on Profile stays on guest Profile, untold', (
      tester,
    ) async {
      final container = await _boot(tester, _Server(), member: true);
      await _openTab(tester, _en.navProfile);

      // Awaited while fake time runs; awaiting it bare would wait on timers
      // the test clock never fires.
      final out = container.read(sessionProvider.notifier).signOut();
      await _settle(tester);
      await out;

      expect(_at(container).path, '/profile');
      expect(find.text(_en.guestProfileTitle), findsOneWidget);
      expect(find.text(_en.guestSignedOutNotice), findsNothing);

      await _shutdown(tester);
    });

    testWidgets('signing out on Home with a slow keystore and slow reads: the '
        'guest\'s cards, no failure, nothing of the member\'s', (tester) async {
      final server = _Server();
      var slow = false;
      // The member and the guest are shown different cards, so a card left
      // over from the member is seen.
      Future<FakeResponse> listing(
        RecordedRequest r, {
        required FakeResponse member,
        required FakeResponse guest,
      }) async {
        if (r.headers.containsKey(_bearer)) return member;
        if (slow) await Future<void>.delayed(const Duration(milliseconds: 400));
        return guest;
      }

      server.backend
        ..handle(
          'GET',
          '/api/discovery/trips',
          (r) => listing(
            r,
            member: discoveryPage([tripCardFixture(12, name: 'Mounir')]),
            guest: discoveryPage([tripCardFixture(11, name: 'Samira')]),
          ),
        )
        ..handle(
          'GET',
          '/api/discovery/people',
          (r) => listing(
            r,
            member: discoveryPage([
              profileCardFixture(id: 'p-9', name: 'Karim'),
            ]),
            guest: discoveryPage([_personCard()]),
          ),
        );
      final storage = MemoryStorage({SessionCore.recordKey: signedInRecord()});
      final container = await _boot(tester, server, storage: storage);
      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(find.text('Mounir', skipOffstage: false), findsWidgets);

      slow = true;
      final write = storage.writeGate = Completer<void>();
      Future<void>.delayed(const Duration(milliseconds: 250), write.complete);
      final out = container.read(sessionProvider.notifier).signOut();
      await _settle(tester);
      await out;
      await _settle(tester, 60);

      expect(container.read(sessionProvider), isA<SessionSignedOut>());
      expect(find.byType(HomeScreen), findsOneWidget);
      expect(find.text('Samira', skipOffstage: false), findsWidgets);
      expect(find.text('Nadia', skipOffstage: false), findsWidgets);
      for (final member in ['Mounir', 'Karim']) {
        expect(find.text(member, skipOffstage: false), findsNothing);
      }
      expect(find.byType(InlineFailure, skipOffstage: false), findsNothing);
      expect(find.byType(StaleNote, skipOffstage: false), findsNothing);

      await _shutdown(tester);
    });
  });

  group('a guest\'s request', () {
    FakeBackend unauthorized() => FakeBackend()
      ..on(
        'GET',
        '/api/discovery/trips',
        const FakeResponse(401, {'detail': 'unauthorized'}),
      )
      ..on('POST', '/api/auth/refresh', const FakeResponse(401, {}));

    test('a refusal is not retried; a cancelled or failed read is', () {
      ApiException failure(ApiFailureKind kind) =>
          ApiException(kind: kind, code: ApiErrorCode.unknown);
      expect(appRetry(0, failure(ApiFailureKind.rateLimited)), isNull);
      expect(appRetry(0, failure(ApiFailureKind.validation)), isNull);
      for (final kind in [
        ApiFailureKind.cancelled,
        ApiFailureKind.server,
        ApiFailureKind.offline,
      ]) {
        expect(appRetry(0, failure(kind)), isNotNull, reason: '$kind');
      }
    });

    test(
      'belongs to no sign-in: answered after a sign-in has finished, it is '
      'still the answer; a member\'s read is voided by its sign-out',
      () async {
        for (final guest in [true, false]) {
          final answer = Completer<FakeResponse>();
          final backend = FakeBackend()
            ..handle('GET', '/api/discovery/trips', (_) => answer.future)
            ..on('POST', '/api/auth/sign-out', const FakeResponse(205));
          final core = backend.session = coreFor(backend, signedIn: !guest);
          await core.load();
          final client = apiClientFor(backend);
          addTearDown(() => client.raw.close(force: true));

          final read = client.getObject('/api/discovery/trips');
          while (backend.requests.isEmpty) {
            await Future<void>.delayed(Duration.zero);
          }
          if (guest) {
            final attempt = core.reserve()!;
            await core.signedIn(
              attempt,
              SignIn(
                sid: 'sid-b',
                account: Account.fromJson(meFixture()),
                access: fakeToken('sid-b', 'access'),
                refresh: fakeToken('sid-b'),
              ),
            );
          } else {
            await core.end('sid-a', EndReason.signedOut);
          }
          answer.complete(const FakeResponse(200, {'state': 'results'}));

          if (guest) {
            expect(await read, {'state': 'results'});
          } else {
            await expectLater(
              read,
              throwsA(
                isA<ApiException>().having(
                  (e) => e.kind,
                  'kind',
                  ApiFailureKind.cancelled,
                ),
              ),
            );
          }
        }
      },
    );

    test('carries no bearer, and its 401 ends nothing and refreshes nothing, '
        'even with a member\'s sign-out still being sent', () async {
      final backend = unauthorized()
        ..handle(
          'POST',
          '/api/auth/sign-out',
          (_) => Completer<FakeResponse>().future,
        );
      final storage = MemoryStorage({
        SessionCore.recordKey: const SessionRecord(
          ended: [EndedSignIn('sid-a', 'a-refresh')],
        ).encode(),
      });
      final core = backend.session = coreFor(backend, storage: storage);
      await core.load();
      final writes = storage.writes;
      final client = apiClientFor(backend);

      await expectLater(
        client.getObject('/api/discovery/trips'),
        throwsA(anything),
      );

      final read = backend.to('GET', '/api/discovery/trips').single;
      expect(read.headers, isNot(contains(_bearer)));
      expect(backend.to('POST', '/api/auth/refresh'), isEmpty);
      expect(storage.writes, writes);
      expect(storage.record!.ended.single.sid, 'sid-a');
    });

    testWidgets('after a sign-out, the guest\'s first reads go without the '
        'member\'s bearer while the sign-out is still being sent, and the '
        'sign-out carries only its refresh token', (tester) async {
      final server = _Server();
      final signOut = Completer<FakeResponse>();
      server.backend.handle(
        'POST',
        '/api/auth/sign-out',
        (_) => signOut.future,
      );
      final storage = MemoryStorage({SessionCore.recordKey: signedInRecord()});
      final container = await _boot(tester, server, storage: storage);
      await _openTab(tester, _en.navProfile);
      final from = server.backend.requests.length;

      final out = container.read(sessionProvider.notifier).signOut();
      await _settle(tester);
      await _openTab(tester, _en.navHome);

      final sent = server.backend.requests.skip(from).toList();
      final signOutCall = sent.singleWhere(
        (r) => r.path == '/api/auth/sign-out',
      );
      expect(signOutCall.headers, isNot(contains(_bearer)));
      expect(signOutCall.body, {'refresh': fakeToken('sid-a')});
      expect(storage.record!.current, isNull);
      expect(
        storage.record!.ended.single.sid,
        'sid-a',
        reason: 'not yet heard',
      );
      final reads = sent.where((r) => r.path.startsWith('/api/discovery'));
      expect(reads, isNotEmpty);
      for (final r in reads) {
        expect(r.headers, isNot(contains(_bearer)), reason: r.path);
      }
      expect(server.backend.to('POST', '/api/auth/refresh'), isEmpty);

      signOut.complete(const FakeResponse(205));
      await _settle(tester, 5);
      await out;
      expect(storage.record!.ended, isEmpty);

      await _shutdown(tester);
    });

    testWidgets('a throttled read shows the throttle at once, asked once', (
      tester,
    ) async {
      final server = _Server();
      server.backend.on(
        'GET',
        '/api/discovery/trips',
        const FakeResponse(429, {'detail': 'throttled'}),
      );
      await _boot(tester, server);

      expect(server.backend.to('GET', '/api/discovery/trips'), hasLength(1));
      expect(find.textContaining(_en.stateRateLimitedBody), findsWidgets);
      await _settle(tester, 100);
      expect(server.backend.to('GET', '/api/discovery/trips'), hasLength(1));

      await _shutdown(tester);
    });
  });

  group('the guest surfaces fit', () {
    const small = Size(320, 640);

    Future<ProviderContainer> bootArabic(WidgetTester tester) async {
      tester.view.padding = const FakeViewPadding(top: 47, bottom: 34);
      tester.view.viewPadding = const FakeViewPadding(top: 47, bottom: 34);
      tester.platformDispatcher.textScaleFactorTestValue = 1.6;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      return _boot(
        tester,
        _Server(),
        store: _Store(locale: 'ar'),
        size: small,
      );
    }

    void expectAboveNavigation(WidgetTester tester, Finder target) {
      final bar = tester.getTopLeft(find.byType(AppNavigationBar)).dy;
      expect(tester.getBottomLeft(target).dy, lessThanOrEqualTo(bar));
    }

    testWidgets('at 320 px, 1.6x text, in Arabic, right to left', (
      tester,
    ) async {
      final container = await bootArabic(tester);
      final router = _router(container);

      expect(
        Directionality.of(tester.element(find.byType(HomeScreen))),
        TextDirection.rtl,
      );
      expect(tester.takeException(), isNull);
      expectAboveNavigation(tester, _hero());

      for (final tab in ['/deliveries', '/chat']) {
        router.go(tab);
        await _settle(tester);
        expect(tester.takeException(), isNull, reason: tab);
        final action = find.widgetWithText(AppButton, _ar.guestAccountAction);
        await tester.ensureVisible(action);
        await _settle(tester, 5);
        expectAboveNavigation(tester, action);
      }

      router.go('/profile');
      await _settle(tester);
      expect(tester.takeException(), isNull);
      final howItWorks = find.text(_ar.guestHowItWorks);
      await tester.scrollUntilVisible(
        howItWorks,
        200,
        scrollable: find
            .descendant(
              of: find.byType(ProfileScreen),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await _settle(tester, 5);
      expect(tester.takeException(), isNull);
      expectAboveNavigation(tester, howItWorks);

      for (final reason in AccountReason.values) {
        router.push('/auth/continue?reason=${reason.wire}');
        await _settle(tester, 10);
        expect(tester.takeException(), isNull, reason: reason.wire);
        final email = find.widgetWithText(AppButton, _ar.accountGateEmail);
        await tester.scrollUntilVisible(
          email,
          200,
          scrollable: find
              .descendant(
                of: find.byType(AccountGateScreen),
                matching: find.byType(Scrollable),
              )
              .first,
        );
        await _settle(tester, 5);
        expect(
          tester.getBottomLeft(email).dy,
          lessThanOrEqualTo(small.height - 34),
          reason: reason.wire,
        );
        await _systemBack(tester);
      }

      await expectHowItWorksFits(tester, router);

      await _shutdown(tester);
    });

    for (final landscape in const [Size(640, 320), Size(800, 360)]) {
      testWidgets('How Wassla works in landscape '
          '${landscape.width.toInt()}x${landscape.height.toInt()}, 1.6x text, '
          'in Arabic', (tester) async {
        // Booted upright: the splash's own landscape layout is not this test's.
        final container = await bootArabic(tester);
        tester.view.physicalSize = landscape;
        tester.view.padding = FakeViewPadding.zero;
        tester.view.viewPadding = FakeViewPadding.zero;
        await _settle(tester, 5);
        expect(tester.takeException(), isNull);

        await expectHowItWorksFits(tester, _router(container));

        await _shutdown(tester);
      });
    }
  });
}

/// Opens How Wassla works and turns through its three chapters, each laid out
/// without an overflow.
Future<void> expectHowItWorksFits(WidgetTester tester, GoRouter router) async {
  router.push('/how-it-works');
  await _settle(tester, 10);
  expect(find.byType(BenefitsScreen), findsOneWidget);
  expect(tester.takeException(), isNull, reason: 'chapter 1');
  for (final chapter in [2, 3]) {
    await tester.tap(
      find.byWidgetPredicate(
        (w) => w.runtimeType.toString() == '_AdvanceButton',
      ),
    );
    await _settle(tester, 10);
    expect(tester.takeException(), isNull, reason: 'chapter $chapter');
  }
  await _systemBack(tester);
}
