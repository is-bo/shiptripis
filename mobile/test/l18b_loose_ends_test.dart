/// L18B: the app half of the loose ends.
///
/// The server's own-rating figure, a welcome caption with no number, one
/// support action that is absent without an address, and the one handler for
/// "confirm your email first" with a working "send the code again".
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/design/components/codes.dart';
import 'package:shiptrip/features/auth/email_gate.dart';
import 'package:shiptrip/features/auth/forgot_password_screen.dart';
import 'package:shiptrip/features/auth/verify_email_screen.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/profile/profile_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/discovery_harness.dart';
import 'support/fake_api.dart';
import 'support/harness.dart';

void _stubMail(WidgetTester tester, List<String> opened) {
  tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
    const MethodChannel('plugins.flutter.io/url_launcher'),
    (call) async {
      if (call.method == 'launch') {
        opened.add((call.arguments as Map)['url'] as String);
      }
      return true;
    },
  );
  addTearDown(
    () => tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      const MethodChannel('plugins.flutter.io/url_launcher'),
      null,
    ),
  );
}

L _l(WidgetTester tester) => L.of(tester.element(find.byType(Scaffold).first));

Future<void> _pumpProfile(
  WidgetTester tester,
  FakeBackend backend, {
  Locale locale = const Locale('en'),
}) async {
  await pumpDiscovery(tester, const ProfileScreen(), backend, locale: locale);
  await tester.pumpAndSettle();
}

