/// Signup coverage for the EU↔Algeria account contract.
///
/// The repository and session are real; the fake sits at Dio so these tests
/// assert the JSON that would reach Django, including legacy compatibility.
library;

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/features/auth/sign_up_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

FakeResponse _signupResponse(RecordedRequest request) {
  final user = meFixture(preferredLanguage: request.body['preferred_language'])
    ..['wilaya'] = request.body['wilaya'] ?? '';
  return FakeResponse(201, {
    'access': 'access-token',
    'refresh': 'refresh-token',
    'user': user,
  });
}

FakeBackend _backend() =>
    FakeBackend()..handle('POST', '/api/auth/sign-up', _signupResponse);

void main() {
  group('signup wilaya compatibility', () {
    testWidgets('the active signup form has no Algeria-only wilaya field', (
      tester,
    ) async {
      await pumpApp(tester, const SignUpScreen());
      await tester.pumpAndSettle();

      expect(find.text('Wilaya'), findsNothing);
      expect(find.textContaining('wilaya'), findsNothing);
    });

    test(
      'EU sender/traveler account omits the Algerian profile hint',
      () async {
        final backend = _backend();
        final container = containerFor(
          backend,
          tokens: FakeTokenStore(refresh: null),
        );
        addTearDown(container.dispose);

        await container
            .read(sessionProvider.notifier)
            .signUp(
              fullName: 'Sender in Paris',
              email: 'paris@example.eu',
              password: 'correct horse battery',
              phone: '+331555000111',
              preferredLanguage: CommunicationLanguage.french,
            );

        final request = backend.lastTo('POST', '/api/auth/sign-up')!;
        expect(request.body, isNot(contains('wilaya')));
        final account = container.read(accountProvider)!;
        expect(account.wilaya, isEmpty);
        expect(account.role, AccountRole.both);
        expect(account.role.canSend, isTrue);
        expect(account.role.canTravel, isTrue);
        expect(account.preferredLanguage.wire, 'fr');
      },
    );

    test(
      'Algeria-side legacy clients can still send a validated wilaya',
      () async {
        final backend = _backend();
        final container = containerFor(
          backend,
          tokens: FakeTokenStore(refresh: null),
        );
        addTearDown(container.dispose);

        await container
            .read(sessionProvider.notifier)
            .signUp(
              fullName: 'Traveler in Algiers',
              email: 'algiers@example.dz',
              password: 'correct horse battery',
              phone: '+213555000111',
              wilaya: '16',
              preferredLanguage: CommunicationLanguage.arabic,
            );

        final request = backend.lastTo('POST', '/api/auth/sign-up')!;
        expect(request.body['wilaya'], '16');
        expect(container.read(accountProvider)!.role, AccountRole.both);
      },
    );
  });
}
