/// Phase 6D: the language ShipTrip writes to somebody in.
///
/// Two things are being defended here, and they are different things.
///
/// **The contract.** `preferred_language` and `communication_language` are
/// enums the server rejects anything outside of, and the client's job is to
/// send exactly `"en"`, `"fr"` or `"ar"` at exactly the right key — or to send
/// nothing, which on the recipient endpoint is itself meaningful. So the tests
/// run through the real repositories onto a fake Dio adapter and then read the
/// JSON that would have reached Django.
///
/// **The distinction.** App language is the interface; communication language
/// is the mail. They are independent, and the combination that has to work is
/// the awkward one: an Arabic email chosen from a French interface must not
/// turn the app around.
library;

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/app/app_settings.dart';
import 'package:shiptrip/core/session/session.dart';
import 'package:shiptrip/data/repositories.dart';
import 'package:shiptrip/design/components/forms.dart';
import 'package:shiptrip/design/tokens.dart';
import 'package:shiptrip/domain/account.dart';
import 'package:shiptrip/domain/communication_language.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/payment.dart';
import 'package:shiptrip/features/deals/recipient_screen.dart';
import 'package:shiptrip/features/profile/language_screen.dart';

import 'support/fake_api.dart';
import 'support/harness.dart';

/// Signs in through the real controller so every screen below sees the account
/// the fake `/api/me` describes.
///
/// Runs under [WidgetTester.runAsync] because `testWidgets` installs a fake
/// clock, and a `Future` that never gets a pump to flush it never completes.
/// The sign-in has to finish *before* the first frame, or the screen renders
/// its signed-out placeholder and the assertions below measure the wrong
/// thing.
Future<void> _signIn(WidgetTester tester, ProviderContainer container) =>
    tester.runAsync(() => container.read(sessionProvider.notifier).restore());

