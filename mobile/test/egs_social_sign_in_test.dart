/// Part D of the email, guest and social plan: Continue with Google and
/// Continue with Apple.
///
/// The real app is booted over a fake server, with [FakeSocialSignIn] in
/// place of the providers, so no test reaches Google or Apple. These tests
/// hold:
///
/// * **offered only when configured**: no client id, no button; Apple only
///   on iOS;
/// * **signing in**: each provider signs in, from sign-in on its own and
///   from the account screen, where the account moment then completes;
///   cancelling does nothing; each failure has its own copy;
/// * **the nonce**: the server gets the nonce whose SHA-256 Apple was given;
/// * **Apple's name is kept** across a failed attempt, without asking Apple
///   again while its token is still usable;
/// * **the name step**: an account left without a name is asked for one,
///   once, after the sign-in and at the next launch on Home;
/// * **the layout**: every changed screen fits 320 px at 1.6x text in
///   Arabic, with the iPhone's insets.
library;

import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/app.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/auth/social_sign_in.dart';
import 'package:shiptrip/core/push/notification_socket.dart';
import 'package:shiptrip/core/push/push_coordinator.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/primitives.dart';
import 'package:shiptrip/design/identity.dart';
import 'package:shiptrip/features/auth/account_gate.dart';
import 'package:shiptrip/features/auth/account_name_screen.dart';
import 'package:shiptrip/features/auth/sign_in_screen.dart';
import 'package:shiptrip/features/auth/sign_up_screen.dart';
import 'package:shiptrip/features/home/home_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';
import 'package:sign_in_with_apple/sign_in_with_apple.dart';

import 'support/fake_api.dart';
import 'support/fake_social_sign_in.dart';

final L _en = lookupL(const Locale('en'));
final L _ar = lookupL(const Locale('ar'));

class _Store extends FakeTokenStore {
  _Store({super.refresh, super.locale, this.access = 'access-token'});

  final String? access;

  @override
  Future<String?> readAccess() async => access;

  @override
  Future<String> readOrCreateInstallationId() async => 'installation';

  @override
  Future<String?> readPendingPushToken() async => null;

  @override
  Future<void> writePendingPushToken(String? token) async {}
}

_Store _guest({String? locale}) =>
    _Store(refresh: null, access: null, locale: locale);

class _IdleConnection implements NotificationSocketConnection {
  final _controller = StreamController<dynamic>();
  @override
  Stream<dynamic> get stream => _controller.stream;
  @override
  Future<void> close() async {
    if (!_controller.isClosed) await _controller.close();
  }
}

/// A server that signs anyone in with either provider, and keeps the
/// account's name the way the server does: settable only while empty.
class _Server {
  _Server({this.name = 'Amina Bouzid'}) {
    backend
      ..emptyDiscovery()
      ..handle('GET', '/api/me', (_) => FakeResponse(200, _me()))
      ..handle('POST', '/api/auth/oauth/google', (_) => _next(google))
      ..handle('POST', '/api/auth/oauth/apple', (_) => _next(apple))
      ..handle('PATCH', '/api/me', _patch)
      ..on('POST', '/api/auth/sign-out', const FakeResponse(200, {}))
      ..fallback = _memberRead;
  }

  final backend = FakeBackend();

  /// The account's name on the server.
  String name;

  /// A name that reaches the account between the step opening and its
  /// answer (a later sign-in that carried one), so the PATCH is refused.
  String? nameArrivesElsewhere;

  /// What each sign-in answers in turn; the last one repeats. Null signs in.
  final google = <FakeResponse?>[null];
  final apple = <FakeResponse?>[null];

  Map<String, dynamic> _me() => {...meFixture(), 'full_name': name};

  FakeResponse _next(List<FakeResponse?> answers) {
    final answer = answers.length > 1 ? answers.removeAt(0) : answers.single;
    return answer ??
        FakeResponse(200, {
          'access': 'access-token',
          'refresh': 'refresh-token',
          'user': _me(),
        });
  }