void main() {
  group('own rating comes from the server', () {
    testWidgets('shows the summary figure under "Rating", never "Recent"', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/users/me/ratings/summary',
          const FakeResponse(200, {
            'state': 'rated',
            'average': 4.5,
            'count': 3,
          }),
        );
      await _pumpProfile(tester, backend);
      final l = _l(tester);
      expect(find.text('4.5 ★'), findsOneWidget);
      expect(find.text(l.profileRating.toUpperCase()), findsOneWidget);
      expect(find.textContaining('recent', findRichText: true), findsNothing);
      expect(find.textContaining('RECENT'), findsNothing);
      expect(backend.to('GET', '/api/users/me/ratings/summary'), hasLength(1));
      // The phone fetches no list to average.
      expect(backend.to('GET', '/api/users/me/ratings'), isEmpty);
    });

    testWidgets('a member with nothing counted is told so', (tester) async {
      await _pumpProfile(tester, discoveryBackend());
      expect(find.text(_l(tester).discoveryNoRatingsYet), findsOneWidget);
    });

    test('the label says "Rating" in all three languages', () {
      expect(lookupL(const Locale('en')).profileRating, 'Rating');
      expect(lookupL(const Locale('fr')).profileRating, 'Note');
      expect(lookupL(const Locale('ar')).profileRating, 'التقييم');
    });
  });

  test('the welcome caption names no number in any language', () {
    for (final code in ['en', 'fr', 'ar']) {
      final caption = lookupL(Locale(code)).benefitsHandoverCaption;
      expect(RegExp(r'[0-9٠-٩]').hasMatch(caption), isFalse, reason: code);
    }
  });

  group('contact support', () {
    testWidgets('Profile offers it only when the server has an address', (
      tester,
    ) async {
      final opened = <String>[];
      _stubMail(tester, opened);
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/support',
          const FakeResponse(200, {'email': 'help@example.test'}),
        );
      await _pumpProfile(tester, backend);
      final l = _l(tester);
      await tester.scrollUntilVisible(find.text(l.actionContactSupport), 200);
      await tester.tap(find.text(l.actionContactSupport));
      await tester.pumpAndSettle();
      expect(opened, hasLength(1));
      expect(opened.single, startsWith('mailto:help@example.test?subject='));
    });

    testWidgets('with no address there is no action at all', (tester) async {
      await _pumpProfile(tester, discoveryBackend());
      expect(find.text(_l(tester).actionContactSupport), findsNothing);
    });

    testWidgets('from a delivery the tracking number is in the subject', (
      tester,
    ) async {
      final opened = <String>[];
      _stubMail(tester, opened);
      final backend = discoveryBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/deals/7',
          FakeResponse(200, {
            ...dealFixture(),
            'match_id': 5,
            'tracking_number': 'WSL-3NZ5FHHQ',
          }),
        )
        ..on(
          'GET',
          '/api/deals/7/problems',
          const FakeResponse(200, {
            'deal_id': 7,
            'tracking_number': 'WSL-3NZ5FHHQ',
            'viewer_role': 'sender',
            'no_show_kind': 'traveler_no_show',
            'can_report_no_show': false,
            'no_show_reason': 'pickup_time_not_reached',
            'no_show_available_at': null,
            'reportable_kinds': ['other'],
            'results': <Object>[],
          }),
        )
        ..on(
          'GET',
          '/api/deals/7/schedule-change',
          const FakeResponse(200, {
            'deal_id': 7,
            'tracking_number': null,
            'change': null,
          }),
        )
        ..on(
          'GET',
          '/api/support',
          const FakeResponse(200, {'email': 'help@example.test'}),
        );
      await pumpDiscovery(
        tester,
        const DealScreen(dealId: 7),
        backend,
        device: DeviceProfile.android,
      );
      await tester.pumpAndSettle();
      final l = _l(tester);
      final button = find.text(l.actionContactSupport);
      await tester.scrollUntilVisible(button, 200);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(opened.single, contains('WSL-3NZ5FHHQ'));
    });
  });

  group('email not confirmed', () {
    testWidgets('Profile offers "Verify email" while the flag is false', (
      tester,
    ) async {
      final backend = discoveryBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, {...meFixture(), 'is_email_verified': false}),
        );
      await _pumpProfile(tester, backend);
      expect(find.text(_l(tester).profileVerifyEmail), findsOneWidget);
    });

    testWidgets('a confirmed member is not offered it', (tester) async {
      await _pumpProfile(tester, discoveryBackend());
      expect(find.text(_l(tester).profileVerifyEmail), findsNothing);
    });

    testWidgets('the refusal opens verify-email, resend works, and the host '
        'screen is still there afterwards', (tester) async {
      final backend = discoveryBackend()
        ..on('POST', '/api/auth/verify-email/resend', const FakeResponse(204))
        ..on('POST', '/api/auth/verify-email', const FakeResponse(204))
        ..on(
          'POST',
          '/api/parcels/delivery/v1',
          const FakeResponse(403, {
            'code': 'email_verification_required',
            'detail': 'Confirm your email address first.',
          }),
        );
      var handled = false;
      var confirmed = false;
      await pumpDiscovery(
        tester,
        Consumer(
          builder: (context, ref, _) => Scaffold(
            body: TextButton(
              onPressed: () async {
                try {
                  await ref
                      .read(apiClientProvider)
                      .postObject('/api/parcels/delivery/v1', body: {});
                } on ApiException catch (error) {
                  handled = await handleEmailVerificationRequired(
                    context,
                    error,
                    onConfirmed: () => confirmed = true,
                  );
                }
              },
              child: const Text('post'),
            ),
          ),
        ),
        backend,
        extraRoutes: [
          GoRoute(
            path: '/auth/verify-email',
            name: Routes.verifyEmail,
            builder: (_, _) => const VerifyEmailScreen(email: ''),
          ),
        ],
      );
      await tester.tap(find.text('post'));
      await tester.pumpAndSettle();
      expect(find.byType(VerifyEmailScreen), findsOneWidget);
      final l = L.of(tester.element(find.byType(VerifyEmailScreen)));

      await tester.tap(find.text(l.authVerifyResend));
      await tester.pumpAndSettle();
      expect(backend.to('POST', '/api/auth/verify-email/resend'), hasLength(1));
      expect(find.text(l.authVerifyResent), findsOneWidget);
      // Let the notice leave the footer before the next tap.
      await tester.pump(const Duration(seconds: 8));
      await tester.pumpAndSettle();

      await tester.enterText(find.byType(TextField).first, '123456');
      await tester.tap(find.text(l.actionConfirm));
      await tester.pumpAndSettle();
      expect(find.byType(VerifyEmailScreen), findsNothing);
      expect(handled, isTrue);
      expect(confirmed, isTrue);
      // The address on the account was used, not an empty route parameter.
      expect(
        backend.to('POST', '/api/auth/verify-email').single.body['email'],
        'sender@example.com',
      );
    });

    test('any other refusal is not the email gate', () {
      expect(
        isEmailVerificationRequired(
          ApiException(
            kind: ApiFailureKind.forbidden,
            code: ApiErrorCode.notAuthorized,
          ),
        ),
        isFalse,
      );
    });
  });

  testWidgets('after a password reset the app ends on sign-in', (tester) async {
    final backend = discoveryBackend()
      ..on('POST', '/api/auth/password/reset/request', const FakeResponse(202))
      ..on('POST', '/api/auth/password/reset/confirm', const FakeResponse(204));
    await pumpApp(
      tester,
      const ForgotPasswordScreen(initialEmail: 'amine@example.test'),
      container: discoveryContainer(backend),
      routed: true,
      extraRoutes: [marker(Routes.signIn, '/auth/sign-in')],
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(ForgotPasswordScreen)));
    await tester.tap(find.text(l.authSendCode));
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(
        of: find.byType(CodeEntryField),
        matching: find.byType(TextField),
      ),
      '123456',
    );
    await tester.enterText(find.byType(TextFormField).last, 'new-password-123');
    await tester.tap(find.text(l.actionConfirm));
    await tester.pumpAndSettle();
    expect(find.byType(ForgotPasswordScreen), findsNothing);
    expect(find.textContaining('at ${Routes.signIn}'), findsOneWidget);
  });
}
