/// The release-critical invariant, asserted rather than trusted.
///
/// **The traveller must never be able to retrieve the delivery code.** The
/// server refuses them with 403, but a client bug could still put the code on
/// a traveller's screen by calling the sender's endpoint from the wrong branch
/// — so these tests check the client side of the promise directly:
///
/// * the traveller's delivery screen renders no reveal affordance;
/// * `revealDeliveryCode` is called from exactly one place in the codebase;
/// * a `RevealedCode` cannot leak through `toString()` into a log or a crash
///   report;
/// * nothing in the app writes a code to storage.
///
/// The source-level checks are unusual for a widget test and deliberate: this
/// invariant is one careless `if` away from being broken, and a compile-time
/// grep is the only thing that catches that reliably.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:shiptrip/domain/deal.dart';
import 'package:shiptrip/domain/handover.dart';

void main() {
  group('delivery-code isolation', () {
    test('the sender reveal endpoint is called from exactly one place', () {
      final hits = _grepLib(
        RegExp(r'\.revealDeliveryCode\('),
        // The repository is the definition, not a call site.
        exclude: {'lib/data/repositories.dart'},
      );

      expect(
        hits.length,
        1,
        reason:
            'revealDeliveryCode must have exactly one call site so the '
            'sender-only guard around it can be reviewed in one place. '
            'Found: $hits',
      );
      expect(
        hits.single,
        contains('delivery_screen.dart'),
        reason: 'the only caller must be the sender branch of DeliveryScreen',
      );
    });

    test('no traveller-facing screen imports a reveal path', () {
      // A traveller only ever *types* a code. Any reveal call outside the
      // delivery/pickup screens would mean a second, unreviewed path.
      final hits = _grepLib(
        RegExp(r'\.reveal(Delivery|Pickup)Code\('),
        exclude: {'lib/data/repositories.dart'},
      );
      for (final file in hits) {
        expect(
          file,
          anyOf(
            contains('delivery_screen.dart'),
            contains('pickup_screen.dart'),
          ),
          reason: 'unexpected code-reveal call in $file',
        );
      }
    });

    test('a revealed code never renders itself into a string', () {
      const code = RevealedCode(
        code: 'ABCD1234',
        formatted: 'ABCD-1234',
        kind: HandoverKind.delivery,
      );

      // `toString` is what ends up in a crash report, a log line, or an
      // `'$object'` interpolation somebody adds in a hurry.
      expect(code.toString(), isNot(contains('ABCD1234')));
      expect(code.toString(), isNot(contains('ABCD-1234')));
      expect(code.toString(), contains('redacted'));
    });

    test('the handover state carries no code material', () {
      // The same payload reaches both parties. If it ever grew a code field,
      // the traveller would receive it.
      final state = HandoverState.maybe(const {
        'deal_status': 'picked_up',
        'delivery_code_available_at': '2026-08-29T10:30:00Z',
        'in_delivery_code_buffer': true,
        'pickup': {'exists': true, 'status': 'used', 'rotation': 1},
        'delivery': {'exists': true, 'status': 'buffered', 'rotation': 1},
        'can_reveal_pickup_code': false,
        'can_reveal_delivery_code': false,
        'traveler_can_view_delivery_code': false,
        'can_submit_pickup_code': false,
        'can_submit_delivery_code': false,
      })!;

      expect(state.travelerCanViewDeliveryCode, isFalse);
      expect(state.inDeliveryCodeBuffer, isTrue);
      expect(state.deliveryCodeAvailableAt, isNotNull);
    });

    test('nothing writes a handover code to storage', () {
      final storageWriters = _grepLib(RegExp(r'\.write\(\s*key:'));
      // Token storage is the only place anything is persisted at all, and it
      // stores tokens, a role and a locale — never code material.
      for (final file in storageWriters) {
        expect(
          file,
          contains('token_store.dart'),
          reason: 'unexpected secure-storage write in $file',
        );
      }

      // And the keys it writes are exactly the four it is allowed to hold.
      final store = File(
        'lib/core/session/token_store.dart',
      ).readAsStringSync();
      final written = RegExp(
        r'\.write\(\s*key:\s*(_k[A-Za-z]+)',
      ).allMatches(store).map((m) => m.group(1)).toSet();
      expect(
        written,
        {'_kAccess', '_kRefresh', '_kRoleContext', '_kLocale'},
        reason:
            'token storage may hold tokens, a role and a locale — '
            'never code material, a guest token or recipient details',
      );
    });

    test('nothing logs anything', () {
      // `print` and `debugPrint` are how a code, a token or a recipient email
      // ends up in a device log. There is no legitimate use in this app.
      final printers = _grepLib(RegExp(r'(?<![A-Za-z_.])(debugPrint|print)\('));
      expect(printers, isEmpty, reason: 'logging found in $printers');
    });

    test('the retired build\'s persisted code artefacts are purged', () {
      final store = File(
        'lib/core/session/token_store.dart',
      ).readAsStringSync();
      // The previous build persisted handover codes. Every launch deletes
      // those keys, so an upgrading device does not keep them on disk.
      expect(store, contains('purgeLegacyArtifacts'));
      expect(store, contains('handover.codes'));
    });
  });

  // -------------------------------------------------------------------------
  // The recipient projection, after Phase 6D added a language to it
  // -------------------------------------------------------------------------

  group('the recipient projection stays traveller-safe', () {
    test('a traveller is given no address and no language', () {
      // This is the payload the server actually sends a carrying traveller:
      // who to hand the parcel to, and the note. The delivery-code email is
      // addressed and written by the server alone, and neither the mailbox nor
      // the language it is written in is the traveller's to see.
      final view = RecipientView.maybe(const {
        'recorded': true,
        'full_name': 'Yacine Haddad',
        'delivery_note': 'Second floor, blue door.',
      });

      expect(view!.email, isNull);
      expect(view.phone, isNull);
      expect(view.communicationLanguage, isNull);
      expect(view.isFullRecord, isFalse);
    });

    test('a recipient never renders its details into a string', () {
      // Adding a field to a model is exactly how a redacted `toString` stops
      // being redacted. The email is the delivery-code destination, so this is
      // the same class of leak as a code in a crash report.
      final view = RecipientView.maybe(const {
        'full_name': 'Yacine Haddad',
        'email': 'yacine@example.com',
        'phone': '+213770112233',
        'delivery_note': 'Second floor, blue door.',
        'communication_language': 'ar',
        'revision': 1,
      })!;

      expect(view.toString(), isNot(contains('yacine@example.com')));
      expect(view.toString(), isNot(contains('+213770112233')));
      expect(view.toString(), contains('redacted'));
    });

    test('the language selector is on the sender screen only', () {
      // The recipient form is sender-gated by the server, and it is the only
      // place the choice exists. A traveller-facing screen reaching for it
      // would mean a second, unreviewed surface onto recipient data.
      final hits = _grepLib(RegExp(r'_language\s*=|communicationLanguage:'));
      for (final file in hits) {
        expect(
          file,
          anyOf(
            contains('recipient_screen.dart'),
            contains('repositories.dart'),
            contains('domain/deal.dart'),
            contains('domain/payment.dart'),
          ),
          reason: 'unexpected recipient-language write in $file',
        );
      }
    });
  });
}

/// Scans `lib/` for [pattern] and returns the matching file paths.
List<String> _grepLib(RegExp pattern, {Set<String> exclude = const {}}) {
  final matches = <String>[];
  for (final entity in Directory('lib').listSync(recursive: true)) {
    if (entity is! File || !entity.path.endsWith('.dart')) continue;
    final path = entity.path.replaceAll(r'\', '/');
    if (exclude.any(path.endsWith)) continue;
    // Generated localisations are not hand-written source.
    if (path.contains('/l10n/app_localizations')) continue;

    for (final line in entity.readAsLinesSync()) {
      final code = line.trimLeft();
      if (code.startsWith('//') || code.startsWith('///')) continue;
      if (pattern.hasMatch(line)) {
        matches.add(path);
        break;
      }
    }
  }
  return matches;
}
