/// Focused J9.3 regressions: private Deal fallback and local validation copy.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:shiptrip/app/router.dart';
import 'package:shiptrip/core/api/api_exception.dart';
import 'package:shiptrip/core/api/error_codes.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/codes.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/components/status.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/canonical_place.dart';
import 'package:shiptrip/features/auth/verify_email_screen.dart';
import 'package:shiptrip/features/auth/forgot_password_screen.dart';
import 'package:shiptrip/features/deals/deal_screen.dart';
import 'package:shiptrip/features/journeys/journey_route_draft.dart';
import 'package:shiptrip/features/profile/dzd_setup_screen.dart';
import 'package:shiptrip/features/requests/request_create_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

class _FixedSession extends SessionController {
  _FixedSession(this._account);

  final Account _account;

  @override
  SessionState build() => SessionSignedIn(_account);
}

ProviderContainer _dealContainer(FakeBackend backend, {int accountId = 42}) {
  final tokens = FakeTokenStore();
  final account = Account.fromJson({...meFixture(), 'id': accountId});
  return ProviderContainer(
    overrides: [
      tokenStoreProvider.overrideWithValue(tokens),
      apiClientProvider.overrideWithValue(apiClientFor(backend, tokens)),
      sessionProvider.overrideWith(() => _FixedSession(account)),
    ],
  );
}

CanonicalPlace _place(int id, String name) => CanonicalPlace.fromJson({
  'id': id,
  'name': name,
  'display_label': name,
  'place_type': 'locality',
  'country_code': 'DZ',
  'matching_locality_id': id,
  'matching_locality_name': name,
});

const RouteCopy _routeCopy = (
  departRequired: 'depart-required',
  departNotAfterPrevious: 'depart-order',
  departBeforePreviousArrival: 'depart-before-arrival',
  arriveRequired: 'arrive-required',
  arriveBeforeDepart: 'arrive-order',
  capacityInvalid: 'capacity-invalid',
  volumeInvalid: 'volume',
  parcelsInvalid: 'parcels',
  windowIncomplete: 'window-incomplete',
  windowOrder: 'window-order',
  windowOutside: 'window-outside',
  required: 'required',
);

