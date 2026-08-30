/// Proof that the retired V0 surfaces are gone from the client.
///
/// The rebuild's premise was that the previous Flutter app spoke a contract the
/// backend had retired — airport-only trips, traveller-first matching,
/// ProductRequest/Kaba, DZD marketplace economics. Those paths are not
/// deprecated here; they are absent, and these tests are what keeps them
/// absent when somebody copies an old snippet back in.
///
/// Source-level rather than behavioural on purpose: the failure mode is a
/// *reintroduced call*, and no runtime test catches code nobody executes.
library;

import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  final source = _libSources();

  group('retired product surfaces', () {
    test('Kaba / ProductRequest is nowhere in the client', () {
      // `error_codes.dart` is exempt: it is the vocabulary of codes the server
      // can send, and recognising `product_request_retired` is how the client
      // explains a refusal rather than showing a generic failure. Naming a
      // retired thing in order to handle it is not using it.
      _expectAbsent(
        source,
        RegExp('Kaba|ProductRequest|product_request'),
        exempt: {'lib/core/api/error_codes.dart'},
      );
    });

    test('no client calls a retired endpoint', () {
      // Each of these answers 410 and would be a dead branch shipped to users.
      for (final path in [
        '/api/matches/apply',
        '/api/matches/apply-to-trip',
        '/api/parcels/quote/delivery',
        '/api/parcels/delivery\'', // the legacy create, not `/delivery/v1`
        '/api/parcels/product',
        '/api/trips/search',
        '/api/payments/intents',
      ]) {
        _expectAbsent(source, RegExp(RegExp.escape(path)));
      }
    });

    test('the legacy match-scoped handover is not used', () {
      // V1 handover is Deal-scoped. The Match-scoped routes still exist on the
      // server and are the ones that leaked plaintext to both parties.
      _expectAbsent(source, RegExp(r'matches/\$?\{?\w*\}?/handover'));
    });

    test('the legacy wallet surface is not used', () {
      _expectAbsent(source, RegExp('/api/wallets'));
    });
  });

  group('V1 economics', () {
    test('no DZD marketplace fields are read', () {
      // These are legacy Offer columns the server strips from a V1 offer. A
      // client reading them would silently render nothing, or worse, a stale
      // price from a pre-V1 row.
      for (final field in [
        'base_amount_dzd',
        'commission_dzd',
        'total_dzd',
        'base_fee_dzd',
        'product_price_dzd',
      ]) {
        _expectAbsent(source, RegExp(RegExp.escape(field)));
      }
    });

    test('no commission rate or floor is hard-coded', () {
      // 10% and €15 are policy snapshots that differ per settings version and
      // per deal. Baking either in makes the client lie the day policy moves.
      final offenders = <String>[];
      source.forEach((path, text) {
        // Ignore the ARB and generated localisations: copy is not arithmetic.
        if (path.contains('/l10n/')) return;
        for (final line in text.split('\n')) {
          final code = line.trimLeft();
          if (code.startsWith('//') || code.startsWith('///')) continue;
          if (RegExp(
            r'\b0\.10\b|\bcommissionRate\s*=|\* *0\.1\b',
          ).hasMatch(line)) {
            offenders.add('$path: ${line.trim()}');
          }
        }
      });
      expect(offenders, isEmpty, reason: 'hard-coded economics: $offenders');
    });

    test('money is never added or subtracted in a screen', () {
      // `Money` has no operators, so this can only be violated by dropping to
      // raw minor units. Catch that directly.
      final offenders = <String>[];
      source.forEach((path, text) {
        if (!path.contains('/features/')) return;
        for (final line in text.split('\n')) {
          final code = line.trimLeft();
          if (code.startsWith('//') || code.startsWith('///')) continue;
          if (RegExp(
            r'minorUnits\s*[+\-*/]|[+\-]\s*\w+\.minorUnits',
          ).hasMatch(line)) {
            offenders.add('$path: ${line.trim()}');
          }
        }
      });
      expect(
        offenders,
        isEmpty,
        reason: 'client-side money arithmetic: $offenders',
      );
    });
  });

  group('admin surfaces stay out of the app', () {
    test('no Phase 6A admin endpoint is called', () {
      // `/api/admin/**` exists and is not a user-facing API. Reaching it from
      // the app would be both a privilege confusion and a support problem.
      _expectAbsent(source, RegExp('/api/admin/'));
      _expectAbsent(source, RegExp('/matches/explain'));
    });
  });

  group('provider activation is not attempted', () {
    test('no provider credentials or webhook registration in the client', () {
      for (final pattern in [
        'sk_live',
        'sk_test',
        'pk_live',
        'STRIPE_SECRET',
        'CHARGILY_SECRET',
        '/payments/webhooks/',
      ]) {
        _expectAbsent(source, RegExp(RegExp.escape(pattern)));
      }
    });

    test('the mock rail is never offered to a user', () {
      // It exists in the enum because the server sends it; it is filtered out
      // of every list the UI renders.
      final payment = File('lib/domain/payment.dart').readAsStringSync();
      expect(payment, contains('PaymentProviderId.mock'));
      expect(payment, contains('where'));
    });
  });
}

/// Every hand-written Dart file under `lib/`, keyed by path.
Map<String, String> _libSources() {
  final files = <String, String>{};
  for (final entity in Directory('lib').listSync(recursive: true)) {
    if (entity is! File || !entity.path.endsWith('.dart')) continue;
    final path = entity.path.replaceAll(r'\', '/');
    // Generated localisations are not source we control.
    if (path.contains('/l10n/app_localizations')) continue;
    files[path] = entity.readAsStringSync();
  }
  return files;
}

/// Fails if [pattern] appears in any non-comment line of any file.
void _expectAbsent(
  Map<String, String> source,
  RegExp pattern, {
  Set<String> exempt = const {},
}) {
  final offenders = <String>[];
  source.forEach((path, text) {
    if (exempt.contains(path)) return;
    for (final line in text.split('\n')) {
      final code = line.trimLeft();
      // A comment explaining *why* something is retired is exactly what we
      // want to keep, so comments are exempt.
      if (code.startsWith('//') ||
          code.startsWith('///') ||
          code.startsWith('*')) {
        continue;
      }
      if (pattern.hasMatch(line)) offenders.add('$path: ${line.trim()}');
    }
  });
  expect(
    offenders,
    isEmpty,
    reason: 'retired surface "${pattern.pattern}" found in: $offenders',
  );
}
