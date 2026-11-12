/// L2B: the discovery copy exists in all three languages, says something in
/// each, and carries the same placeholders.
///
/// The ARB files are read as data, so a key added to English and forgotten in
/// French or Arabic fails here and not on a member's phone.
library;

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

Map<String, dynamic> _arb(String code) =>
    jsonDecode(File('lib/l10n/app_$code.arb').readAsStringSync())
        as Map<String, dynamic>;

Set<String> _keys(Map<String, dynamic> arb) =>
    arb.keys.where((k) => !k.startsWith('@')).toSet();

/// The placeholder names English declares for [key].
Set<String> _declared(Map<String, dynamic> en, String key) {
  final meta = en['@$key'] as Map<String, dynamic>?;
  final placeholders = meta?['placeholders'] as Map<String, dynamic>?;
  return {...?placeholders?.keys};
}

/// Text with placeholders, ICU keywords and the product name removed: what a
/// reader actually reads.
String _prose(String message) => message
    .replaceAll(RegExp(r'\{\w+\}'), '')
    .replaceAll(RegExp(r'\b(plural|select|other|one|few|many|zero|two)\b'), '')
    .replaceAll(RegExp(r'\{\w+,'), '')
    .replaceAll('Wassla', '');

/// The screens and sections this package added, by key prefix.
final _discoveryKeys = RegExp(
  r'^(alert|browse|carry|corridor|discovery|focus|optIn|person|public|reject'
  r'|trip|homeMatches|homeTrips|homeRequests|homeListings|homePeople'
  r'|notificationRouteAlert|notificationTravelerInterested|requestCarry'
  r'|requestCard|requestOffered)',
);

/// A name that reads the same in French. Anything else equal to English is a
/// string somebody forgot to translate.
const _sameInFrench = {'countryFrance'};

void main() {
  final en = _arb('en');
  final fr = _arb('fr');
  final ar = _arb('ar');

  test('French and Arabic carry exactly English\'s keys', () {
    expect(_keys(fr).difference(_keys(en)), isEmpty, reason: 'only in fr');
    expect(_keys(ar).difference(_keys(en)), isEmpty, reason: 'only in ar');
    expect(_keys(en).difference(_keys(fr)), isEmpty, reason: 'missing in fr');
    expect(_keys(en).difference(_keys(ar)), isEmpty, reason: 'missing in ar');
  });

  test('the generator reports nothing untranslated', () {
    final report = File('l10n_untranslated.json').readAsStringSync().trim();
    expect(jsonDecode(report), isEmpty);
  });

  test('every language uses each placeholder English declares', () {
    for (final key in _keys(en)) {
      for (final name in _declared(en, key)) {
        for (final (code, arb) in [('fr', fr), ('ar', ar)]) {
          expect(
            (arb[key] as String).contains('{$name'),
            isTrue,
            reason: '$code: $key lacks {$name}',
          );
        }
      }
    }
  });

  test('no discovery copy is empty or left in English', () {
    final copy = _keys(en).where(_discoveryKeys.hasMatch);
    expect(copy.length, greaterThan(100), reason: 'the family is found');
    for (final key in copy) {
      for (final (code, arb) in [('fr', fr), ('ar', ar)]) {
        final text = arb[key] as String;
        expect(text.trim(), isNotEmpty, reason: '$code: $key');
        if (code == 'fr' && _sameInFrench.contains(key)) continue;
        // A string that is only placeholders and punctuation has no language.
        if (!RegExp(r'\p{L}', unicode: true).hasMatch(_prose(text))) continue;
        expect(text, isNot(en[key]), reason: '$code: $key is still English');
      }
    }
  });

  test('Arabic copy uses Arabic script, not a French or English leftover', () {
    final latin = RegExp(r'[A-Za-z]{4,}');
    for (final key in _keys(en).where(_discoveryKeys.hasMatch)) {
      final prose = _prose(ar[key] as String);
      expect(
        latin.hasMatch(prose),
        isFalse,
        reason: 'ar: $key has Latin text: ${ar[key]}',
      );
    }
  });
}
