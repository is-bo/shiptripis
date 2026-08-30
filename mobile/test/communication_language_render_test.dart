/// Phase 6D, rendered.
///
/// The bounded visual pass for the two new surfaces. There is no hardware in
/// this loop, so these run at the real device metrics the rest of the suite
/// uses — a 320-point Android, an iPhone with a home indicator, and 1.6×
/// text — and assert the three things a screenshot would have been used to
/// check:
///
/// * nothing overflows;
/// * every new string is the translated one, not the English source leaking
///   through a missing key; and
/// * the direction is the interface's, in a screen that now names three
///   languages at once.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/features/deals/recipient_screen.dart';
import 'package:shiptrip/features/profile/language_screen.dart';
import 'package:shiptrip/l10n/app_localizations.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

Future<ProviderContainer> _signedIn(
  WidgetTester tester,
  FakeBackend backend,
) async {
  final container = containerFor(backend);
  addTearDown(container.dispose);
  await tester.runAsync(
    () => container.read(sessionProvider.notifier).restore(),
  );
  return container;
}

/// Brings the language row into the viewport on the short profiles, where a
/// lazily-built list has not reached it yet.
Future<void> _revealChoice(WidgetTester tester) async {
  final choice = find.byType(AppSegmentedChoice<CommunicationLanguage>);
  if (choice.evaluate().isNotEmpty) return;
  await tester.scrollUntilVisible(
    choice,
    120,
    scrollable: find.byType(Scrollable).first,
  );
}

FakeBackend _profileBackend(String language) => FakeBackend()
  ..on(
    'GET',
    '/api/me',
    FakeResponse(200, meFixture(preferredLanguage: language)),
  );

FakeBackend _recipientBackend(String language) => FakeBackend()
  ..on(
    'GET',
    '/api/me',
    FakeResponse(200, meFixture(preferredLanguage: language)),
  )
  ..on('GET', '/api/deals/7', FakeResponse(200, dealFixture()));