  FakeResponse _patch(RecordedRequest r) {
    final elsewhere = nameArrivesElsewhere;
    if (elsewhere != null) name = elsewhere;
    if (name.isNotEmpty) {
      return const FakeResponse(400, {
        'code': 'name_already_set',
        'detail': 'This account already has a name.',
      });
    }
    name = (r.body['full_name'] as String).trim();
    return FakeResponse(200, _me());
  }

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
  List<RecordedRequest> get patches => backend.to('PATCH', '/api/me');
}

Future<void> _settle(WidgetTester tester, [int frames = 30]) async {
  for (var i = 0; i < frames; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Future<ProviderContainer> _boot(
  WidgetTester tester,
  _Server server, {
  SocialSignIn? social,
  _Store? store,
  Size size = const Size(412, 915),
}) async {
  tester.view.devicePixelRatio = 1;
  tester.view.physicalSize = size;
  addTearDown(tester.view.reset);

  final tokens = store ?? _guest();
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
        if (social != null) socialSignInProvider.overrideWithValue(social),
      ],
      child: const ShipTripApp(),
    ),
  );
  await _settle(tester);
  return ProviderScope.containerOf(tester.element(find.byType(ShipTripApp)));
}

Future<void> _shutdown(WidgetTester tester) async {
  await tester.pumpWidget(const SizedBox.shrink());
  await _settle(tester, 5);
}

GoRouter _router(ProviderContainer container) => container.read(routerProvider);

Uri _at(ProviderContainer container) => _router(container).state.uri;

Future<void> _systemBack(WidgetTester tester) async {
  await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
    'flutter/navigation',
    const JSONMethodCodec().encodeMethodCall(const MethodCall('popRoute')),
    (_) {},
  );
  await _settle(tester);
}

Finder _hero() => find.byWidgetPredicate(
  (w) => w is AppButton && w.variant == AppButtonVariant.hero,
  description: 'the hero button',
);

Finder _google([L? l]) => find.text((l ?? _en).socialContinueWithGoogle);
Finder _apple([L? l]) => find.text((l ?? _en).socialContinueWithApple);

Finder _nameField() => find.descendant(
  of: find.byType(AccountNameScreen),
  matching: find.byType(TextFormField),
);

Future<void> _tap(WidgetTester tester, Finder target) async {
  await tester.ensureVisible(target);
  await _settle(tester, 3);
  await tester.tap(target);
  await _settle(tester);
}

/// Guest Home, "Send a parcel": the account screen for posting a request.
Future<void> _openGate(WidgetTester tester) async {
  await tester.tap(_hero());
  await _settle(tester);
  expect(find.byType(AccountGateScreen), findsOneWidget);
}

void _expectFlowClosed() {
  for (final type in [
    AccountGateScreen,
    SignInScreen,
    SignUpScreen,
    AccountNameScreen,
  ]) {
    expect(find.byType(type, skipOffstage: false), findsNothing);
  }
}

/// The account moment completed: the form the guest asked for is open over
/// Home, and no account screen is left.
void _expectRequestFormOverHome(ProviderContainer container) {
  expect(container.read(sessionProvider), isA<SessionSignedIn>());
  expect(find.byType(RequestCreateScreen), findsOneWidget);
  expect(_at(container).path, '/requests/new');
  _expectFlowClosed();
}