void main() {
  // -------------------------------------------------------------------------
  // The enum itself
  // -------------------------------------------------------------------------

  group('language values', () {
    test('the three supported values map to the wire strings', () {
      expect(CommunicationLanguage.english.wire, 'en');
      expect(CommunicationLanguage.french.wire, 'fr');
      expect(CommunicationLanguage.arabic.wire, 'ar');
      // A fourth value would be rejected by the server's ChoiceField.
      expect(CommunicationLanguage.values.length, 3);
    });

    test('a blank or missing legacy value resolves to English', () {
      // Mirrors `apps.core.languages.normalize_communication_language`.
      expect(CommunicationLanguage.parse(null), CommunicationLanguage.english);
      expect(CommunicationLanguage.parse(''), CommunicationLanguage.english);
      expect(CommunicationLanguage.parse('   '), CommunicationLanguage.english);
      expect(CommunicationLanguage.parse('de'), CommunicationLanguage.english);
      expect(CommunicationLanguage.parse(7), CommunicationLanguage.english);
    });

    test('casing and a region tag still resolve', () {
      expect(CommunicationLanguage.parse('AR'), CommunicationLanguage.arabic);
      expect(
        CommunicationLanguage.parse('fr-DZ'),
        CommunicationLanguage.french,
      );
      expect(
        CommunicationLanguage.parse(' en '),
        CommunicationLanguage.english,
      );
    });

    test('`maybe` keeps "absent" distinguishable from "English"', () {
      // The recipient projection omits the key for a traveller. That is not
      // the same statement as "the recipient reads English".
      expect(CommunicationLanguage.maybe(null), isNull);
      expect(CommunicationLanguage.maybe(''), CommunicationLanguage.english);
      expect(CommunicationLanguage.maybe('ar'), CommunicationLanguage.arabic);
    });

    test('only Arabic lays its own label out right-to-left', () {
      expect(CommunicationLanguage.arabic.isRtlLabel, isTrue);
      expect(CommunicationLanguage.french.isRtlLabel, isFalse);
      expect(CommunicationLanguage.english.isRtlLabel, isFalse);
    });

    test('every option is named in its own language', () {
      expect(CommunicationLanguage.english.nativeLabel, 'English');
      expect(CommunicationLanguage.french.nativeLabel, 'Français');
      expect(CommunicationLanguage.arabic.nativeLabel, 'العربية');
    });
  });

  // -------------------------------------------------------------------------
  // Parsing the profile
  // -------------------------------------------------------------------------

  group('profile parsing', () {
    Account parse(Object? value) =>
        Account.fromJson(meFixture(preferredLanguage: value));

    test('English, French and Arabic each parse', () {
      expect(parse('en').preferredLanguage, CommunicationLanguage.english);
      expect(parse('fr').preferredLanguage, CommunicationLanguage.french);
      expect(parse('ar').preferredLanguage, CommunicationLanguage.arabic);
    });

    test('a legacy account with a blank value reads as English', () {
      expect(parse('').preferredLanguage, CommunicationLanguage.english);
      expect(parse(null).preferredLanguage, CommunicationLanguage.english);
    });

    test('a deployment that omits the key entirely still parses', () {
      final json = meFixture()..remove('preferred_language');
      expect(
        Account.fromJson(json).preferredLanguage,
        CommunicationLanguage.english,
      );
    });
  });

  group('recipient parsing', () {
    test('the sender projection carries the stored language', () {
      final view = RecipientView.maybe(
        recipientFixture(communicationLanguage: 'fr'),
      );
      expect(view!.communicationLanguage, CommunicationLanguage.french);
      expect(view.isFullRecord, isTrue);
    });

    test('a legacy blank row reads as English', () {
      final view = RecipientView.maybe(
        recipientFixture(communicationLanguage: ''),
      );
      expect(view!.communicationLanguage, CommunicationLanguage.english);
    });

    test('the traveller projection has no language at all', () {
      // The traveller gets `recorded`, a name and a note once carrying — never
      // the email, and nothing about how the recipient is written to.
      final view = RecipientView.maybe(const {
        'recorded': true,
        'full_name': 'Yacine Haddad',
        'delivery_note': 'Second floor, blue door.',
      });
      expect(view!.communicationLanguage, isNull);
      expect(view.isFullRecord, isFalse);
    });
  });

  // -------------------------------------------------------------------------
  // Profile: reading and writing the account preference
  // -------------------------------------------------------------------------

  group('profile communication language', () {
    testWidgets('a legacy blank value shows English selected, not nothing', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, meFixture(preferredLanguage: '')),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      await pumpApp(tester, const LanguageScreen(), container: container);
      await tester.pumpAndSettle();

      expect(_selectedEmailLanguage(tester), CommunicationLanguage.english);
    });

    for (final (value, expected) in [
      ('en', CommunicationLanguage.english),
      ('fr', CommunicationLanguage.french),
      ('ar', CommunicationLanguage.arabic),
    ]) {
      testWidgets('a stored "$value" is the one option ticked', (tester) async {
        final backend = FakeBackend()
          ..on(
            'GET',
            '/api/me',
            FakeResponse(200, meFixture(preferredLanguage: value)),
          );
        final container = containerFor(backend);
        addTearDown(container.dispose);
        await _signIn(tester, container);

        await pumpApp(tester, const LanguageScreen(), container: container);
        await tester.pumpAndSettle();

        expect(_selectedEmailLanguage(tester), expected);
      });
    }

    testWidgets('changing the value PATCHes /api/me with the wire string', (
      tester,
    ) async {
      var stored = 'en';
      final backend = FakeBackend()
        ..handle(
          'GET',
          '/api/me',
          (_) => FakeResponse(200, meFixture(preferredLanguage: stored)),
        )
        ..handle('PATCH', '/api/me', (request) {
          stored = request.body['preferred_language'] as String;
          return FakeResponse(200, meFixture(preferredLanguage: stored));
        });
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      await pumpApp(tester, const LanguageScreen(), container: container);
      await tester.pumpAndSettle();

      await tester.tap(find.text('العربية').last);
      await tester.pumpAndSettle();

      final patch = backend.lastTo('PATCH', '/api/me');
      expect(patch, isNotNull, reason: 'the change must reach the server');
      // The exact key and the exact value the server's ChoiceField accepts.
      expect(patch!.body, {'preferred_language': 'ar'});

      // And the app now holds what the server returned, not what was asked
      // for — they happen to agree here, and the point is that it re-read.
      expect(_selectedEmailLanguage(tester), CommunicationLanguage.arabic);
      expect(
        container.read(accountProvider)?.preferredLanguage,
        CommunicationLanguage.arabic,
      );
    });

    testWidgets('a server error leaves the old value selected and says so', (
      tester,
    ) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, meFixture(preferredLanguage: 'en')),
        )
        ..on(
          'PATCH',
          '/api/me',
          const FakeResponse(500, {'detail': 'Server error.'}),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      await pumpApp(tester, const LanguageScreen(), container: container);
      await tester.pumpAndSettle();

      await tester.tap(find.text('Français').last);
      await tester.pumpAndSettle();

      // Not moved optimistically: the account still says English, because
      // English is still what the server would put in an email.
      expect(_selectedEmailLanguage(tester), CommunicationLanguage.english);
      expect(
        container.read(accountProvider)?.preferredLanguage,
        CommunicationLanguage.english,
      );

      // And the failure is stated in place, not only in a snackbar that has
      // already gone by the time the user looks.
      expect(find.textContaining('Try again'), findsWidgets);
    });

    testWidgets('the app language is not sent to the server', (tester) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, meFixture(preferredLanguage: 'en')),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      await pumpApp(tester, const LanguageScreen(), container: container);
      await tester.pumpAndSettle();

      // Tapping an *app* language is a device setting. Nothing about it
      // belongs on the account, and a PATCH here would be the silent
      // overwrite the phase explicitly forbids.
      await tester.tap(find.text('Français').first);
      await tester.pumpAndSettle();

      expect(backend.to('PATCH', '/api/me'), isEmpty);
      expect(
        container.read(accountProvider)?.preferredLanguage,
        CommunicationLanguage.english,
      );
    });
  });

  // -------------------------------------------------------------------------
  // Recipient
  // -------------------------------------------------------------------------

  group('recipient communication language', () {
    /// Builds the screen for a deal with (or without) a recipient already on
    /// it, and returns the backend so the test can read what was PUT.
    Future<FakeBackend> open(
      WidgetTester tester, {
      required String senderLanguage,
      Map<String, dynamic>? recipient,
      Locale locale = const Locale('en'),
    }) async {
      final backend = FakeBackend()
        ..on(
          'GET',
          '/api/me',
          FakeResponse(200, meFixture(preferredLanguage: senderLanguage)),
        )
        ..on(
          'GET',
          '/api/deals/7',
          FakeResponse(200, dealFixture(recipient: recipient)),
        )
        ..handle(
          'PUT',
          '/api/deals/7/recipient',
          (_) => FakeResponse(200, {'deal': dealFixture(recipient: recipient)}),
        );

      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      await pumpRouted(
        tester,
        const RecipientScreen(dealId: 7),
        container: container,
        locale: locale,
      );
      await tester.pumpAndSettle();
      return backend;
    }

    testWidgets('a new recipient defaults to the sender\'s own language', (
      tester,
    ) async {
      final backend = await open(tester, senderLanguage: 'fr');

      await _fillRecipient(tester);
      await _save(tester);

      final put = backend.lastTo('PUT', '/api/deals/7/recipient');
      expect(put!.body['communication_language'], 'fr');
    });

    testWidgets('the default is never guessed from the recipient', (
      tester,
    ) async {
      // An Arabic-speaking sender addressing `pierre@laposte.fr` still gets
      // Arabic. Nothing about the name, the address or its domain may move it.
      final backend = await open(tester, senderLanguage: 'ar');

      await _fillRecipient(tester, email: 'pierre.dubois@laposte.fr');
      await _save(tester);

      expect(
        backend
            .lastTo('PUT', '/api/deals/7/recipient')!
            .body['communication_language'],
        'ar',
      );
    });

    for (final (label, wire) in [
      ('English', 'en'),
      ('Français', 'fr'),
      ('العربية', 'ar'),
    ]) {
      testWidgets('the sender can choose $label explicitly', (tester) async {
        final backend = await open(tester, senderLanguage: 'en');

        await _fillRecipient(tester);
        await tester.tap(find.text(label));
        await tester.pumpAndSettle();
        await _save(tester);

        expect(
          backend
              .lastTo('PUT', '/api/deals/7/recipient')!
              .body['communication_language'],
          wire,
        );
      });
    }

    testWidgets('editing preserves the stored value, not the sender\'s', (
      tester,
    ) async {
      // The stored recipient reads Arabic; the sender's own preference is
      // French. Correcting a phone number must not rewrite the recipient's
      // language to French.
      final backend = await open(
        tester,
        senderLanguage: 'fr',
        recipient: recipientFixture(communicationLanguage: 'ar'),
      );

      await tester.enterText(_field('Phone (optional)'), '+213770999888');
      await _save(tester);

      expect(
        backend
            .lastTo('PUT', '/api/deals/7/recipient')!
            .body['communication_language'],
        'ar',
      );
    });

    testWidgets(
      'a legacy blank recipient edits as English, not as the sender',
      (tester) async {
        final backend = await open(
          tester,
          senderLanguage: 'ar',
          recipient: recipientFixture(communicationLanguage: ''),
        );

        await _save(tester);

        // English is the server's own fallback for that row. Substituting the
        // sender's Arabic here would be inventing intent at migration time.
        expect(
          backend
              .lastTo('PUT', '/api/deals/7/recipient')!
              .body['communication_language'],
          'en',
        );
      },
    );

    testWidgets('a deployment that omits the field also edits as English', (
      tester,
    ) async {
      final backend = await open(
        tester,
        senderLanguage: 'ar',
        recipient: recipientFixture(includeLanguage: false),
      );

      await _save(tester);

      expect(
        backend
            .lastTo('PUT', '/api/deals/7/recipient')!
            .body['communication_language'],
        'en',
      );
    });

    testWidgets('changing an existing value sends the new one', (tester) async {
      final backend = await open(
        tester,
        senderLanguage: 'en',
        recipient: recipientFixture(communicationLanguage: 'en'),
      );

      await tester.tap(find.text('العربية'));
      await tester.pumpAndSettle();
      await _save(tester);

      expect(
        backend
            .lastTo('PUT', '/api/deals/7/recipient')!
            .body['communication_language'],
        'ar',
      );
    });

    testWidgets('the rest of the recipient payload is unchanged', (
      tester,
    ) async {
      final backend = await open(tester, senderLanguage: 'en');

      await _fillRecipient(tester);
      await _save(tester);

      final body = backend.lastTo('PUT', '/api/deals/7/recipient')!.body;
      expect(body.keys.toSet(), {
        'full_name',
        'email',
        'phone',
        'delivery_note',
        'communication_language',
      });
    });
  });

  // -------------------------------------------------------------------------
  // App language versus communication language
  // -------------------------------------------------------------------------

  group('app language and communication language stay independent', () {
    /// The combinations that break if the two settings are conflated.
    for (final (app, mail) in [
      (Locale('ar'), 'en'),
      (Locale('ar'), 'fr'),
      (Locale('en'), 'ar'),
      (Locale('fr'), 'ar'),
    ]) {
      testWidgets(
        '${app.languageCode} interface with $mail mail renders both',
        (tester) async {
          final backend = FakeBackend()
            ..on(
              'GET',
              '/api/me',
              FakeResponse(200, meFixture(preferredLanguage: mail)),
            );
          final container = containerFor(backend);
          addTearDown(container.dispose);
          await _signIn(tester, container);

          late bool isRtl;
          await pumpApp(
            tester,
            Builder(
              builder: (context) {
                isRtl = context.isRtl;
                return const LanguageScreen();
              },
            ),
            container: container,
            locale: app,
          );
          await tester.pumpAndSettle();

          // Direction follows the *app* language and nothing else. Arabic mail
          // from a French interface must not mirror the app.
          expect(
            isRtl,
            app.languageCode == 'ar',
            reason: 'direction must follow the interface, not the mail',
          );

          expect(
            _selectedEmailLanguage(tester),
            CommunicationLanguage.parse(mail),
          );
        },
      );
    }

    testWidgets('choosing Arabic mail from a French app does not mirror it', (
      tester,
    ) async {
      var stored = 'fr';
      final backend = FakeBackend()
        ..handle(
          'GET',
          '/api/me',
          (_) => FakeResponse(200, meFixture(preferredLanguage: stored)),
        )
        ..handle('PATCH', '/api/me', (request) {
          stored = request.body['preferred_language'] as String;
          return FakeResponse(200, meFixture(preferredLanguage: stored));
        });
      final container = containerFor(backend);
      addTearDown(container.dispose);
      await _signIn(tester, container);

      late bool isRtl;
      await pumpApp(
        tester,
        Builder(
          builder: (context) {
            isRtl = context.isRtl;
            return const LanguageScreen();
          },
        ),
        container: container,
        locale: const Locale('fr'),
      );
      await tester.pumpAndSettle();

      await tester.tap(find.text('العربية').last);
      await tester.pumpAndSettle();

      expect(stored, 'ar');
      expect(container.read(localeProvider), isNull);
      expect(isRtl, isFalse, reason: 'the app stays left-to-right');
    });
  });

  // -------------------------------------------------------------------------
  // Guest payment
  // -------------------------------------------------------------------------

  group('guest payment link', () {
    test(
      'an explicit language reaches the server at the documented key',
      () async {
        final backend = FakeBackend()
          ..handle(
            'POST',
            '/api/payments/orders/ORD-1/guest-link',
            (_) => FakeResponse(201, {
              'token': 'opaque',
              'expires_at': '2026-09-01T00:00:00Z',
              'amount_eur_cents': 4200,
              'currency': 'EUR',
              'communication_language': 'ar',
            }),
          );
        final container = containerFor(backend);
        addTearDown(container.dispose);

        final link = await container
            .read(paymentRepositoryProvider)
            .createGuestLink(
              reference: 'ORD-1',
              communicationLanguage: CommunicationLanguage.arabic,
            );

        expect(
          backend.lastTo('POST', '/api/payments/orders/ORD-1/guest-link')!.body,
          {'communication_language': 'ar'},
        );
        // The snapshot the server took is what the issuer is told about.
        expect(link.communicationLanguage, CommunicationLanguage.arabic);
      },
    );

    test('omitting it lets the server snapshot the owner preference', () async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          '/api/payments/orders/ORD-1/guest-link',
          (_) => FakeResponse(201, {
            'token': 'opaque',
            'currency': 'EUR',
            'amount_eur_cents': 4200,
            'communication_language': 'fr',
          }),
        );
      final container = containerFor(backend);
      addTearDown(container.dispose);

      final link = await container
          .read(paymentRepositoryProvider)
          .createGuestLink(reference: 'ORD-1');

      // No key at all — not `null`, which the server's ChoiceField would
      // reject, and not a guessed value.
      expect(
        backend
            .lastTo('POST', '/api/payments/orders/ORD-1/guest-link')!
            .body
            .containsKey('communication_language'),
        isFalse,
      );
      expect(link.communicationLanguage, CommunicationLanguage.french);
    });

    test('a link still redacts its token when printed', () {
      const link = GuestPaymentLink(
        token: 'super-secret-token',
        currency: 'EUR',
        communicationLanguage: CommunicationLanguage.english,
      );
      expect(link.toString(), isNot(contains('super-secret-token')));
    });
  });

  // -------------------------------------------------------------------------
  // Sign-up
  // -------------------------------------------------------------------------

  group('sign-up', () {
    test('the account is created with an explicit language', () async {
      final backend = FakeBackend()
        ..handle(
          'POST',
          '/api/auth/sign-up',
          (request) => FakeResponse(201, {
            'access': 'a',
            'refresh': 'r',
            'user': meFixture(
              preferredLanguage: request.body['preferred_language'],
            ),
          }),
        );
      // No stored credential: this is a first launch, so `restore()` must not
      // go looking for a profile that does not exist yet.
      final container = containerFor(
        backend,
        tokens: FakeTokenStore(refresh: null),
      );
      addTearDown(container.dispose);

      await container
          .read(sessionProvider.notifier)
          .signUp(
            fullName: 'Amina Bouzid',
            email: 'sender@example.com',
            password: 'correct horse battery',
            phone: '+213555000111',
            preferredLanguage: CommunicationLanguage.arabic,
          );

      expect(
        backend.lastTo('POST', '/api/auth/sign-up')!.body['preferred_language'],
        'ar',
      );
      expect(
        container.read(accountProvider)?.preferredLanguage,
        CommunicationLanguage.arabic,
      );
    });
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Which email-language option currently carries the tick.
///
/// Read from the rendered tree rather than from the provider, so the test
/// fails if the screen and the account ever disagree.
CommunicationLanguage _selectedEmailLanguage(WidgetTester tester) {
  final selected = <CommunicationLanguage>[];
  for (final language in CommunicationLanguage.values) {
    // `.last` — the app-language list above shows the same three names, and
    // the email list is the one underneath it.
    final finder = find.ancestor(
      of: find.text(language.nativeLabel).last,
      matching: find.byType(Semantics),
    );
    final nodes = tester.widgetList<Semantics>(finder);
    if (nodes.any((s) => s.properties.selected ?? false)) {
      selected.add(language);
    }
  }
  expect(
    selected,
    hasLength(1),
    reason: 'exactly one email language must be selected, got $selected',
  );
  return selected.single;
}

/// The input belonging to one [AppTextField], located by its visible label.
///
/// The label is a sibling above the field, not an ancestor of it, so this goes
/// up to the `AppTextField` first and back down to its `TextFormField`.
Finder _field(String label) => find.descendant(
  of: find.ancestor(of: find.text(label), matching: find.byType(AppTextField)),
  matching: find.byType(TextFormField),
);

Future<void> _fillRecipient(
  WidgetTester tester, {
  String name = 'Yacine Haddad',
  String email = 'yacine@example.com',
}) async {
  await tester.enterText(_field("Recipient's name"), name);
  await tester.enterText(_field("Recipient's email"), email);
  await tester.pumpAndSettle();
}

Future<void> _save(WidgetTester tester) async {
  await tester.tap(find.text('Save recipient'));
  await tester.pumpAndSettle();
}