void main() {
  group('the language screen renders', () {
    for (final device in DeviceProfile.all) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        testWidgets('on ${device.name} in ${locale.languageCode}', (
          tester,
        ) async {
          final container = await _signedIn(tester, _profileBackend('ar'));

          await pumpApp(
            tester,
            const LanguageScreen(),
            container: container,
            device: device,
            locale: locale,
          );
          await tester.pumpAndSettle();

          // A RenderFlex overflow is reported as a caught exception, not a
          // failed assertion, so it has to be asked for explicitly.
          expect(
            tester.takeException(),
            isNull,
            reason: 'the screen overflowed on ${device.name}',
          );
        });
      }
    }

    testWidgets('English names both settings and separates them', (
      tester,
    ) async {
      final container = await _signedIn(tester, _profileBackend('en'));
      await pumpApp(tester, const LanguageScreen(), container: container);
      await tester.pumpAndSettle();

      expect(find.text('App language'), findsOneWidget);
      expect(find.text('Email language'), findsOneWidget);

      // The help lines are what carry the distinction. Losing them would leave
      // two identical-looking lists of the same three languages.
      expect(find.textContaining('Stored on this phone'), findsOneWidget);
      expect(find.textContaining('Saved to your account'), findsOneWidget);

      // Both lists offer each language under its own name.
      expect(find.text('English'), findsNWidgets(2));
      expect(find.text('Français'), findsNWidgets(2));
      expect(find.text('العربية'), findsNWidgets(2));
    });

    testWidgets('Arabic runs right-to-left and is actually translated', (
      tester,
    ) async {
      final container = await _signedIn(tester, _profileBackend('en'));

      late BuildContext captured;
      await pumpApp(
        tester,
        Builder(
          builder: (context) {
            captured = context;
            return const LanguageScreen();
          },
        ),
        container: container,
        locale: const Locale('ar'),
      );
      await tester.pumpAndSettle();

      expect(captured.isRtl, isTrue);
      expect(Directionality.of(captured), TextDirection.rtl);

      // Not the English source string.
      final l = L.of(captured);
      expect(l.profileAppLanguage, isNot('App language'));
      expect(l.profileEmailLanguage, isNot('Email language'));
      expect(find.text(l.profileEmailLanguage), findsOneWidget);
      expect(tester.takeException(), isNull);
    });

    testWidgets('French is translated too', (tester) async {
      final container = await _signedIn(tester, _profileBackend('en'));
      await pumpApp(
        tester,
        const LanguageScreen(),
        container: container,
        locale: const Locale('fr'),
      );
      await tester.pumpAndSettle();

      expect(find.text('App language'), findsNothing);
      expect(find.text('Email language'), findsNothing);
      expect(find.text('Langue de l’application'), findsOneWidget);
      expect(find.text('Langue des e-mails'), findsOneWidget);
    });
  });

  group('the recipient form renders', () {
    for (final device in DeviceProfile.all) {
      for (final locale in const [Locale('en'), Locale('fr'), Locale('ar')]) {
        testWidgets('on ${device.name} in ${locale.languageCode}', (
          tester,
        ) async {
          final container = await _signedIn(tester, _recipientBackend('ar'));

          await pumpRouted(
            tester,
            const RecipientScreen(dealId: 7),
            container: container,
            device: device,
            locale: locale,
          );
          await tester.pumpAndSettle();
          await _revealChoice(tester);

          // A RenderFlex overflow is reported as a caught exception, not a
          // failed assertion, so it has to be asked for explicitly.
          final exception = tester.takeException();
          expect(
            exception,
            isNull,
            reason: 'the form overflowed on ${device.name}',
          );

          // Present and laid out, not clipped away by the narrow width or
          // pushed off the bottom by 1.6x text — asserted on every profile,
          // landscape included.
          expect(
            find.byType(AppSegmentedChoice<CommunicationLanguage>),
            findsOneWidget,
          );
        });
      }
    }

    for (final (locale, label, help) in const [
      (Locale('en'), "Recipient's language", 'delivery email'),
      (Locale('fr'), 'Langue du destinataire', 'destinataire'),
      (Locale('ar'), 'لغة المستلِم', 'المستلِم'),
    ]) {
      testWidgets('${locale.languageCode} labels the choice in its own words', (
        tester,
      ) async {
        final container = await _signedIn(tester, _recipientBackend('fr'));

        await pumpRouted(
          tester,
          const RecipientScreen(dealId: 7),
          container: container,
          locale: locale,
        );
        await tester.pumpAndSettle();

        expect(find.text(label), findsOneWidget);
        expect(find.textContaining(help), findsWidgets);

        // Each option under its own name, exactly once — this form has only
        // the one language row.
        expect(find.text('English'), findsOneWidget);
        expect(find.text('Français'), findsOneWidget);
        expect(find.text('العربية'), findsOneWidget);
      });
    }

    testWidgets('the choice is a real tap target on the narrowest phone', (
      tester,
    ) async {
      final container = await _signedIn(tester, _recipientBackend('en'));

      await pumpRouted(
        tester,
        const RecipientScreen(dealId: 7),
        container: container,
        device: DeviceProfile.smallAndroid,
      );
      await tester.pumpAndSettle();
      await _revealChoice(tester);

      for (final label in ['English', 'Français', 'العربية']) {
        final size = tester.getSize(
          find.ancestor(of: find.text(label), matching: find.byType(InkWell)),
        );
        expect(
          size.height,
          greaterThanOrEqualTo(AppSpace.minTapTarget - 4),
          reason: '"$label" is too short to hit',
        );
        expect(size.width, greaterThan(0));
      }
    });

    testWidgets('a locked form still shows the choice, greyed', (tester) async {
      // After pickup the server refuses recipient edits. The choice stays
      // visible — the sender still needs to see which language was used — but
      // it cannot be changed.
      final backend = FakeBackend()
        ..on('GET', '/api/me', FakeResponse(200, meFixture()))
        ..on(
          'GET',
          '/api/deals/7',
          FakeResponse(
            200,
            dealFixture(
              status: 'in_transit',
              recipient: recipientFixture(communicationLanguage: 'ar'),
              pickupConfirmedAt: '2026-08-22T09:00:00Z',
            ),
          ),
        );
      final container = await _signedIn(tester, backend);

      await pumpRouted(
        tester,
        const RecipientScreen(dealId: 7),
        container: container,
      );
      await tester.pumpAndSettle();

      expect(find.text('English'), findsOneWidget);

      // Tapping does nothing: no PUT, and no way to reach one.
      await tester.tap(find.text('Français'));
      await tester.pumpAndSettle();
      expect(backend.to('PUT', '/api/deals/7/recipient'), isEmpty);
    });
  });
}