void main() {
  group('which providers a build offers', () {
    ({bool google, bool apple}) offers(
      TargetPlatform platform, {
      bool isWeb = false,
      String server = 'web-client',
      String ios = 'ios-client',
      bool apple = true,
    }) => socialSignInOffers(
      platform: platform,
      isWeb: isWeb,
      googleServerClientId: server,
      googleIosClientId: ios,
      appleSignInEnabled: apple,
    );

    test('nothing without configuration, on any platform', () {
      for (final platform in TargetPlatform.values) {
        expect(offers(platform, server: '', ios: '', apple: false), (
          google: false,
          apple: false,
        ), reason: platform.name);
      }
    });

    test('Android: Google with the server client id; never Apple', () {
      expect(offers(TargetPlatform.android), (google: true, apple: false));
      expect(offers(TargetPlatform.android, server: ''), (
        google: false,
        apple: false,
      ));
    });

    test('iOS: Google needs both client ids; Apple needs its switch', () {
      expect(offers(TargetPlatform.iOS), (google: true, apple: true));
      expect(offers(TargetPlatform.iOS, ios: ''), (google: false, apple: true));
      expect(offers(TargetPlatform.iOS, server: ''), (
        google: false,
        apple: true,
      ));
      expect(offers(TargetPlatform.iOS, apple: false), (
        google: true,
        apple: false,
      ));
    });

    test('the web and desktops offer neither', () {
      expect(offers(TargetPlatform.android, isWeb: true), (
        google: false,
        apple: false,
      ));
      for (final platform in [
        TargetPlatform.macOS,
        TargetPlatform.windows,
        TargetPlatform.linux,
        TargetPlatform.fuchsia,
      ]) {
        expect(offers(platform), (
          google: false,
          apple: false,
        ), reason: platform.name);
      }
    });

    test('this build, with no defines, offers neither', () {
      final real = PlatformSocialSignIn();
      expect(real.offersGoogle, isFalse);
      expect(real.offersApple, isFalse);
    });
  });

  group('Apple\'s credential', () {
    AuthorizationCredentialAppleID authorization({
      String? given = 'Yacine',
      String? family = 'Belkacem',
      String? token = 'identity-token',
    }) => AuthorizationCredentialAppleID(
      userIdentifier: 'apple-user',
      givenName: given,
      familyName: family,
      authorizationCode: 'code',
      email: null,
      identityToken: token,
      state: null,
    );

    test('Apple is given the SHA-256 of the nonce the server gets', () async {
      final given = <String>[];
      final social = PlatformSocialSignIn(
        authorizeApple: (hashed) async {
          given.add(hashed);
          return authorization();
        },
      );

      final first = (await social.apple())!;
      final second = (await social.apple())!;

      expect(given.first, appleNonceHash(first.rawNonce));
      expect(given.first, matches(RegExp(r'^[0-9a-f]{64}$')));
      expect(first.rawNonce, matches(RegExp(r'^[A-Za-z0-9_-]{43}$')));
      expect(second.rawNonce, isNot(first.rawNonce), reason: 'one per try');
      expect(first.identityToken, 'identity-token');
      expect(first.fullName, 'Yacine Belkacem');
      expect(first.userIdentifier, 'apple-user');
    });

    test('a known hash: SHA-256 in lowercase hex', () {
      expect(
        appleNonceHash('abc'),
        'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad',
      );
    });

    test('cancelling answers null; any other refusal is a failure', () async {
      PlatformSocialSignIn refusing(Object error) =>
          PlatformSocialSignIn(authorizeApple: (_) async => throw error);

      expect(
        await refusing(
          const SignInWithAppleAuthorizationException(
            code: AuthorizationErrorCode.canceled,
            message: 'cancelled',
          ),
        ).apple(),
        isNull,
      );
      await expectLater(
        refusing(
          const SignInWithAppleAuthorizationException(
            code: AuthorizationErrorCode.failed,
            message: 'failed',
          ),
        ).apple(),
        throwsA(isA<SocialSignInFailure>()),
      );
      await expectLater(
        PlatformSocialSignIn(
          authorizeApple: (_) async => authorization(token: null),
        ).apple(),
        throwsA(isA<SocialSignInFailure>()),
      );
    });

    test('the name parts become one name the server accepts', () {
      expect(joinAppleName(' Yacine ', ' Belkacem '), 'Yacine Belkacem');
      expect(joinAppleName('Yacine', null), 'Yacine');
      expect(joinAppleName(null, ''), '');
      final long = joinAppleName('A' * 100, 'B' * 100);
      expect(long.runes.length, lessThanOrEqualTo(maxFullNameLength));
      expect(long, startsWith('${'A' * 100} B'));
    });

    testWidgets('the server gets the raw nonce and the name', (tester) async {
      final given = <String>[];
      final server = _Server();
      final platform = PlatformSocialSignIn(
        authorizeApple: (hashed) async {
          given.add(hashed);
          return authorization();
        },
      );
      await _boot(
        tester,
        server,
        social: _Delegating(FakeSocialSignIn(offersGoogle: false), platform),
      );

      await _openGate(tester);
      await _tap(tester, _apple());

      final body = server.posts('/api/auth/oauth/apple').single.body;
      expect(appleNonceHash(body['nonce'] as String), given.single);
      expect(body['identity_token'], 'identity-token');
      expect(body['full_name'], 'Yacine Belkacem');
      expect(body['preferred_language'], 'en');

      await _shutdown(tester);
    });
  });

  group('the buttons', () {
    testWidgets('are hidden when the build is not configured', (tester) async {
      final container = await _boot(tester, _Server());
      final router = _router(container);

      for (final location in [
        '/auth/continue?reason=post_request',
        '/auth/sign-in',
        '/auth/sign-up',
      ]) {
        router.push(location);
        await _settle(tester, 10);
        expect(_google(), findsNothing, reason: location);
        expect(_apple(), findsNothing, reason: location);
        expect(find.text(_en.socialOr), findsNothing, reason: location);
        await _systemBack(tester);
      }

      await _shutdown(tester);
    });

    testWidgets('show what the platform offers, Apple first', (tester) async {
      for (final social in [
        FakeSocialSignIn(),
        FakeSocialSignIn(offersApple: false),
      ]) {
        final container = await _boot(tester, _Server(), social: social);
        final router = _router(container);
        for (final location in [
          '/auth/continue?reason=post_request',
          '/auth/sign-in',
          '/auth/sign-up',
        ]) {
          router.push(location);
          await _settle(tester, 10);
          expect(_google(), findsOneWidget, reason: location);
          expect(
            _apple(),
            social.offersApple ? findsOneWidget : findsNothing,
            reason: location,
          );
          if (social.offersApple) {
            expect(
              tester.getTopLeft(_apple()).dy,
              lessThan(tester.getTopLeft(_google()).dy),
            );
          }
          // The email form follows on sign-in and sign-up, after an "or".
          expect(
            find.text(_en.socialOr),
            location.contains('continue') ? findsNothing : findsOneWidget,
            reason: location,
          );
          await _systemBack(tester);
        }
        await _shutdown(tester);
      }
    });
  });

  group('signing in', () {
    testWidgets('Google on sign-in on its own: signed in, then Home', (
      tester,
    ) async {
      final server = _Server();
      final social = FakeSocialSignIn();
      final container = await _boot(tester, server, social: social);
      _router(container).go('/auth/sign-in');
      await _settle(tester);

      await _tap(tester, _google());

      expect(container.read(sessionProvider), isA<SessionSignedIn>());
      expect(_at(container).path, '/home');
      expect(server.posts('/api/auth/oauth/google').single.body, {
        'id_token': 'google-id-token',
        'preferred_language': 'en',
      });
      expect(find.byType(AccountNameScreen), findsNothing);

      await _shutdown(tester);
    });

    testWidgets('Google on the account screen: the form opens over Home', (
      tester,
    ) async {
      final server = _Server();
      final container = await _boot(tester, server, social: FakeSocialSignIn());

      await _openGate(tester);
      await _tap(tester, _google());

      _expectRequestFormOverHome(container);
      expect(server.posts('/api/auth/oauth/google'), hasLength(1));

      await _systemBack(tester);
      expect(_at(container).path, '/home');
      expect(find.byType(HomeScreen), findsOneWidget);

      await _shutdown(tester);
    });

    testWidgets('Apple on sign-in inside the account moment: the form opens', (
      tester,
    ) async {
      final server = _Server();
      final container = await _boot(tester, server, social: FakeSocialSignIn());

      await _openGate(tester);
      await _tap(tester, find.text(_en.accountGateHaveAccount));
      expect(find.byType(SignInScreen), findsOneWidget);
      await _tap(tester, _apple());

      _expectRequestFormOverHome(container);
      final body = server.posts('/api/auth/oauth/apple').single.body;
      expect(body['full_name'], 'Yacine Belkacem');
      expect(body['nonce'], 'raw-nonce-0123456789abcdef');

      await _shutdown(tester);
    });

    testWidgets('Google on sign-up inside the account moment: the form opens', (
      tester,
    ) async {
      final container = await _boot(
        tester,
        _Server(),
        social: FakeSocialSignIn(offersApple: false),
      );

      await _openGate(tester);
      await _tap(tester, find.text(_en.accountGateEmail));
      expect(find.byType(SignUpScreen), findsOneWidget);
      await _tap(tester, _google());

      _expectRequestFormOverHome(container);

      await _shutdown(tester);
    });

    testWidgets('cancelling does nothing and says nothing', (tester) async {
      final server = _Server();
      final social = FakeSocialSignIn()
        ..googleAnswers[0] = (() => null)
        ..appleAnswers[0] = (() => null);
      final container = await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _google());
      await _tap(tester, _apple());

      expect(social.googleCalls, 1);
      expect(social.appleCalls, 1);
      expect(server.posts('/api/auth/oauth/google'), isEmpty);
      expect(server.posts('/api/auth/oauth/apple'), isEmpty);
      expect(find.byType(AccountGateScreen), findsOneWidget);
      expect(find.byType(InfoNotice), findsNothing);
      expect(container.read(sessionProvider), isA<SessionSignedOut>());

      await _shutdown(tester);
    });

    final failures =
        <
          ({
            String what,
            SocialProvider provider,
            FakeResponse? response,
            String Function(L) copy,
          })
        >[
          (
            what: 'Google could not give a credential',
            provider: SocialProvider.google,
            response: null,
            copy: (l) => l.socialGoogleFailed,
          ),
          (
            what: 'the server refused the Google token',
            provider: SocialProvider.google,
            response: const FakeResponse(401, {
              'detail': 'Invalid Google token.',
            }),
            copy: (l) => l.socialGoogleFailed,
          ),
          (
            what: 'the server refused the Apple token',
            provider: SocialProvider.apple,
            response: const FakeResponse(401, {
              'detail': 'Invalid Apple token.',
            }),
            copy: (l) => l.socialAppleFailed,
          ),
          (
            what: 'a disabled account, through Google',
            provider: SocialProvider.google,
            response: const FakeResponse(403, {
              'code': 'account_disabled',
              'detail': 'This account is disabled.',
            }),
            copy: (l) => l.socialAccountDisabled,
          ),
          (
            what: 'a disabled account, through Apple',
            provider: SocialProvider.apple,
            response: const FakeResponse(403, {
              'code': 'account_disabled',
              'detail': 'This account is disabled.',
            }),
            copy: (l) => l.socialAccountDisabled,
          ),
          (
            what: 'the server does not offer Google yet',
            provider: SocialProvider.google,
            response: const FakeResponse(503, {
              'code': 'google_sign_in_unavailable',
              'detail': 'Google sign-in is not configured.',
            }),
            copy: (l) => l.socialGoogleUnavailable,
          ),
          (
            what: 'the server does not offer Apple yet',
            provider: SocialProvider.apple,
            response: const FakeResponse(503, {
              'code': 'apple_sign_in_unavailable',
              'detail': 'Apple sign-in is not configured.',
            }),
            copy: (l) => l.socialAppleUnavailable,
          ),
          (
            what: 'the server failed',
            provider: SocialProvider.google,
            response: const FakeResponse(500, {'detail': 'boom'}),
            copy: (l) => l.stateServerErrorBody,
          ),
        ];

    for (final failure in failures) {
      testWidgets('${failure.what}: its copy, and nobody is signed in', (
        tester,
      ) async {
        final server = _Server();
        final social = FakeSocialSignIn();
        final google = failure.provider == SocialProvider.google;
        final response = failure.response;
        if (response == null) {
          social.googleAnswers[0] = () => throw const SocialSignInFailure(
            SocialProvider.google,
            'clientConfigurationError',
          );
        } else {
          (google ? server.google : server.apple)[0] = response;
        }
        final container = await _boot(tester, server, social: social);

        await _openGate(tester);
        await _tap(tester, google ? _google() : _apple());

        expect(find.text(failure.copy(_en)), findsOneWidget);
        expect(find.byType(AccountGateScreen), findsOneWidget);
        expect(container.read(sessionProvider), isA<SessionSignedOut>());
        // The buttons are usable again.
        expect(
          tester
              .widget<ButtonStyleButton>(
                find.ancestor(
                  of: google ? _google() : _apple(),
                  matching: find.byWidgetPredicate(
                    (w) => w is ButtonStyleButton,
                  ),
                ),
              )
              .onPressed,
          isNotNull,
        );

        await _shutdown(tester);
      });
    }
  });

  group('Apple\'s name is kept until a sign-in succeeds', () {
    testWidgets('a retry after 503 resends it, without asking Apple again', (
      tester,
    ) async {
      final server = _Server()
        ..apple.insert(
          0,
          const FakeResponse(503, {'code': 'apple_sign_in_unavailable'}),
        );
      final social = FakeSocialSignIn();
      final container = await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _apple());
      expect(find.text(_en.socialAppleUnavailable), findsOneWidget);
      await _tap(tester, _apple());

      _expectRequestFormOverHome(container);
      expect(social.appleCalls, 1);
      final [first, second] = server.posts('/api/auth/oauth/apple');
      expect(first.body, second.body);
      expect(second.body['full_name'], 'Yacine Belkacem');

      await _shutdown(tester);
    });

    testWidgets('a refused token: Apple again, with the first name', (
      tester,
    ) async {
      final server = _Server()
        ..apple.insert(0, const FakeResponse(401, {'detail': 'Bad token.'}));
      final social = FakeSocialSignIn()
        ..appleAnswers.replaceRange(0, 1, [
          appleCredential,
          // Apple gives the name only on the first authorization.
          () => appleCredential(
            fullName: '',
            identityToken: fakeJwt(
              expires: DateTime.now().add(const Duration(minutes: 10)),
              subject: 'second',
            ),
            rawNonce: 'second-nonce-0123456789',
          ),
        ]);
      final container = await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _apple());
      expect(find.text(_en.socialAppleFailed), findsOneWidget);
      await _tap(tester, _apple());

      _expectRequestFormOverHome(container);
      expect(social.appleCalls, 2);
      final [first, second] = server.posts('/api/auth/oauth/apple');
      expect(
        second.body['identity_token'],
        isNot(first.body['identity_token']),
      );
      expect(second.body['nonce'], 'second-nonce-0123456789');
      expect(second.body['full_name'], 'Yacine Belkacem');

      await _shutdown(tester);
    });

    testWidgets('a token about to expire is not reused; the name still goes', (
      tester,
    ) async {
      final server = _Server()
        ..apple.insert(0, const FakeResponse(503, {'detail': 'Unavailable.'}));
      final social = FakeSocialSignIn()
        ..appleAnswers.replaceRange(0, 1, [
          () => appleCredential(
            identityToken: fakeJwt(
              expires: DateTime.now().add(const Duration(seconds: 20)),
            ),
          ),
          () => appleCredential(fullName: ''),
        ]);
      final container = await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _apple());
      await _tap(tester, _apple());

      _expectRequestFormOverHome(container);
      expect(social.appleCalls, 2);
      expect(
        server.posts('/api/auth/oauth/apple').last.body['full_name'],
        'Yacine Belkacem',
      );

      await _shutdown(tester);
    });

    testWidgets('another Apple ID does not get the first one\'s name', (
      tester,
    ) async {
      final server = _Server()
        ..apple.insert(0, const FakeResponse(401, {'detail': 'Bad token.'}));
      final social = FakeSocialSignIn()
        ..appleAnswers.replaceRange(0, 1, [
          appleCredential,
          () => appleCredential(fullName: '', userIdentifier: 'someone-else'),
        ]);
      await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _apple());
      await _tap(tester, _apple());

      final body = server.posts('/api/auth/oauth/apple').last.body;
      expect(body.containsKey('full_name'), isFalse);

      await _shutdown(tester);
    });
  });

  group('the name step', () {
    testWidgets('only for an account without a name; validation; then the '
        'action goes ahead', (tester) async {
      final server = _Server(name: '');
      final social = FakeSocialSignIn()
        ..appleAnswers[0] = () => appleCredential(fullName: '');
      final container = await _boot(tester, server, social: social);

      await _openGate(tester);
      await _tap(tester, _apple());

      expect(find.byType(AccountNameScreen), findsOneWidget);
      expect(find.text(_en.accountNameTitle), findsOneWidget);
      expect(find.byType(RequestCreateScreen), findsNothing);

      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));
      expect(find.text(_en.validationRequired), findsOneWidget);

      await tester.enterText(_nameField(), '   ');
      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));
      expect(find.text(_en.validationRequired), findsOneWidget);

      await tester.enterText(_nameField(), 'y' * 121);
      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));
      expect(find.text(_en.validationTooLong(120)), findsOneWidget);
      expect(server.patches, isEmpty);

      await tester.enterText(_nameField(), '  Yacine Belkacem ');
      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));

      expect(server.patches.single.body, {'full_name': 'Yacine Belkacem'});
      _expectRequestFormOverHome(container);
      expect(container.read(accountProvider)?.fullName, 'Yacine Belkacem');

      // Back on Home, nobody is asked again.
      await _systemBack(tester);
      expect(_at(container).path, '/home');
      expect(find.byType(AccountNameScreen), findsNothing);

      await _shutdown(tester);
    });

    test('the name check counts what the server counts', () {
      expect(validateAccountName(_en, null), _en.validationRequired);
      expect(validateAccountName(_en, ' \n '), _en.validationRequired);
      expect(validateAccountName(_en, 'y' * 120), isNull);
      expect(validateAccountName(_en, ' ${'y' * 120} '), isNull);
      expect(validateAccountName(_en, 'y' * 121), _en.validationTooLong(120));
      expect(validateAccountName(_ar, ''), _ar.validationRequired);
    });

    testWidgets('"name already set" is a success: the account is re-read', (
      tester,
    ) async {
      final server = _Server(name: '')..nameArrivesElsewhere = 'Yacine B.';
      final container = await _boot(tester, server, social: FakeSocialSignIn());

      await _openGate(tester);
      await _tap(tester, _google());
      expect(find.byType(AccountNameScreen), findsOneWidget);

      await tester.enterText(_nameField(), 'Yacine');
      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));

      expect(server.patches, hasLength(1));
      _expectRequestFormOverHome(container);
      expect(container.read(accountProvider)?.fullName, 'Yacine B.');

      await _shutdown(tester);
    });

    testWidgets('closing it lets the action go ahead; not asked again in '
        'this launch', (tester) async {
      final server = _Server(name: '');
      final container = await _boot(tester, server, social: FakeSocialSignIn());

      await _openGate(tester);
      await _tap(tester, _google());
      expect(find.byType(AccountNameScreen), findsOneWidget);

      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);

      _expectRequestFormOverHome(container);
      expect(server.patches, isEmpty);
      await _systemBack(tester);
      expect(_at(container).path, '/home');
      expect(find.byType(AccountNameScreen), findsNothing);

      await _shutdown(tester);
    });

    testWidgets('a sign-in on its own: Home asks once', (tester) async {
      final server = _Server(name: '');
      final container = await _boot(tester, server, social: FakeSocialSignIn());
      _router(container).go('/auth/sign-in');
      await _settle(tester);

      await _tap(tester, _google());

      expect(find.byType(AccountNameScreen), findsOneWidget);
      await tester.enterText(_nameField(), 'Yacine');
      await _tap(tester, find.widgetWithText(AppButton, _en.actionContinue));

      expect(find.byType(AccountNameScreen), findsNothing);
      expect(_at(container).path, '/home');
      expect(container.read(accountProvider)?.fullName, 'Yacine');

      await _shutdown(tester);
    });

    testWidgets('each launch with the name still empty asks again, on Home', (
      tester,
    ) async {
      final server = _Server(name: '');

      var container = await _boot(tester, server, store: _Store());
      expect(find.byType(AccountNameScreen), findsOneWidget);
      await tester.tap(find.byType(PaperCloseButton));
      await _settle(tester);
      expect(_at(container).path, '/home');
      expect(find.byType(AccountNameScreen), findsNothing);

      // The rest of this launch: Home again, and no second ask.
      _router(container).go('/profile');
      await _settle(tester);
      _router(container).go('/home');
      await _settle(tester);
      expect(find.byType(AccountNameScreen), findsNothing);
      await _shutdown(tester);

      container = await _boot(tester, server, store: _Store());
      expect(find.byType(AccountNameScreen), findsOneWidget);
      await _shutdown(tester);

      // Named: no ask.
      server.name = 'Yacine';
      container = await _boot(tester, server, store: _Store());
      expect(_at(container).path, '/home');
      expect(find.byType(AccountNameScreen), findsNothing);
      await _shutdown(tester);
    });
  });

  group('the changed screens fit', () {
    const small = Size(320, 640);

    void iPhoneArabicAt16x(WidgetTester tester) {
      tester.view.padding = const FakeViewPadding(top: 47, bottom: 34);
      tester.view.viewPadding = const FakeViewPadding(top: 47, bottom: 34);
      tester.platformDispatcher.textScaleFactorTestValue = 1.6;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
    }

    Future<void> reach(WidgetTester tester, Finder target, Type screen) async {
      await tester.scrollUntilVisible(
        target,
        200,
        scrollable: find
            .descendant(
              of: find.byType(screen),
              matching: find.byType(Scrollable),
            )
            .first,
      );
      await _settle(tester, 5);
    }

    testWidgets('sign-in, sign-up and the account screen with both buttons, '
        'at 320 px, 1.6x text, in Arabic', (tester) async {
      iPhoneArabicAt16x(tester);
      final container = await _boot(
        tester,
        _Server(),
        social: FakeSocialSignIn(),
        store: _guest(locale: 'ar'),
        size: small,
      );
      final router = _router(container);

      for (final (location, screen, last) in [
        (
          '/auth/continue?reason=post_request',
          AccountGateScreen,
          find.widgetWithText(AppButton, _ar.accountGateEmail),
        ),
        ('/auth/sign-in', SignInScreen, find.text(_ar.authForgotPassword)),
        ('/auth/sign-up', SignUpScreen, find.text(_ar.authTermsNotice)),
      ]) {
        router.push(location);
        await _settle(tester, 10);
        expect(tester.takeException(), isNull, reason: location);
        expect(
          Directionality.of(tester.element(find.byType(screen))),
          TextDirection.rtl,
        );
        for (final target in [_apple(_ar), _google(_ar), last]) {
          await reach(tester, target, screen);
          expect(tester.takeException(), isNull, reason: location);
          expect(
            tester.getBottomLeft(target).dy,
            lessThanOrEqualTo(small.height - 34),
            reason: '$location $target',
          );
          expect(tester.getTopLeft(target).dy, greaterThanOrEqualTo(47));
        }
        await _systemBack(tester);
      }

      await _shutdown(tester);
    });

    testWidgets('the name step, with its error, at 320 px, 1.6x text, in '
        'Arabic', (tester) async {
      iPhoneArabicAt16x(tester);
      final container = await _boot(
        tester,
        _Server(name: ''),
        store: _Store(locale: 'ar'),
        size: small,
      );
      expect(find.byType(AccountNameScreen), findsOneWidget);
      expect(_at(container).path, '/auth/name');

      final submit = find.widgetWithText(AppButton, _ar.actionContinue);
      await tester.tap(submit);
      await _settle(tester);
      expect(tester.takeException(), isNull);
      expect(find.text(_ar.validationRequired), findsOneWidget);
      expect(
        tester.getBottomLeft(submit).dy,
        lessThanOrEqualTo(small.height - 34),
      );
      await reach(tester, find.text(_ar.accountNameTitle), AccountNameScreen);
      expect(tester.takeException(), isNull);

      await _shutdown(tester);
    });
  });
}

/// The fake's switches and counts, with Apple answered by the real
/// [PlatformSocialSignIn] over a stubbed Apple.
class _Delegating implements SocialSignIn {
  _Delegating(this._fake, this._platform);

  final FakeSocialSignIn _fake;
  final PlatformSocialSignIn _platform;

  @override
  bool get offersGoogle => _fake.offersGoogle;

  @override
  bool get offersApple => _fake.offersApple;

  @override
  Future<GoogleCredential?> google() => _fake.google();

  @override
  Future<AppleCredential?> apple() => _platform.apple();
}