void main() {
  group('MOB-13 Deal unavailable', () {
    for (final accountId in [42, 99]) {
      testWidgets('legitimate participant $accountId sees normal Deal', (
        tester,
      ) async {
        final backend = FakeBackend()
          ..on('GET', '/api/deals/7', FakeResponse(200, dealFixture()));
        await pumpRouted(
          tester,
          const DealScreen(dealId: 7),
          container: _dealContainer(backend, accountId: accountId),
        );
        await tester.pumpAndSettle();

        expect(find.text('Delivery unavailable'), findsNothing);
        expect(find.byType(StatusPill), findsWidgets);
      });
    }

    for (final locale in const ['en', 'fr', 'ar']) {
      testWidgets('unrelated account gets private $locale recovery', (
        tester,
      ) async {
        final privateDeal = {
          ...dealFixture(),
          'sender_id': 98,
          'traveler_id': 99,
          'match_id': 77,
        };
        final backend = FakeBackend()
          ..on('GET', '/api/deals/7', FakeResponse(200, privateDeal));
        final semantics = tester.ensureSemantics();
        await pumpApp(
          tester,
          const DealScreen(dealId: 7),
          locale: Locale(locale),
          container: _dealContainer(backend),
          routed: true,
          extraRoutes: [
            GoRoute(
              path: '/home',
              name: Routes.home,
              builder: (_, _) => const Scaffold(body: Text('Safe home')),
            ),
          ],
        );
        await tester.pumpAndSettle();
        final l = L.of(tester.element(find.byType(DealScreen)));

        expect(find.text(l.dealUnavailableTitle), findsOneWidget);
        expect(find.text(l.dealUnavailableBody), findsOneWidget);
        expect(find.text(l.timelineTitle), findsNothing);
        expect(find.text(l.dealOpenChat), findsNothing);
        expect(
          find.byWidgetPredicate(
            (widget) =>
                widget is Semantics && widget.properties.liveRegion == true,
          ),
          findsOneWidget,
        );
        expect(find.text(l.navHome), findsOneWidget);
        await tester.tap(find.text(l.navHome));
        await tester.pumpAndSettle();
        expect(find.text('Safe home'), findsOneWidget);
        semantics.dispose();
      });
    }

    for (final status in [403, 404]) {
      testWidgets(
        'stale/private deep link $status has same safe state and Back',
        (tester) async {
          final backend = FakeBackend()
            ..on(
              'GET',
              '/api/deals/7',
              FakeResponse(status, {'detail': 'secret'}),
            );
          await pumpRouted(
            tester,
            const DealScreen(dealId: 7),
            container: _dealContainer(backend),
          );
          await tester.pumpAndSettle();
          final l = L.of(tester.element(find.byType(DealScreen)));
          expect(find.text(l.dealUnavailableTitle), findsOneWidget);
          expect(find.text('secret'), findsNothing);
          await tester.tap(find.text(l.actionBack).last);
          await tester.pumpAndSettle();
          expect(find.byType(DealScreen), findsNothing);
        },
      );
    }
  });

  group('MOB-04 quote error localization', () {
    for (final locale in const ['en', 'fr', 'ar']) {
      testWidgets('$locale maps known and unknown errors, never server prose', (
        tester,
      ) async {
        String? known;
        String? unknown;
        String? unknownValidation;
        await pumpApp(
          tester,
          Builder(
            builder: (context) {
              known = requestPricingFailureMessage(
                context,
                ApiException(
                  kind: ApiFailureKind.validation,
                  code: ApiErrorCode.rewardBelowMinimum,
                  serverDetail: 'RAW INTERNAL ENGLISH',
                ),
              );
              unknown = requestPricingFailureMessage(
                context,
                ApiException(
                  kind: ApiFailureKind.server,
                  code: ApiErrorCode.unknown,
                  serverDetail: 'RAW INTERNAL ENGLISH',
                ),
              );
              unknownValidation = requestPricingFailureMessage(
                context,
                ApiException(
                  kind: ApiFailureKind.validation,
                  code: ApiErrorCode.unknown,
                  serverDetail: 'RAW INTERNAL ENGLISH',
                ),
              );
              final l = L.of(context);
              expect(known, l.staleRewardBelowMinimum);
              expect(unknown, l.stateServerErrorBody);
              expect(unknownValidation, l.stateUnexpectedBody);
              return Text('$known $unknown $unknownValidation');
            },
          ),
          locale: Locale(locale),
        );
        expect(known, isNot(contains('RAW INTERNAL')));
        expect(unknown, isNot(contains('RAW INTERNAL')));
        expect(unknownValidation, isNot(contains('RAW INTERNAL')));
      });
    }
  });

  test('MOB-10 client enforces server 0.01–20,000 kg leg range', () {
    final draft = JourneyRouteDraft()
      ..setOrigin(_place(1, 'Jijel'))
      ..setDestination(_place(2, 'Algiers'));
    addTearDown(draft.dispose);
    final now = DateTime.utc(2030);
    draft.setSegmentDeparture(0, now.add(const Duration(days: 1)));
    draft.setSegmentArrival(0, now.add(const Duration(days: 1, hours: 2)));
    final capacity = draft.segments.first.capacity;
    for (final valid in ['0.01', '200.00', '20000.00']) {
      capacity.text = valid;
      expect(draft.issuesFor(0, _routeCopy, now: now).capacity, isNull);
    }
    for (final invalid in ['0', '0.005', '20000.001', '20000.01', '50000']) {
      capacity.text = invalid;
      expect(
        draft.issuesFor(0, _routeCopy, now: now).capacity,
        'capacity-invalid',
      );
    }
  });

  for (final locale in const ['en', 'fr', 'ar']) {
    testWidgets('MOB-11 DZD empty, malformed and valid in $locale', (
      tester,
    ) async {
      await pumpApp(tester, const DzdSetupScreen(), locale: Locale(locale));
      await tester.pumpAndSettle();
      final l = L.of(tester.element(find.byType(DzdSetupScreen)));
      final inputs = find.byType(TextFormField);
      final form = tester.state<FormState>(find.byType(Form));

      await tester.enterText(inputs.at(0), 'Amine');
      await tester.enterText(inputs.at(1), 'Benali');
      form.validate();
      await tester.pump();
      expect(find.text(l.validationRequired), findsWidgets);

      await tester.enterText(inputs.at(2), '123456');
      await tester.enterText(inputs.at(3), '1');
      await tester.enterText(inputs.at(4), '123');
      form.validate();
      await tester.pump();
      expect(find.text(l.validationCcpKeyDigits), findsOneWidget);
      expect(find.text(l.validationRipDigits), findsOneWidget);

      await tester.enterText(inputs.at(3), '12');
      await tester.enterText(inputs.at(4), '12345678901234567890');
      expect(form.validate(), isTrue);
    });

    testWidgets('MOB-12 OTP validator and verify screen copy in $locale', (
      tester,
    ) async {
      await pumpRouted(
        tester,
        const VerifyEmailScreen(email: 'amine@example.test'),
        locale: Locale(locale),
      );
      final context = tester.element(find.byType(VerifyEmailScreen));
      final l = L.of(context);
      final validator = Validators.of(context);
      expect(validator.sixDigitCode(''), l.validationRequired);
      expect(validator.sixDigitCode('123'), l.validationCodeSixDigits);
      expect(validator.sixDigitCode('1234567'), l.validationCodeSixDigits);
      expect(validator.sixDigitCode('123456'), isNull);
      await tester.enterText(find.byType(TextField).first, '123');
      await tester.tap(find.text(l.actionConfirm));
      await tester.pump();
      expect(find.text(l.validationCodeSixDigits), findsOneWidget);
    });
  }

  testWidgets('MOB-12 password reset uses malformed-code copy', (tester) async {
    final backend = FakeBackend()
      ..on('POST', '/api/auth/password/reset/request', const FakeResponse(202));
    await pumpRouted(
      tester,
      const ForgotPasswordScreen(initialEmail: 'amine@example.test'),
      container: containerFor(backend),
    );
    await tester.pumpAndSettle();
    final l = L.of(tester.element(find.byType(ForgotPasswordScreen)));
    await tester.tap(find.text(l.authSendCode));
    await tester.pumpAndSettle();
    expect(
      backend.to('POST', '/api/auth/password/reset/request'),
      hasLength(1),
    );
    await tester.enterText(
      find.descendant(
        of: find.byType(CodeEntryField),
        matching: find.byType(TextField),
      ),
      '123',
    );
    await tester.enterText(find.byType(TextFormField).last, 'new-password-123');
    await tester.tap(find.text(l.actionConfirm));
    await tester.pump();
    expect(find.text(l.validationCodeSixDigits), findsOneWidget);
    expect(backend.to('POST', '/api/auth/password/reset/confirm'), isEmpty);
  });
}
